"""Promotion criteria and evaluation result for the research loop."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import PromotionThresholds
from . import metrics as M
from .backtest import BacktestResult


@dataclass
class Evaluation:
    is_sharpe: float
    oos_sharpe: float
    oos_alpha: float
    oos_beta: float
    max_dd: float
    n_trades: int
    hit_rate: float
    fitness: float
    oos_returns: pd.Series

    def as_row(self) -> dict:
        return {
            "is_sharpe": self.is_sharpe, "oos_sharpe": self.oos_sharpe,
            "oos_alpha": self.oos_alpha, "max_dd": self.max_dd,
            "n_trades": self.n_trades, "hit_rate": self.hit_rate,
            "fitness": self.fitness,
        }


def evaluate(is_res: BacktestResult, oos_res: BacktestResult,
             benchmark: pd.Series) -> Evaluation:
    is_sharpe = M.sharpe(is_res.returns)
    oos_sharpe = M.sharpe(oos_res.returns)
    alpha, beta = M.alpha_beta(oos_res.returns, benchmark)
    max_dd = M.max_drawdown(oos_res.returns)
    stats = M.trade_stats(oos_res.trade_pnls)

    # fitness rewards OOS Sharpe, penalizes drawdown and IS/OOS overfit gap
    overfit_penalty = max(0.0, is_sharpe - oos_sharpe) * 0.3
    dd_penalty = max_dd * 0.5
    fitness = oos_sharpe - overfit_penalty - dd_penalty

    return Evaluation(
        is_sharpe=is_sharpe, oos_sharpe=oos_sharpe, oos_alpha=alpha, oos_beta=beta,
        max_dd=max_dd, n_trades=stats.n_trades, hit_rate=stats.hit_rate,
        fitness=fitness, oos_returns=oos_res.returns,
    )


def check_promotion(ev: Evaluation, thr: PromotionThresholds,
                    promoted_returns: list[pd.Series]) -> tuple[bool, list[str]]:
    """Return (passed, fail_reasons)."""
    reasons = []
    if ev.oos_sharpe < thr.min_oos_sharpe:
        reasons.append(f"oos_sharpe {ev.oos_sharpe:.2f} < {thr.min_oos_sharpe}")
    if ev.oos_alpha < thr.min_oos_alpha:
        reasons.append(f"oos_alpha {ev.oos_alpha:.3f} < {thr.min_oos_alpha}")
    if ev.max_dd > thr.max_drawdown:
        reasons.append(f"max_dd {ev.max_dd:.2f} > {thr.max_drawdown}")
    if ev.n_trades < thr.min_trades:
        reasons.append(f"n_trades {ev.n_trades} < {thr.min_trades}")
    if ev.is_sharpe > 0 and ev.oos_sharpe < ev.is_sharpe * thr.min_oos_is_ratio:
        reasons.append("oos/is consistency too low")

    # de-correlation vs already-promoted strategies
    for pr in promoted_returns:
        joined = pd.concat([ev.oos_returns, pr], axis=1, join="inner").dropna()
        if len(joined) > 20:
            corr = joined.iloc[:, 0].corr(joined.iloc[:, 1])
            if corr is not None and corr > thr.max_correlation:
                reasons.append(f"correlated {corr:.2f} with promoted strategy")
                break

    return (len(reasons) == 0), reasons
