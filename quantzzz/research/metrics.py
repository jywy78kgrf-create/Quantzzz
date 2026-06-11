"""Performance metrics over daily return series. Pure numpy/pandas, no I/O."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def annualized_return(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    total = float((1 + returns).prod())
    if total <= 0:
        return -1.0
    return total ** (TRADING_DAYS / len(returns)) - 1


def annualized_vol(returns: pd.Series) -> float:
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1)) * np.sqrt(TRADING_DAYS)


def sharpe(returns: pd.Series, rf_annual: float = 0.0) -> float:
    vol = annualized_vol(returns)
    if vol == 0:
        return 0.0
    excess = annualized_return(returns) - rf_annual
    return excess / vol


def sortino(returns: pd.Series) -> float:
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0
    dd_vol = float(downside.std(ddof=1)) * np.sqrt(TRADING_DAYS)
    if dd_vol == 0:
        return 0.0
    return annualized_return(returns) / dd_vol


def equity_curve(returns: pd.Series) -> pd.Series:
    return (1 + returns).cumprod()


def max_drawdown(returns: pd.Series) -> float:
    """Maximum peak-to-trough loss as a positive fraction."""
    if len(returns) == 0:
        return 0.0
    curve = equity_curve(returns)
    peak = curve.cummax()
    dd = curve / peak - 1.0
    return float(-dd.min())


def alpha_beta(returns: pd.Series, benchmark: pd.Series) -> tuple[float, float]:
    """Annualized alpha and beta vs a benchmark return series (aligned on index)."""
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 20:
        return 0.0, 0.0
    r, b = joined.iloc[:, 0].to_numpy(), joined.iloc[:, 1].to_numpy()
    var_b = b.var()
    if var_b == 0:
        return 0.0, 0.0
    beta = float(np.cov(r, b, ddof=1)[0, 1] / b.var(ddof=1))
    alpha_daily = float(r.mean() - beta * b.mean())
    return alpha_daily * TRADING_DAYS, beta


@dataclass
class TradeStats:
    n_trades: int
    hit_rate: float
    avg_win: float
    avg_loss: float

    @property
    def payoff(self) -> float:
        return self.avg_win / abs(self.avg_loss) if self.avg_loss != 0 else 0.0


def trade_stats(trade_pnls: list[float]) -> TradeStats:
    if not trade_pnls:
        return TradeStats(0, 0.0, 0.0, 0.0)
    arr = np.asarray(trade_pnls, dtype=float)
    wins, losses = arr[arr > 0], arr[arr <= 0]
    return TradeStats(
        n_trades=len(arr),
        hit_rate=float(len(wins) / len(arr)),
        avg_win=float(wins.mean()) if len(wins) else 0.0,
        avg_loss=float(losses.mean()) if len(losses) else 0.0,
    )
