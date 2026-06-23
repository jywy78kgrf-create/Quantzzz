"""Mission-control cockpit: an always-on, self-refreshing visual dashboard.

Serves a single dark "fund cockpit" page (dashboards/cockpit.html) plus a JSON
state API straight from the SQLite DB — stdlib HTTP server, no new
dependencies. With --auto-sync it periodically pulls the repo and adopts the
committed seed, so the page tracks the GitHub-run fund with zero interaction.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import BENCHMARKS, PROJECT_ROOT, Config
from .data.snapshots import SnapshotStore
from .db import get_conn

HTML_PATH = PROJECT_ROOT / "dashboards" / "cockpit.html"


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _forward_realized(conn, store, fund: str, golive_ts: str) -> float:
    """Realized P&L earned strictly inside the forward window.

    A position carried into go-live (opened during the backtest/replay and still
    held when live trading started) keeps its cheap historical cost basis, so
    booking its full exit-minus-entry gain credits pre-track appreciation to the
    live record. Re-base any such trade to its go-live close — only the
    go-live -> exit move belongs to the forward track. Trades opened on or after
    go-live keep their real entry price."""
    import pandas as pd

    gl_day = golive_ts[:10]
    gl_ts = pd.Timestamp(gl_day)
    rows = conn.execute(
        "SELECT ticker, qty, entry_px, exit_px, entry_ts FROM trades "
        "WHERE fund=? AND source='live' AND exit_ts IS NOT NULL", (fund,)).fetchall()
    marks: dict[str, float] = {}   # ticker -> go-live close (cached)
    total = 0.0
    for ticker, qty, entry_px, exit_px, entry_ts in rows:
        if entry_ts and entry_ts[:10] < gl_day:        # carried from the backtest
            if ticker not in marks:
                df = store.load_prices(ticker)
                if df is not None and not df.empty:
                    sub = df.loc[df.index <= gl_ts, "close"]
                    if len(sub):
                        marks[ticker] = float(sub.iloc[-1])
            basis = marks.get(ticker, entry_px)         # fall back to raw if no mark
        else:
            basis = entry_px
        total += (exit_px - basis) * qty
    return total


def build_state(cfg: Config) -> dict:
    conn = get_conn(cfg.db_path)
    store = SnapshotStore(cfg.snapshot_dir)
    state: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # ---- funds: headline + curves vs benchmark ----
    funds = {}
    for fund in ("equity", "biotech", "biotech_smallcap"):
        snaps = _rows(conn, "SELECT ts, equity, gross_exposure, drawdown, source "
                            "FROM equity_snapshots WHERE fund=? ORDER BY ts", (fund,))
        if not snaps:
            continue
        curve = [[s["ts"], round(s["equity"], 2)] for s in snaps][-500:]
        first, last = snaps[0], snaps[-1]
        bench_t = BENCHMARKS[fund]
        bench_curve = []
        px = store.load_prices(bench_t)
        if px is not None:
            import pandas as pd
            start = pd.to_datetime(first["ts"], format="ISO8601", utc=True).tz_localize(None)
            window = px.loc[px.index >= start, "close"]
            if len(window):
                scale = first["equity"] / window.iloc[0]
                bench_curve = [[str(d.date()), round(v * scale, 2)]
                               for d, v in window.items()][-500:]
        mode_row = conn.execute("SELECT mode FROM fund_state WHERE fund=?", (fund,)).fetchone()
        live = [s for s in snaps if s["source"] == "live"]
        # Fixed-budget forward book: the live paper trade expressed from the
        # fund's STARTING budget, not the replay-inflated NAV. Positions size as
        # a % of equity, so the live returns are identical whether the book sits
        # at $1M or replay's $2.2M — rebasing to the starting budget shows honest
        # dollars and drops the deceptive hindsight NAV from the headline.
        acct = conn.execute("SELECT starting_cash FROM accounts WHERE fund=?",
                             (fund,)).fetchone()
        start_budget = (acct["starting_cash"] if acct and acct["starting_cash"]
                        else cfg.starting_cash)
        fwd_value = start_budget
        fwd_curve, fwd_bench_curve, fwd_bench_ret = [], [], None
        if live:
            import pandas as pd
            base = live[0]["equity"]
            fwd_value = start_budget * (live[-1]["equity"] / base)
            fwd_curve = [[s["ts"], round(start_budget * s["equity"] / base, 2)]
                         for s in live]
            if px is not None:
                gl = pd.to_datetime(live[0]["ts"], format="ISO8601", utc=True).tz_localize(None)
                w = px.loc[px.index >= gl, "close"]
                if len(w):
                    bscale = start_budget / w.iloc[0]
                    fwd_bench_curve = [[str(d.date()), round(v * bscale, 2)]
                                       for d, v in w.items()]
                    fwd_bench_ret = (w.iloc[-1] / w.iloc[0] - 1) * 100
        _scale = (start_budget / live[0]["equity"]) if live else (start_budget / last["equity"])
        # realized = banked P&L from CLOSED live round-trips (can't reverse);
        # unrealized (filled in the positions pass) = paper mark on OPEN positions.
        # Carried-in positions are re-based to their go-live close so the realized
        # line counts only what was earned after the forward clock started, not
        # backtest appreciation that merely got booked during the live window.
        realized_live = (_forward_realized(conn, store, fund, live[0]["ts"])
                         if live else 0.0)
        funds[fund] = {
            "equity": last["equity"],
            "ret_pct": (last["equity"] / first["equity"] - 1) * 100,
            "start_budget": start_budget,
            "fwd_value": fwd_value,
            # constant factor to express any current dollar (NAV, positions) on
            # the fixed starting budget: start_budget / equity-at-go-live
            "fwd_scale": _scale,
            "realized_fwd": realized_live * _scale,   # banked, on the fixed budget
            "unrealized_fwd": 0.0,                     # set in the positions pass
            "fwd_ret_pct": ((live[-1]["equity"] / live[0]["equity"] - 1) * 100
                            if len(live) >= 1 else None),
            "fwd_since": live[0]["ts"][:10] if live else None,
            "fwd_sessions": len(live),
            "fwd_curve": fwd_curve,
            "fwd_bench_curve": fwd_bench_curve,
            "fwd_bench_ret_pct": fwd_bench_ret,
            "bench": bench_t,
            "bench_ret_pct": ((bench_curve[-1][1] / first["equity"] - 1) * 100) if bench_curve else None,
            "gross": last["gross_exposure"] * 100,
            "drawdown": last["drawdown"] * 100,
            "mode": mode_row["mode"] if mode_row else "normal",
            "curve": curve,
            "bench_curve": bench_curve,
        }
    state["funds"] = funds

    # ---- the loop: live counters ----
    g = lambda sql, p=(): (conn.execute(sql, p).fetchone() or [0])[0]
    state["loop"] = {
        "iterations": g("SELECT COUNT(*) FROM research_iterations"),
        "evaluated": g("SELECT COUNT(*) FROM strategies"),
        "promoted": g("SELECT COUNT(*) FROM strategies WHERE status='promoted'"),
        "retired": g("SELECT COUNT(*) FROM strategies WHERE status='retired'"),
        "open_positions": g("SELECT COUNT(*) FROM positions"),
        "closed_trades": g("SELECT COUNT(*) FROM trades WHERE exit_ts IS NOT NULL"),
        "journal_entries": g("SELECT COUNT(*) FROM journal_entries"),
        "learning_reviews": g("SELECT COUNT(*) FROM journal_entries WHERE entry_type='learning'"),
        # "last cycle" = when the loop last DID something (advances every cycle,
        # ~30 min), distinct from the last EOD mark. equity snapshots only move
        # when a new daily close arrives, so they lag intraday — reporting them
        # as "last cycle" made a live system look stalled between closes.
        "last_cycle": g("SELECT MAX(ts) FROM journal_entries"),
        "last_close_marked": g("SELECT MAX(last_session_price_date) FROM fund_state"),
        "av_calls_today": g("SELECT calls_used FROM api_budget WHERE source='alphavantage' "
                            "ORDER BY date DESC LIMIT 1"),
        "best_oos_sharpe": g("SELECT MAX(oos_sharpe) FROM research_iterations"),
    }

    # ---- volatility regime (observe-only): VIX term-structure read ----
    from .data.regime import vol_regime
    state["regime"] = vol_regime(store)

    # ---- strategies: ALL promoted edges, then best candidates ----
    # backtest claim (oos/dsr/alpha) PLUS the live forward record per edge — the
    # closed live-trade count (maturity), realized live P&L (delivered), and live
    # hit rate. source='live' excludes the replay/hindsight era, so this is the
    # honest "promised vs delivered" the backtest ranking can't settle.
    strats = _rows(conn, """
        SELECT s.id, s.desk, s.family, s.status, s.origin,
               MAX(i.oos_sharpe) sharpe, MAX(i.oos_alpha) alpha,
               MAX(i.dsr_prob) dsr, MAX(i.bootstrap_q05) boot,
               (SELECT COUNT(*) FROM trades t WHERE t.strategy_id=s.id
                  AND t.source='live' AND t.exit_ts IS NOT NULL) live_closed,
               (SELECT ROUND(SUM(t.pnl),0) FROM trades t WHERE t.strategy_id=s.id
                  AND t.source='live' AND t.exit_ts IS NOT NULL) live_pnl,
               (SELECT ROUND(AVG(CASE WHEN t.pnl>0 THEN 1.0 ELSE 0.0 END),2)
                  FROM trades t WHERE t.strategy_id=s.id
                  AND t.source='live' AND t.exit_ts IS NOT NULL) live_hit
        FROM strategies s JOIN research_iterations i ON i.strategy_id = s.id
        WHERE i.oos_sharpe IS NOT NULL
        GROUP BY s.id
        ORDER BY (s.status='promoted') DESC, sharpe DESC LIMIT 60""")
    promoted = [r for r in strats if r["status"] == "promoted"]
    others = [r for r in strats if r["status"] != "promoted"]
    state["strategies"] = promoted + others[:4]

    # ---- biotech bench: the contaminated-discovery gate, watchable ----
    from .config import PROMOTION_THRESHOLDS, PROMOTION_THRESHOLDS_EXTERNAL
    ext_fams = ("event_anchored", "options_iv_runup", "insider_conviction")
    ph = ",".join("?" * len(ext_fams))
    trend = _rows(conn, f"""
        SELECT date(i.ts) d, ROUND(MAX(i.dsr_prob), 3) dsr
        FROM research_iterations i JOIN strategies st ON st.id = i.strategy_id
        WHERE i.desk='biotech' AND st.family IN ({ph}) AND i.dsr_prob IS NOT NULL
        GROUP BY date(i.ts) ORDER BY d""", ext_fams)
    agg = conn.execute(f"""
        SELECT COUNT(*) n, MAX(i.oos_sharpe) best_oos,
               SUM(CASE WHEN i.fail_reasons LIKE 'dsr_prob%' AND
                        i.fail_reasons NOT LIKE '%;%' AND i.dsr_prob >= ?
                   THEN 1 ELSE 0 END) held_out,
               SUM(i.promoted) promoted
        FROM research_iterations i JOIN strategies st ON st.id = i.strategy_id
        WHERE i.desk='biotech' AND st.family IN ({ph})""",
        (PROMOTION_THRESHOLDS["biotech"].min_dsr_prob, *ext_fams)).fetchone()
    state["bench"] = {
        "trend": [[r["d"], r["dsr"]] for r in trend],
        "strict": PROMOTION_THRESHOLDS_EXTERNAL.min_dsr_prob,
        "standard": PROMOTION_THRESHOLDS["biotech"].min_dsr_prob,
        "candidates": agg["n"], "best_oos": agg["best_oos"],
        "held_out": agg["held_out"], "promoted": agg["promoted"],
    }

    # ---- shadow book: pre-registered forward trials ----
    shadow_rows = _rows(conn, """
        SELECT sb.id, sb.fund, sb.registered_ts, sb.expected_oos_sharpe,
               sb.expected_dsr, sb.status, sb.note, s.family, s.params_json
        FROM shadow_book sb JOIN strategies s ON s.id = sb.strategy_id
        ORDER BY sb.status='active' DESC, sb.id""")
    shadows = []
    for r in shadow_rows:
        navs = _rows(conn, "SELECT ts, nav FROM shadow_nav WHERE shadow_id=? "
                           "ORDER BY ts", (r["id"],))
        fwd = (navs[-1]["nav"] - 1) * 100 if navs else None
        sharpe = None
        if len(navs) >= 10:
            import numpy as np
            nv = np.array([n["nav"] for n in navs])
            rets = nv[1:] / nv[:-1] - 1
            if rets.std() > 0:
                sharpe = float(rets.mean() / rets.std() * 252 ** 0.5)
        try:
            sig = json.loads(r["params_json"]).get("rank_signal", "")
        except Exception:
            sig = ""
        shadows.append({
            "id": r["id"], "family": r["family"], "signal": sig,
            "registered": r["registered_ts"][:10], "status": r["status"],
            "claim_sharpe": r["expected_oos_sharpe"], "claim_dsr": r["expected_dsr"],
            "fwd_ret_pct": fwd, "fwd_sharpe": sharpe, "marks": len(navs),
            "note": (r["note"] or "")[:120],
        })
    state["shadows"] = shadows[:12]

    # ---- positions with entry context and live P&L ----
    positions = {}
    for fund in ("equity", "biotech", "biotech_smallcap"):
        rows = _rows(conn, "SELECT ticker, qty, avg_cost, opened_ts FROM positions "
                           "WHERE fund=?", (fund,))
        fd = funds.get(fund, {})
        eq = fd.get("equity") or 1
        scale = fd.get("fwd_scale", 1.0)   # rebase $ onto the fixed budget
        out = []
        for r in rows:
            px = store.load_prices(r["ticker"])
            last_px = float(px["close"].iloc[-1]) if px is not None and len(px) else r["avg_cost"]
            out.append({
                "ticker": r["ticker"],
                "entry_date": (r["opened_ts"] or "")[:10],
                "entry_px": r["avg_cost"],
                "px": last_px,
                "cost": r["qty"] * r["avg_cost"] * scale,
                "value": r["qty"] * last_px * scale,
                "weight": r["qty"] * last_px / eq * 100,
                "pnl": (last_px - r["avg_cost"]) * r["qty"] * scale,
                "pnl_pct": (last_px / r["avg_cost"] - 1) * 100 if r["avg_cost"] else 0,
            })
        if fund in funds:   # total unrealized = mark-over-cost across ALL open names
            funds[fund]["unrealized_fwd"] = sum(o["pnl"] for o in out)
        out.sort(key=lambda x: -x["weight"])
        positions[fund] = out[:20]
    state["positions"] = positions

    # ---- catalyst sleeve: event-driven per-event book (runs in tandem) ----
    cat: dict = {}
    acct = conn.execute("SELECT cash, starting_cash FROM accounts "
                        "WHERE fund='biotech_catalyst'").fetchone()
    if acct:
        start = acct["starting_cash"] or cfg.starting_cash
        live = _rows(conn, "SELECT equity FROM equity_snapshots "
                           "WHERE fund='biotech_catalyst' AND source='live' ORDER BY id")
        value, fwd_ret, scale = start, None, 1.0
        if live:
            base = live[0]["equity"] or start
            value = start * live[-1]["equity"] / base
            fwd_ret = (live[-1]["equity"] / base - 1) * 100
            scale = start / base
        def _q(t):
            df = store.load_prices(t)
            return float(df["close"].iloc[-1]) if df is not None and len(df) else None
        opens = []
        for r in _rows(conn, "SELECT ticker, catalyst_type, catalyst_date, entry_ts, "
                             "entry_px, qty, runup_180d FROM catalyst_sleeve "
                             "WHERE fund='biotech_catalyst' ORDER BY catalyst_date"):
            px = _q(r["ticker"]) or r["entry_px"]
            opens.append({"ticker": r["ticker"], "ctype": r["catalyst_type"] or "",
                          "catalyst_date": r["catalyst_date"],
                          "entry_date": (r["entry_ts"] or "")[:10],
                          "entry_px": r["entry_px"], "now_px": px,
                          "pnl_pct": (px / r["entry_px"] - 1) * 100 if r["entry_px"] else 0,
                          "alloc": r["qty"] * r["entry_px"] * scale,
                          "value": r["qty"] * px * scale,
                          "runup": (r["runup_180d"] or 0) * 100})
        cl = conn.execute("SELECT COUNT(*) n, AVG(CASE WHEN pnl_pct>0 THEN 1.0 ELSE 0 END) "
                          "hit, SUM(pnl) pnl FROM trades WHERE fund='biotech_catalyst' "
                          "AND exit_ts IS NOT NULL AND source='live'").fetchone()
        cat = {"value": value, "fwd_ret": fwd_ret, "start": start, "open": opens,
               "n_open": len(opens), "closed_n": cl["n"] or 0, "hit": cl["hit"],
               "pnl": (cl["pnl"] or 0) * scale}
    state["catalyst"] = cat

    # ---- research lab: recent iterations for the animated search space ----
    state["research_feed"] = _rows(conn, """
        SELECT i.ts, i.desk, s.family, s.params_json, i.oos_sharpe, i.is_sharpe,
               i.max_dd, i.fitness, i.promoted, i.dsr_prob, i.bootstrap_q05,
               substr(i.fail_reasons,1,60) fail
        FROM research_iterations i LEFT JOIN strategies s ON s.id = i.strategy_id
        ORDER BY i.id DESC LIMIT 150""")

    # ---- decision feed ----
    state["journal"] = _rows(conn, """
        SELECT ts, fund, entry_type, ticker, substr(reasoning, 1, 160) reasoning
        FROM journal_entries ORDER BY id DESC LIMIT 30""")

    # ---- upcoming catalysts ----
    cats = store.load_json("bpiq/catalysts.json") or []
    today = time.strftime("%Y-%m-%d")
    upcoming = [
        {"ticker": c.get("ticker"), "date": c.get("catalyst_date"),
         "label": ((c.get("stage_event") or {}).get("label") or "")[:40],
         "big": bool(c.get("is_big_mover"))}
        for c in cats
        if c.get("catalyst_date") and c["catalyst_date"] >= today and c.get("ticker")
    ]
    upcoming.sort(key=lambda c: c["date"])
    state["catalysts"] = upcoming[:14]

    conn.close()
    return state


class Handler(BaseHTTPRequestHandler):
    cfg: Config = None

    def log_message(self, *args):  # quiet
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path.startswith("/api/state"):
                body = json.dumps(build_state(self.cfg), default=str).encode()
                self._send(body, "application/json")
            elif self.path.startswith("/vendor/"):
                name = Path(self.path).name
                vendor = HTML_PATH.parent / "vendor" / name
                if vendor.suffix == ".js" and vendor.is_file() \
                        and vendor.parent == HTML_PATH.parent / "vendor":
                    self._send(vendor.read_bytes(), "application/javascript")
                else:
                    self.send_response(404)
                    self.end_headers()
            else:
                self._send(HTML_PATH.read_bytes(), "text/html; charset=utf-8")
        except BrokenPipeError:
            pass
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())


def _auto_sync_loop(cfg: Config, interval_s: int):
    """Pull the repo and adopt a newer committed seed, forever.

    Freshness is keyed to the git HEAD moving (new cycle commits), NOT to seed
    vs read-DB mtimes: the cockpit OPENS the read-DB (WAL touches it), which used
    to bump its mtime newer than the seed and silently wedge the sync on a stale
    copy. Adopt once on startup, then re-adopt whenever HEAD advances."""
    seed = PROJECT_ROOT / "data" / "seed.db"

    def _head() -> str:
        r = subprocess.run(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        return r.stdout.strip()

    def _adopt() -> None:
        if seed.exists():
            tmp = cfg.db_path.with_suffix(".db.incoming")
            shutil.copy(seed, tmp)
            os.replace(tmp, cfg.db_path)

    try:
        _adopt()                       # a freshly-started cockpit is current at once
    except Exception:
        pass
    last_head = _head()
    while True:
        time.sleep(interval_s)
        try:
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            subprocess.run(["git", "-C", str(PROJECT_ROOT), "pull", "--ff-only", "-q"],
                           timeout=120, capture_output=True, env=env)
            head = _head()
            if head != last_head:      # new commits pulled -> adopt the fresh seed
                _adopt()
                last_head = head
        except Exception:
            continue  # transient network/git issues: try again next round


def serve(cfg: Config, port: int = 8600, auto_sync_s: int = 0) -> None:
    Handler.cfg = cfg
    if auto_sync_s > 0:
        threading.Thread(target=_auto_sync_loop, args=(cfg, auto_sync_s),
                         daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    sync_msg = f", auto-syncing from GitHub every {auto_sync_s}s" if auto_sync_s else ""
    print(f"Quantzzz cockpit -> http://localhost:{port}{sync_msg}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ncockpit stopped.")
