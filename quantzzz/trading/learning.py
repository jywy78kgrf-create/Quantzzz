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

            old_mult = self.current_multiplier(sid)
            # reward profitable, high-payoff strategies; shrink losers
            edge = stats.hit_rate * stats.payoff - (1 - stats.hit_rate)
            new_mult = float(min(2.0, max(0.25, 1.0 + 0.5 * edge)))
            active = 1
            if stats.n_trades >= 8 and realized_pnl < 0 and stats.hit_rate < 0.35:
                active = 0  # kill persistent loser
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
