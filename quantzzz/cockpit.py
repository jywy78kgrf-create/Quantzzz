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


def build_state(cfg: Config) -> dict:
    conn = get_conn(cfg.db_path)
    store = SnapshotStore(cfg.snapshot_dir)
    state: dict = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # ---- funds: headline + curves vs benchmark ----
    funds = {}
    for fund in ("equity", "biotech"):
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
        funds[fund] = {
            "equity": last["equity"],
            "ret_pct": (last["equity"] / first["equity"] - 1) * 100,
            "fwd_ret_pct": ((live[-1]["equity"] / live[0]["equity"] - 1) * 100
                            if len(live) >= 1 else None),
            "fwd_since": live[0]["ts"][:10] if live else None,
            "fwd_sessions": len(live),
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
        "last_cycle": g("SELECT MAX(ts) FROM equity_snapshots"),
        "av_calls_today": g("SELECT calls_used FROM api_budget WHERE source='alphavantage' "
                            "ORDER BY date DESC LIMIT 1"),
        "best_oos_sharpe": g("SELECT MAX(oos_sharpe) FROM research_iterations"),
    }

    # ---- strategies: promoted first, then best candidates ----
    state["strategies"] = _rows(conn, """
        SELECT s.desk, s.family, s.status, s.origin,
               MAX(i.oos_sharpe) sharpe, MAX(i.oos_alpha) alpha,
               MAX(i.dsr_prob) dsr, MAX(i.bootstrap_q05) boot
        FROM strategies s JOIN research_iterations i ON i.strategy_id = s.id
        WHERE i.oos_sharpe IS NOT NULL
        GROUP BY s.id
        ORDER BY (s.status='promoted') DESC, sharpe DESC LIMIT 10""")

    # ---- positions with entry context and live P&L ----
    positions = {}
    for fund in ("equity", "biotech"):
        rows = _rows(conn, "SELECT ticker, qty, avg_cost, opened_ts FROM positions "
                           "WHERE fund=?", (fund,))
        eq = funds.get(fund, {}).get("equity") or 1
        out = []
        for r in rows:
            px = store.load_prices(r["ticker"])
            last_px = float(px["close"].iloc[-1]) if px is not None and len(px) else r["avg_cost"]
            out.append({
                "ticker": r["ticker"],
                "entry_date": (r["opened_ts"] or "")[:10],
                "entry_px": r["avg_cost"],
                "px": last_px,
                "value": r["qty"] * last_px,
                "weight": r["qty"] * last_px / eq * 100,
                "pnl": (last_px - r["avg_cost"]) * r["qty"],
                "pnl_pct": (last_px / r["avg_cost"] - 1) * 100 if r["avg_cost"] else 0,
            })
        out.sort(key=lambda x: -x["weight"])
        positions[fund] = out[:12]
    state["positions"] = positions

    # ---- research lab: recent iterations for the animated search space ----
    state["research_feed"] = _rows(conn, """
        SELECT i.ts, i.desk, s.family, s.params_json, i.oos_sharpe, i.is_sharpe,
               i.max_dd, i.fitness, i.promoted, substr(i.fail_reasons,1,60) fail
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
    """Pull the repo and adopt a newer committed seed, forever."""
    seed = PROJECT_ROOT / "data" / "seed.db"
    while True:
        time.sleep(interval_s)
        try:
            subprocess.run(["git", "-C", str(PROJECT_ROOT), "pull", "--ff-only", "-q"],
                           timeout=120, capture_output=True)
            if seed.exists() and (not cfg.db_path.exists()
                                  or seed.stat().st_mtime > cfg.db_path.stat().st_mtime):
                tmp = cfg.db_path.with_suffix(".db.incoming")
                shutil.copy(seed, tmp)
                os.replace(tmp, cfg.db_path)
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
