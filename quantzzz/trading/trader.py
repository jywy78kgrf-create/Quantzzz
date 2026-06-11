"""TraderAgent: weight-tracking execution of promoted strategies.

The trader rebalances toward the combined target weights of its fund's
promoted strategies — making live execution mathematically consistent with how
the strategies were validated. Intelligence and safety sit as overlays on the
targets: drawdown halts, vol-aware disaster stops with re-entry cooldown,
pre-earnings blackouts, the biotech catalyst EV gate, Monte Carlo halt-risk
throttling, single-name/gross caps, and learned per-strategy weight
multipliers. Every adjustment is journaled.
"""

from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

from ..config import Config
from ..db import get_conn, insert, utcnow
from ..data.snapshots import SnapshotStore
from ..research.strategies import signal_fn_for
from ..research.strategy_space import StrategySpec
from .broker import Order, make_broker
from .journal import DecisionJournal
from .learning import LearningLoop
from .risk import RiskManager


class TraderAgent:
    def __init__(self, cfg: Config, fund: str, conn: sqlite3.Connection):
        self.cfg = cfg
        self.fund = fund
        self.conn = conn
        self.store = SnapshotStore(cfg.snapshot_dir)
        self.limits = cfg.risk_limits(fund)
        self.risk = RiskManager(self.limits)
        self.journal = DecisionJournal(conn, fund)
        from ..llm import get_llm
        self.llm = get_llm(cfg)
        self.learning = LearningLoop(cfg, fund, conn, self.journal, self.llm)
        self.as_of = None                       # set during historical replay
        self._all_prices = self._load_price_frames()
        self._price_cache = self._closes_as_of(None)
        self._bundle = self._load_bundle()      # built once, sliced per session
        self._earnings_dates = self._load_earnings_calendar()
        self.broker = make_broker(cfg, fund, conn, self._quote)

    @classmethod
    def build(cls, cfg: Config, fund: str) -> "TraderAgent":
        return cls(cfg, fund, get_conn(cfg.db_path))

    def _load_bundle(self):
        from ..research.feature_loader import load_feature_bundle
        from ..universe import universe_for
        tickers = universe_for(self.fund, self.cfg.snapshot_dir)
        return load_feature_bundle(self.cfg, self.fund, tickers, self.store, self.conn)

    # ---- quotes / time ----
    def _load_price_frames(self) -> dict:
        frames = {}
        for t in self.store.available_tickers():
            df = self.store.load_prices(t)
            if df is not None and len(df):
                frames[t] = df["close"]
        return frames

    def _closes_as_of(self, as_of) -> dict[str, float]:
        cache = {}
        for t, series in self._all_prices.items():
            s = series if as_of is None else series[series.index <= as_of]
            if len(s):
                cache[t] = float(s.iloc[-1])
        return cache

    def _quote(self, ticker: str) -> float | None:
        return self._price_cache.get(ticker)

    def _ts(self) -> str:
        if self.as_of is not None:
            return pd.Timestamp(self.as_of).isoformat()
        return utcnow()

    def _ticker_vol(self, ticker: str) -> float:
        series = self._all_prices.get(ticker)
        if series is None or len(series) < 30:
            return 0.4
        end = pd.Timestamp(self.as_of) if self.as_of is not None else None
        s = series if end is None else series[series.index <= end]
        vol = s.pct_change().tail(60).std() * np.sqrt(252)
        return float(vol) if vol and vol > 0 else 0.4

    # ---- calendars / gates ----
    def _load_earnings_calendar(self) -> dict[str, list[pd.Timestamp]]:
        cal = self.store.load_json("av_earnings_calendar.json") or []
        out: dict[str, list[pd.Timestamp]] = {}
        for row in cal:
            try:
                out.setdefault(row["ticker"], []).append(pd.Timestamp(row["reportDate"]))
            except (KeyError, ValueError):
                continue
        return out

    def _in_earnings_blackout(self, ticker: str) -> pd.Timestamp | None:
        now = pd.Timestamp(self.as_of) if self.as_of is not None else pd.Timestamp.today()
        for d in self._earnings_dates.get(ticker, []):
            days = (d - now.normalize()).days
            if 0 <= days <= self.cfg.pre_earnings_blackout_days:
                return d
        return None

    def _stop_out_cooldown_tickers(self, cooldown_days: int = 14) -> set[str]:
        cutoff = (pd.Timestamp(self._ts()) - pd.Timedelta(days=cooldown_days)).isoformat()
        rows = self.conn.execute(
            "SELECT DISTINCT ticker FROM trades WHERE fund=? AND exit_reason LIKE 'stop hit%' "
            "AND exit_ts >= ?", (self.fund, cutoff)).fetchall()
        return {r["ticker"] for r in rows}

    def _days_to_next_catalyst(self, ticker: str) -> int | None:
        now = pd.Timestamp(self.as_of) if self.as_of is not None else pd.Timestamp.today()
        best = None
        for c in (self._bundle.catalysts or []):
            if c.get("ticker") != ticker or not c.get("catalyst_date"):
                continue
            try:
                days = (pd.Timestamp(c["catalyst_date"]) - now.normalize()).days
            except (ValueError, TypeError):
                continue
            if days >= 0 and (best is None or days < best):
                best = days
        return best

    def _catalyst_ev_blocked(self, ticker: str) -> dict | None:
        """Block only when about to hold INTO a near catalyst with a negative
        empirical EV profile. Strategies that exit before events are untouched."""
        if self.fund != "biotech":
            return None
        days = self._days_to_next_catalyst(ticker)
        if days is None or days > self.cfg.catalyst_gate_days:
            return None
        from ..research.montecarlo import catalyst_scenario_stats
        hist = (self._bundle.hist_catalysts or {}).get(ticker, [])
        moves = [float(v) for r in hist
                 if (v := r.get("open_price_gap_percent")) is not None]
        if len(moves) < self.cfg.min_catalyst_events:
            return None     # thin history: pooled EV is positive, allow
        stats = catalyst_scenario_stats(moves, kelly_cap=self.limits.kelly_cap)
        if stats and stats["ev"] <= 0:
            return {**stats, "days_to_catalyst": days}
        return None

    # ---- target construction ----
    def _combined_targets(self) -> dict[str, float]:
        """Equal-capital blend of promoted strategies' latest target weights,
        scaled by learned per-strategy multipliers."""
        rows = self.conn.execute(
            "SELECT id, family, params_json FROM strategies "
            "WHERE desk=? AND status='promoted'", (self.fund,)).fetchall()
        bundle = self._bundle
        if self.as_of is not None:
            dates = bundle.prices.index[bundle.prices.index <= self.as_of]
            if len(dates) < 2:
                return {}
            bundle = bundle.slice(dates)

        strat_weights: list[tuple[int, pd.Series, float]] = []
        for r in rows:
            if not self.learning.is_active(r["id"]):
                continue
            try:
                spec = StrategySpec.from_row(r["family"], self.fund, r["params_json"])
                w = signal_fn_for(spec.family)(bundle, spec.params)
            except Exception:
                continue
            if w.empty:
                continue
            mult = self.learning.current_multiplier(r["id"])
            strat_weights.append((r["id"], w.iloc[-1], mult))
        if not strat_weights:
            return {}

        n = len(strat_weights)
        combined: dict[str, float] = {}
        contributors: dict[str, list[int]] = {}
        for sid, latest, mult in strat_weights:
            for ticker, w in latest.items():
                if w > 1e-6:
                    combined[ticker] = combined.get(ticker, 0.0) + (w * mult) / n
                    contributors.setdefault(ticker, []).append(sid)
        self._contributors = contributors
        # respect the gross exposure cap
        gross = sum(combined.values())
        cap = self.limits.max_gross_exposure
        if gross > cap:
            combined = {t: w * cap / gross for t, w in combined.items()}
        return combined

    def _apply_overlays(self, targets: dict[str, float],
                        current: dict[str, float], mc_throttle: float) -> dict[str, float]:
        out: dict[str, float] = {}
        cooled = self._stop_out_cooldown_tickers()
        for ticker, w in targets.items():
            cur = current.get(ticker, 0.0)
            if self._quote(ticker) is None:
                continue
            increasing = w > cur + 1e-9
            if increasing and ticker in cooled:
                out[ticker] = cur        # hold, don't add after a stop-out
                continue
            if increasing:
                report = self._in_earnings_blackout(ticker)
                if report is not None:
                    self.journal.record(
                        "skip", ticker=ticker, action="hold",
                        reasoning=(f"Not adding {ticker}: earnings on "
                                   f"{report.date()} inside blackout."),
                        inputs={"target_w": w, "current_w": cur})
                    out[ticker] = cur
                    continue
                blocked = self._catalyst_ev_blocked(ticker)
                if blocked is not None:
                    self.journal.record(
                        "skip", ticker=ticker, action="exit_before_event",
                        reasoning=(f"Zeroing {ticker}: catalyst in "
                                   f"{blocked['days_to_catalyst']}d with negative "
                                   f"empirical EV {blocked['ev']:+.2%} over "
                                   f"{blocked['n_events']} events "
                                   f"(q05 {blocked['downside_q05']:+.1%})."),
                        inputs=blocked)
                    out[ticker] = 0.0
                    continue
                # throttle only the increase, not the holding
                w = cur + (w - cur) * mc_throttle
            out[ticker] = min(w, self.limits.max_position_pct)
        # names we hold but targets dropped entirely
        for ticker, cur in current.items():
            if ticker not in out and ticker not in targets:
                out[ticker] = 0.0
        return out

    # ---- session ----
    def session(self, as_of=None) -> str:
        self.as_of = as_of
        if as_of is not None:
            self._price_cache = self._closes_as_of(as_of)
        self.broker.mark_to_market(self._price_cache, ts=self._ts())
        drawdown = self._current_drawdown()
        state = self._fund_mode()

        if self.risk.drawdown_halted(drawdown) and state != "liquidate_only":
            self._set_mode("liquidate_only")
            self.journal.record("halt", reasoning=(
                f"Drawdown {drawdown:.1%} breached halt "
                f"{-self.limits.drawdown_halt_pct:.0%}; entering liquidate-only."))
            state = "liquidate_only"
        elif state == "liquidate_only" and drawdown > -self.limits.drawdown_halt_pct * 0.5:
            self._set_mode("normal")            # recovered halfway back: resume
            self.journal.record("halt", reasoning=(
                f"Drawdown recovered to {drawdown:.1%}; resuming normal mode."))
            state = "normal"

        stops = self._process_stops()

        acct = self.broker.get_account()
        current = self._current_weights(acct.equity)
        targets = {} if state == "liquidate_only" else self._combined_targets()
        mc_throttle = self._compute_mc_throttle()
        targets = self._apply_overlays(targets, current, mc_throttle)
        n_trades = self._rebalance(targets, current, acct.equity)

        reviewed = 0
        if self.learning.unreviewed_count() >= self.cfg.learning_review_every:
            reviewed = self.learning.review()

        self.broker.mark_to_market(self._price_cache, ts=self._ts())
        acct = self.broker.get_account()
        return (f"[{self.fund}] equity ${acct.equity:,.0f} cash ${acct.cash:,.0f} | "
                f"stops {stops}, rebalance trades {n_trades}, positions "
                f"{len(self.broker.get_positions())}, reviewed {reviewed}, mode {state}")

    # ---- stops (disaster brake; cooldown prevents instant re-entry) ----
    def _process_stops(self) -> int:
        count = 0
        for pos in self.broker.get_positions():
            row = self.conn.execute(
                "SELECT stop_px, avg_cost, strategy_id FROM positions WHERE fund=? AND ticker=?",
                (self.fund, pos.ticker)).fetchone()
            px = self._quote(pos.ticker) or pos.avg_cost
            if row["stop_px"] and px <= row["stop_px"]:
                self._close_position(pos.ticker, row["strategy_id"],
                                     f"stop hit ({px:.2f} <= {row['stop_px']:.2f})")
                count += 1
        return count

    def _close_position(self, ticker: str, strategy_id, reason: str) -> None:
        pos = self.conn.execute(
            "SELECT qty, avg_cost FROM positions WHERE fund=? AND ticker=?",
            (self.fund, ticker)).fetchone()
        if pos is None:
            return
        jid = self.journal.record("exit", ticker=ticker, action="sell",
                                  reasoning=f"Closing {ticker}: {reason}.",
                                  inputs={"reason": reason})
        fill = self.broker.submit_order(Order(self.fund, ticker, "sell", pos["qty"],
                                              strategy_id=strategy_id, journal_id=jid))
        if fill:
            pnl = (fill.price - pos["avg_cost"]) * pos["qty"]
            pnl_pct = (fill.price / pos["avg_cost"] - 1) if pos["avg_cost"] else 0.0
            self._record_trade_exit(ticker, fill.price, pnl, pnl_pct, reason)

    # ---- rebalancing ----
    def _current_weights(self, equity: float) -> dict[str, float]:
        if equity <= 0:
            return {}
        out = {}
        for p in self.broker.get_positions():
            px = self._quote(p.ticker) or p.avg_cost
            out[p.ticker] = p.qty * px / equity
        return out

    def _rebalance(self, targets: dict[str, float], current: dict[str, float],
                   equity: float) -> int:
        deltas = []
        for ticker in set(targets) | set(current):
            d = targets.get(ticker, 0.0) - current.get(ticker, 0.0)
            if abs(d) >= self.cfg.min_rebalance_weight:
                deltas.append((ticker, d))
        # sells first to free cash
        deltas.sort(key=lambda x: x[1])
        n = 0
        for ticker, d in deltas:
            px = self._quote(ticker)
            if px is None or px <= 0:
                continue
            qty = float(int(abs(d) * equity / px))
            if qty < 1:
                continue
            sid = (self._contributors.get(ticker) or [None])[0] \
                if hasattr(self, "_contributors") else None
            if d < 0:
                held = self.conn.execute(
                    "SELECT qty, avg_cost, strategy_id FROM positions WHERE fund=? AND ticker=?",
                    (self.fund, ticker)).fetchone()
                if held is None:
                    continue
                qty = min(qty, held["qty"])
                full_close = targets.get(ticker, 0.0) < self.cfg.min_rebalance_weight
                if full_close:
                    qty = held["qty"]
                jid = self.journal.record(
                    "exit" if full_close else "resize", ticker=ticker, action="sell",
                    reasoning=(f"Rebalance {ticker}: weight "
                               f"{current.get(ticker, 0):.1%} -> {targets.get(ticker, 0):.1%} "
                               f"per strategy targets."),
                    inputs={"target_w": targets.get(ticker, 0), "current_w": current.get(ticker, 0)})
                fill = self.broker.submit_order(Order(self.fund, ticker, "sell", qty,
                                                      strategy_id=held["strategy_id"],
                                                      journal_id=jid))
                if fill:
                    n += 1
                    if full_close:
                        pnl = (fill.price - held["avg_cost"]) * qty
                        pnl_pct = (fill.price / held["avg_cost"] - 1) if held["avg_cost"] else 0.0
                        self._record_trade_exit(ticker, fill.price, pnl, pnl_pct,
                                                "rebalance: target weight zero")
            else:
                opening = ticker not in current or current.get(ticker, 0.0) == 0.0
                jid = self.journal.record(
                    "entry" if opening else "resize", ticker=ticker, action="buy",
                    reasoning=(f"Rebalance {ticker}: weight "
                               f"{current.get(ticker, 0):.1%} -> {targets[ticker]:.1%} "
                               f"(strategies {self._contributors.get(ticker, [])}, "
                               f"vol {self._ticker_vol(ticker):.0%})."),
                    inputs={"target_w": targets[ticker],
                            "current_w": current.get(ticker, 0)})
                fill = self.broker.submit_order(Order(self.fund, ticker, "buy", qty,
                                                      strategy_id=sid, journal_id=jid))
                if fill:
                    n += 1
                    if opening:
                        self.conn.execute(
                            "UPDATE positions SET stop_px=? WHERE fund=? AND ticker=?",
                            (self.risk.stop_price(fill.price, self._ticker_vol(ticker)),
                             self.fund, ticker))
                        insert(self.conn, "trades", fund=self.fund, strategy_id=sid,
                               ticker=ticker, entry_ts=self._ts(), entry_px=fill.price,
                               qty=qty)
                        self.conn.commit()
        return n

    # ---- risk / MC ----
    def _compute_mc_throttle(self) -> float:
        from ..research.montecarlo import drawdown_halt_probability
        positions = self.broker.get_positions()
        if not positions:
            return 1.0
        acct = self.broker.get_account()
        if acct.equity <= 0:
            return 1.0
        end = pd.Timestamp(self.as_of) if self.as_of is not None else None
        parts = []
        for p in positions:
            series = self._all_prices.get(p.ticker)
            if series is None:
                continue
            s = series if end is None else series[series.index <= end]
            w = (p.qty * (self._quote(p.ticker) or p.avg_cost)) / acct.equity
            parts.append(s.pct_change().tail(252) * w)
        if not parts:
            return 1.0
        port_rets = pd.concat(parts, axis=1).sum(axis=1, skipna=True).dropna()
        halt_p = drawdown_halt_probability(
            port_rets, halt_pct=self.limits.drawdown_halt_pct,
            horizon_days=self.cfg.mc_horizon_days)
        if halt_p is None or halt_p <= self.cfg.max_halt_probability:
            return 1.0
        throttle = max(0.25, self.cfg.max_halt_probability / halt_p)
        self.journal.record(
            "resize", action="mc_throttle",
            reasoning=(f"Monte Carlo: P(hit {self.limits.drawdown_halt_pct:.0%} halt "
                       f"within {self.cfg.mc_horizon_days}d) = {halt_p:.1%}; "
                       f"new exposure scaled to {throttle:.0%}."),
            inputs={"halt_probability": halt_p, "throttle": throttle})
        return throttle

    # ---- state helpers ----
    def _current_drawdown(self) -> float:
        row = self.conn.execute(
            "SELECT drawdown FROM equity_snapshots WHERE fund=? ORDER BY id DESC LIMIT 1",
            (self.fund,)).fetchone()
        return row["drawdown"] if row else 0.0

    def _fund_mode(self) -> str:
        row = self.conn.execute(
            "SELECT mode FROM fund_state WHERE fund=?", (self.fund,)).fetchone()
        return row["mode"] if row else "normal"

    def _set_mode(self, mode: str) -> None:
        self.conn.execute("UPDATE fund_state SET mode=?, halted_since=? WHERE fund=?",
                          (mode, utcnow(), self.fund))
        self.conn.commit()

    def _record_trade_exit(self, ticker, exit_px, pnl, pnl_pct, reason):
        row = self.conn.execute(
            "SELECT id FROM trades WHERE fund=? AND ticker=? AND exit_ts IS NULL "
            "ORDER BY id DESC LIMIT 1", (self.fund, ticker)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE trades SET exit_ts=?, exit_px=?, pnl=?, pnl_pct=?, exit_reason=? "
                "WHERE id=?", (self._ts(), exit_px, pnl, pnl_pct, reason, row["id"]))
            self.conn.commit()
