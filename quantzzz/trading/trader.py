"""TraderAgent: the per-fund decision loop.

Session order: mark-to-market & drawdown halt check -> process exits (stops,
retired strategies, exit signals) -> rank and enter new candidates with sizing
and risk checks -> run the learning loop when enough trades have closed. Every
decision is journaled.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from ..config import Config
from ..db import get_conn, insert, utcnow
from ..data.snapshots import SnapshotStore
from .broker import Order, make_broker
from .journal import DecisionJournal
from .learning import LearningLoop
from .risk import RiskManager
from .signals import generate_candidates
from . import sizing


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
        """Report date if the ticker reports within the blackout window."""
        now = pd.Timestamp(self.as_of) if self.as_of is not None else pd.Timestamp.today()
        for d in self._earnings_dates.get(ticker, []):
            days = (d - now.normalize()).days
            if 0 <= days <= self.cfg.pre_earnings_blackout_days:
                return d
        return None

    def _load_bundle(self):
        from ..research.feature_loader import load_feature_bundle
        from ..universe import universe_for
        tickers = universe_for(self.fund, self.cfg.snapshot_dir)
        return load_feature_bundle(self.cfg, self.fund, tickers, self.store, self.conn)

    @classmethod
    def build(cls, cfg: Config, fund: str) -> "TraderAgent":
        conn = get_conn(cfg.db_path)
        return cls(cfg, fund, conn)

    # ---- quotes (snapshot close as the paper price) ----
    def _load_price_frames(self) -> dict:
        frames = {}
        for t in self.store.available_tickers():
            df = self.store.load_prices(t)
            if df is not None and len(df):
                frames[t] = df["close"]
        return frames

    def _closes_as_of(self, as_of) -> dict[str, float]:
        """Latest close on or before as_of (or the very latest when as_of is None)."""
        cache = {}
        for t, series in self._all_prices.items():
            s = series if as_of is None else series[series.index <= as_of]
            if len(s):
                cache[t] = float(s.iloc[-1])
        return cache

    def _quote(self, ticker: str) -> float | None:
        return self._price_cache.get(ticker)

    def _ts(self) -> str:
        """Effective timestamp: the as-of date during replay, else wall clock."""
        if self.as_of is not None:
            return pd.Timestamp(self.as_of).isoformat()
        return utcnow()

    def _compute_mc_throttle(self) -> float:
        """Monte Carlo halt-risk sizing: bootstrap the current book's recent
        returns forward and shrink new entries if the probability of hitting
        the drawdown halt within the horizon is too high."""
        from ..research.montecarlo import drawdown_halt_probability

        positions = self.broker.get_positions()
        if not positions:
            return 1.0
        acct = self.broker.get_account()
        if acct.equity <= 0:
            return 1.0
        # weighted portfolio return series over the trailing year, as-of aware
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
                       f"within {self.cfg.mc_horizon_days}d) = {halt_p:.1%} > "
                       f"{self.cfg.max_halt_probability:.0%} target; new entries "
                       f"scaled to {throttle:.0%}."),
            inputs={"halt_probability": halt_p, "throttle": throttle,
                    "n_positions": len(positions)})
        return throttle

    def _ticker_vol(self, ticker: str) -> float:
        df = self.store.load_prices(ticker)
        if df is None or len(df) < 30:
            return 0.4
        vol = df["close"].pct_change().tail(60).std() * np.sqrt(252)
        return float(vol) if vol and vol > 0 else 0.4

    # ---- session ----
    def session(self, as_of=None) -> str:
        self.as_of = as_of
        if as_of is not None:
            self._price_cache = self._closes_as_of(as_of)
        quotes = self._price_cache
        self.broker.mark_to_market(quotes, ts=self._ts())
        drawdown = self._current_drawdown()
        state = self._fund_mode()

        if self.risk.drawdown_halted(drawdown) and state != "liquidate_only":
            self._set_mode("liquidate_only")
            self.journal.record("halt", reasoning=(
                f"Drawdown {drawdown:.1%} breached halt "
                f"{-self.limits.drawdown_halt_pct:.0%}; entering liquidate-only."))
            state = "liquidate_only"

        exits = self._process_exits()
        self._mc_throttle = self._compute_mc_throttle()
        entries = 0 if state == "liquidate_only" else self._process_entries()

        reviewed = 0
        if self.learning.unreviewed_count() >= self.cfg.learning_review_every:
            reviewed = self.learning.review()

        self.broker.mark_to_market(self._price_cache, ts=self._ts())
        acct = self.broker.get_account()
        return (f"[{self.fund}] equity ${acct.equity:,.0f} cash ${acct.cash:,.0f} | "
                f"exits {exits}, entries {entries}, positions "
                f"{len(self.broker.get_positions())}, reviewed {reviewed}, mode {state}")

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
        self.conn.execute(
            "UPDATE fund_state SET mode=?, halted_since=? WHERE fund=?",
            (mode, utcnow(), self.fund))
        self.conn.commit()

    # ---- exits ----
    def _process_exits(self) -> int:
        count = 0
        retired = {r["id"] for r in self.conn.execute(
            "SELECT id FROM strategies WHERE status='retired'").fetchall()}
        candidates = generate_candidates(self.cfg, self.fund, self.conn, self.store, self.as_of, self._bundle)
        exit_signals = {(c["strategy_id"], c["ticker"]) for c in candidates
                        if c["direction"] == "exit"}
        long_signals = {(c["strategy_id"], c["ticker"]) for c in candidates
                        if c["direction"] == "long"}

        for pos in self.broker.get_positions():
            row = self.conn.execute(
                "SELECT strategy_id, avg_cost, stop_px FROM positions WHERE fund=? AND ticker=?",
                (self.fund, pos.ticker)).fetchone()
            sid = row["strategy_id"]
            px = self._quote(pos.ticker) or pos.avg_cost
            reason = None
            if row["stop_px"] and px <= row["stop_px"]:
                reason = f"stop hit ({px:.2f} <= {row['stop_px']:.2f})"
            elif sid in retired:
                reason = "strategy retired"
            elif (sid, pos.ticker) in exit_signals:
                reason = "exit signal"
            elif sid is not None and (sid, pos.ticker) not in long_signals:
                reason = "signal no longer active"
            if reason:
                self._close(pos.ticker, sid, reason)
                count += 1
        return count

    def _close(self, ticker: str, strategy_id, reason: str) -> None:
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
            self._record_trade_exit(ticker, strategy_id, fill.price, pos["qty"],
                                    pnl, pnl_pct, reason)

    # ---- entries ----
    def _process_entries(self) -> int:
        candidates = generate_candidates(self.cfg, self.fund, self.conn, self.store, self.as_of, self._bundle)
        longs = [c for c in candidates if c["direction"] == "long"]
        held = {p.ticker for p in self.broker.get_positions()}

        ranked = []
        seen_tickers: set[str] = set()
        cooled_off = self._stop_out_cooldown_tickers()
        longs.sort(key=lambda c: c["strength"], reverse=True)
        for c in longs:
            t = c["ticker"]
            if t in held or t in seen_tickers or self._quote(t) is None:
                continue
            if t in cooled_off:
                continue  # recently stopped out; don't churn straight back in
            if not self.learning.is_active(c["strategy_id"]):
                continue
            seen_tickers.add(t)  # one entry per ticker per session, strongest signal wins
            mult = self.learning.current_multiplier(c["strategy_id"])
            ranked.append((c["strength"] * mult, mult, c))
        ranked.sort(key=lambda x: x[0], reverse=True)

        count = 0
        for _, mult, c in ranked:
            if self._enter(c, mult):
                count += 1
        return count

    def _enter(self, c: dict, weight_multiplier: float) -> bool:
        ticker = c["ticker"]
        report_date = self._in_earnings_blackout(ticker)
        if report_date is not None:
            self.journal.record(
                "skip", ticker=ticker, action="buy",
                reasoning=(f"Skipped {ticker}: earnings report on "
                           f"{report_date.date()} is inside the "
                           f"{self.cfg.pre_earnings_blackout_days}-day blackout."),
                inputs={"report_date": str(report_date.date())})
            return False
        price = self._quote(ticker)
        acct = self.broker.get_account()
        perf = self._strategy_perf(c["strategy_id"])
        qty = sizing.final_qty(
            equity=acct.equity, price=price, ticker_vol_annual=self._ticker_vol(ticker),
            target_vol=self.limits.target_vol, max_positions=self.limits.max_positions,
            hit_rate=perf["hit_rate"], payoff=perf["payoff"],
            weight_multiplier=weight_multiplier, kelly_cap=self.limits.kelly_cap,
            max_position_pct=self.limits.max_position_pct)
        qty *= getattr(self, "_mc_throttle", 1.0)

        if self.fund == "biotech":
            scenario_mult = self._catalyst_scenario_mult(ticker)
            if scenario_mult is None:
                return False        # negative-EV event profile; skip journaled inside
            qty *= scenario_mult

        qty = float(int(qty))
        if qty < 1:
            return False

        positions = self.broker.get_positions()
        verdict = self.risk.check_entry(
            Order(self.fund, ticker, "buy", qty), acct, positions, price)
        if verdict.decision == "rejected":
            self.journal.record("reject", ticker=ticker, action="buy",
                                reasoning=f"Rejected {ticker}: {verdict.reason}.",
                                inputs={"qty": qty, "reason": verdict.reason})
            return False
        if verdict.decision == "resized":
            self.journal.record("resize", ticker=ticker, action="buy",
                                reasoning=f"Resized {ticker} {qty:.0f}->{verdict.qty:.0f}: "
                                          f"{verdict.reason}.",
                                inputs={"from": qty, "to": verdict.qty})
            qty = float(int(verdict.qty))
            if qty < 1:
                return False

        jid = self.journal.record(
            "entry", ticker=ticker, action="buy",
            reasoning=(f"Buy {qty:.0f} {ticker} @ ~{price:.2f} from strategy "
                       f"{c['strategy_id']} (strength {c['strength']:.2f}, "
                       f"weight x{weight_multiplier:.2f}, "
                       f"hit {perf['hit_rate']:.0%}, payoff {perf['payoff']:.2f})."),
            inputs={"strength": c["strength"], "weight_multiplier": weight_multiplier,
                    "ticker_vol": self._ticker_vol(ticker), **perf})
        fill = self.broker.submit_order(Order(self.fund, ticker, "buy", qty,
                                              strategy_id=c["strategy_id"], journal_id=jid))
        if fill:
            self.conn.execute(
                "UPDATE positions SET stop_px=? WHERE fund=? AND ticker=?",
                (self.risk.stop_price(fill.price, self._ticker_vol(ticker)),
                 self.fund, ticker))
            insert(self.conn, "trades", fund=self.fund, strategy_id=c["strategy_id"],
                   ticker=ticker, entry_ts=self._ts(), entry_px=fill.price, qty=qty)
            self.conn.commit()
            return True
        return False

    def _stop_out_cooldown_tickers(self, cooldown_days: int = 14) -> set[str]:
        """Tickers stopped out within the cooldown window (no immediate re-entry)."""
        cutoff = (pd.Timestamp(self._ts()) - pd.Timedelta(days=cooldown_days)).isoformat()
        rows = self.conn.execute(
            "SELECT DISTINCT ticker FROM trades WHERE fund=? AND exit_reason LIKE 'stop hit%' "
            "AND exit_ts >= ?", (self.fund, cutoff)).fetchall()
        return {r["ticker"] for r in rows}

    def _catalyst_scenario_mult(self, ticker: str) -> float | None:
        """Empirical catalyst scenario sizing for biotech entries.

        Uses the ticker's own historical catalyst price reactions (pooled across
        the universe when its history is thin). Negative expected value -> skip
        (returns None). Otherwise scale size by scenario-Kelly confidence.
        """
        from ..research.montecarlo import catalyst_scenario_stats

        own = [r.get("open_price_gap_percent")
               for r in self.bundle_hist().get(ticker, [])]
        own = [float(v) for v in own if v is not None]
        if len(own) >= self.cfg.min_catalyst_events:
            moves, scope = own, "ticker"
        else:
            pooled = [float(v) for recs in self.bundle_hist().values()
                      for r in (recs or [])
                      if (v := r.get("open_price_gap_percent")) is not None]
            moves, scope = pooled, "universe-pooled"
        stats = catalyst_scenario_stats(moves, kelly_cap=self.limits.kelly_cap)
        if stats is None:
            return 1.0      # no event history at all -> no adjustment
        if stats["ev"] <= 0:
            self.journal.record(
                "skip", ticker=ticker, action="buy",
                reasoning=(f"Skipped {ticker}: catalyst scenario EV "
                           f"{stats['ev']:+.2%} over {stats['n_events']} historical "
                           f"events ({scope}); 5th-pct outcome {stats['downside_q05']:+.1%}."),
                inputs={**stats, "scope": scope})
            return None
        mult = max(0.25, min(1.0, stats["kelly"] / self.limits.kelly_cap))
        return mult

    def bundle_hist(self) -> dict:
        return getattr(self._bundle, "hist_catalysts", {}) or {}

    def _strategy_perf(self, strategy_id: int) -> dict:
        row = self.conn.execute(
            "SELECT hit_rate, payoff FROM strategy_performance WHERE strategy_id=? "
            "ORDER BY as_of_ts DESC LIMIT 1", (strategy_id,)).fetchone()
        if row and row["hit_rate"] is not None:
            return {"hit_rate": row["hit_rate"], "payoff": row["payoff"]}
        return {"hit_rate": 0.0, "payoff": 0.0}

    def _record_trade_exit(self, ticker, strategy_id, exit_px, qty, pnl, pnl_pct, reason):
        row = self.conn.execute(
            "SELECT id FROM trades WHERE fund=? AND ticker=? AND exit_ts IS NULL "
            "ORDER BY id DESC LIMIT 1", (self.fund, ticker)).fetchone()
        if row:
            self.conn.execute(
                "UPDATE trades SET exit_ts=?, exit_px=?, pnl=?, pnl_pct=?, exit_reason=? "
                "WHERE id=?", (self._ts(), exit_px, pnl, pnl_pct, reason, row["id"]))
            self.conn.commit()
