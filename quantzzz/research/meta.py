"""Meta-learning: closing the OUTERMOST loop.

The learning loop (trading/learning.py) judges each strategy's forward record one
strategy at a time — de-weighting and retiring individual overfits. What it does
NOT do is learn the PATTERN: if a whole FAMILY's promotions keep clearing the
backtest gate and then failing forward, the gate keeps waving that profile
through, and the system re-promotes-then-catches the same overfit shape forever.

This module aggregates the forward record by family and feeds it back:
  (1) GATE recalibration — a family whose promotions chronically under-deliver
      forward faces a HIGHER backtest bar. It only ever tightens, never loosens,
      so the meta-layer can only reduce promotions of a bad profile.
  (2) SEARCH prior — bias proposal toward families whose edges actually survive.

Both are sample-aware (Beta-Binomial shrinkage): with little forward evidence a
family's score sits at neutral and nothing changes, so the meta-layer cannot
itself overfit a thin record. It activates only as the live sample matures.
"""

from __future__ import annotations

import sqlite3

MIN_LIVE_CLOSED = 12        # closed LIVE trades before a strategy counts as evidence
PRIOR_A = 2.0               # Beta prior pseudo-counts -> neutral survival = 0.5,
PRIOR_B = 2.0               # ~4 pseudo-obs so a family needs real evidence to move
NEUTRAL = PRIOR_A / (PRIOR_A + PRIOR_B)
TIGHTEN_K = 0.8             # how hard to tighten per unit of forward shortfall
MAX_TIGHTEN = 1.4           # cap: never more than +40% on a family's Sharpe bar


def family_forward_scores(conn: sqlite3.Connection, desk: str) -> dict[str, float]:
    """Per-family shrunk forward-survival rate in [0,1] (NEUTRAL when thin).

    survival = fraction of the desk's strategies that, with a real LIVE sample
    (>= MIN_LIVE_CLOSED closed live trades), are net-profitable forward — i.e.
    their backtest promise actually held up in the forward paper record.
    """
    rows = conn.execute(
        """SELECT s.family AS family, COUNT(*) AS n,
                  SUM(CASE WHEN x.live_pnl > 0 THEN 1 ELSE 0 END) AS survivors
           FROM strategies s
           JOIN (SELECT strategy_id, COUNT(*) AS live_closed, SUM(pnl) AS live_pnl
                 FROM trades WHERE source='live' AND exit_ts IS NOT NULL
                 GROUP BY strategy_id HAVING COUNT(*) >= ?) x ON x.strategy_id = s.id
           WHERE s.desk = ?
           GROUP BY s.family""",
        (MIN_LIVE_CLOSED, desk)).fetchall()
    return {r["family"]: (r["survivors"] + PRIOR_A) / (r["n"] + PRIOR_A + PRIOR_B)
            for r in rows}


def gate_factor(score: float | None) -> float:
    """Multiplier (>= 1.0) for a family's min-OOS-Sharpe bar. Only tightens:
    a chronic forward-underdeliverer must clear a higher backtest bar."""
    if score is None:
        return 1.0
    shortfall = max(0.0, NEUTRAL - score) / NEUTRAL      # 0 (neutral) .. 1 (worst)
    return min(MAX_TIGHTEN, 1.0 + TIGHTEN_K * shortfall)


def search_weight(score: float | None) -> float:
    """Relative proposal weight for a family — favor what survives forward, but
    keep a floor so a struggling family is never fully abandoned."""
    if score is None:
        return 1.0
    return max(0.3, 0.5 + score)                          # ~0.8 (failing) .. 1.5 (proven)
