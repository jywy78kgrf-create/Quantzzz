"""Recursive learning loop: review closed trades and adjust strategy weights."""

from __future__ import annotations

import sqlite3

from ..config import Config
from ..db import insert, utcnow
from ..research import metrics as M


class LearningLoop:
    def __init__(self, cfg: Config, fund: str, conn: sqlite3.Connection, journal, llm=None):
        self.cfg = cfg
        self.fund = fund
        self.conn = conn
        self.journal = journal
        self.llm = llm

    def unreviewed_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) n FROM trades WHERE fund=? AND exit_ts IS NOT NULL AND reviewed=0",
            (self.fund,)).fetchone()
        return row["n"]

    def current_multiplier(self, strategy_id: int) -> float:
        row = self.conn.execute(
            "SELECT weight_multiplier FROM strategy_performance WHERE strategy_id=? "
            "ORDER BY as_of_ts DESC LIMIT 1", (strategy_id,)).fetchone()
        return row["weight_multiplier"] if row else 1.0

    def is_active(self, strategy_id: int) -> bool:
        row = self.conn.execute(
            "SELECT active FROM strategy_performance WHERE strategy_id=? "
            "ORDER BY as_of_ts DESC LIMIT 1", (strategy_id,)).fetchone()
        return bool(row["active"]) if row else True

    def review(self) -> int:
        """Recompute per-strategy stats from closed trades; adjust multipliers."""
        strategies = self.conn.execute(
            "SELECT DISTINCT strategy_id FROM trades WHERE fund=? AND exit_ts IS NOT NULL",
            (self.fund,)).fetchall()
        reviewed = 0
        for row in strategies:
            sid = row["strategy_id"]
            if sid is None:
                continue
            trades = self.conn.execute(
                "SELECT pnl, pnl_pct FROM trades WHERE fund=? AND strategy_id=? "
                "AND exit_ts IS NOT NULL", (self.fund, sid)).fetchall()
            pnls = [t["pnl_pct"] for t in trades if t["pnl_pct"] is not None]
            if not pnls:
                continue
            stats = M.trade_stats(pnls)
            realized_pnl = sum(t["pnl"] or 0 for t in trades)
            # Beta-binomial shrinkage: small samples get pulled toward a 0.45
            # prior (10 pseudo-trades) so a 4-for-6 streak doesn't read as a
            # 67% hit rate. Converges to the raw rate as evidence accumulates.
            wins = stats.hit_rate * stats.n_trades
            hit_shrunk = (wins + 4.5) / (stats.n_trades + 10.0)

            old_mult = self.current_multiplier(sid)
            # Statistical patience: with few closed trades, hit rates are noise
            # (the same standard we hold research to). Track stats but don't
            # act until the sample can support a decision. One asymmetric
            # exception: clear early bleeding earns a partial de-weight long
            # before the full sample arrives — biotech holding periods make
            # waiting for 15 closed trades a year-scale exposure to a bad
            # promotion. De-weighting is cheap to reverse; losses are not.
            MIN_ADJUST, MIN_RETIRE, MIN_CAUTION = 15, 20, 8
            early_caution = False
            if stats.n_trades < MIN_CAUTION:
                new_mult = old_mult
            elif stats.n_trades < MIN_ADJUST:
                if realized_pnl < 0 and hit_shrunk < 0.30:
                    new_mult = max(0.5, round(old_mult * 0.7, 2))
                    early_caution = new_mult < old_mult
                else:
                    new_mult = old_mult
            else:
                edge = hit_shrunk * stats.payoff - (1 - hit_shrunk)
                new_mult = float(min(2.0, max(0.25, 1.0 + 0.5 * edge)))
            active = 1
            if stats.n_trades >= MIN_RETIRE and realized_pnl < 0 and hit_shrunk < 0.35:
                active = 0  # persistent loser with a real sample behind it
                self.conn.execute(
                    "UPDATE strategies SET status='retired', retired_ts=? WHERE id=?",
                    (utcnow(), sid))

            insert(self.conn, "strategy_performance", strategy_id=sid, fund=self.fund,
                   as_of_ts=utcnow(), n_closed=stats.n_trades, hit_rate=stats.hit_rate,
                   payoff=stats.payoff, realized_pnl=realized_pnl, avg_slippage_bps=0.0,
                   weight_multiplier=new_mult, active=active)
            self.journal.record(
                "learning", action=f"strategy {sid}",
                reasoning=(f"Reviewed {stats.n_trades} trades: hit {stats.hit_rate:.0%}, "
                           f"payoff {stats.payoff:.2f}, realized P&L {realized_pnl:,.0f}. "
                           f"Weight {old_mult:.2f}->{new_mult:.2f}"
                           f"{' (early caution: bleeding on a small sample)' if early_caution else ''}"
                           f"{', RETIRED' if not active else ''}."),
                inputs={"hit_rate": stats.hit_rate, "payoff": stats.payoff,
                        "n": stats.n_trades}, ref_table="strategies", ref_id=sid)
            reviewed += 1

        self.conn.execute(
            "UPDATE trades SET reviewed=1 WHERE fund=? AND exit_ts IS NOT NULL", (self.fund,))
        self.conn.commit()

        if self.llm and self.llm.available and reviewed:
            self._llm_review()
        return reviewed

    def _llm_review(self) -> None:
        entries = [dict(r) for r in self.conn.execute(
            "SELECT entry_type, ticker, reasoning FROM journal_entries WHERE fund=? "
            "ORDER BY id DESC LIMIT 30", (self.fund,)).fetchall()]
        outcomes = [dict(r) for r in self.conn.execute(
            "SELECT ticker, pnl_pct, exit_reason FROM trades WHERE fund=? "
            "AND exit_ts IS NOT NULL ORDER BY id DESC LIMIT 30", (self.fund,)).fetchall()]
        try:
            review = self.llm.review_journal(self.fund, entries, outcomes)
        except Exception:
            review = None
        if review:
            self.journal.record("llm_review", reasoning=review, action="periodic review")
