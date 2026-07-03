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
    # Annualizing a very short sample extrapolates explosively: the 252/n
    # exponent turns a handful of active days into a meaningless 5-digit
    # "annual" return (the degenerate candidate artifact in the strategy book).
    # Floor the horizon at a quarter and clamp to a sane band — real strategies
    # live far inside [-99%, +1000%], so legitimate metrics are untouched and
    # only degenerate extrapolations are tamed.
    horizon = max(len(returns), TRADING_DAYS // 4)
    ann = total ** (TRADING_DAYS / horizon) - 1
    return float(min(max(ann, -0.99), 10.0))


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


def downside_capture(returns: pd.Series, benchmark: pd.Series) -> float | None:
    """Downside capture ratio: the strategy's average return on benchmark-DOWN
    days divided by the benchmark's average return on those days.

    < 1.0  -> loses less than the benchmark when the sector sells off (robust)
    ~ 1.0  -> moves one-for-one with the sector (pure beta)
    > 1.0  -> loses MORE than the benchmark in stress (fragile / leveraged beta)

    A real edge should not amplify sector drawdowns; this catches strategies
    that only look good because the sector rose, independent of the time-based
    walk-forward windows. Returns None when there aren't enough down days to
    judge.
    """
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 30:
        return None
    r, b = joined.iloc[:, 0], joined.iloc[:, 1]
    down = b < 0
    if int(down.sum()) < 10:
        return None
    bench_down = float(b[down].mean())
    if bench_down >= 0:
        return None
    return float(r[down].mean() / bench_down)


def alpha_beta(returns: pd.Series, benchmark: pd.Series) -> tuple[float, float]:
    """Annualized alpha and beta vs a benchmark return series (aligned on index)."""
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if len(joined) < 20:
        return 0.0, 0.0
    r, b = joined.iloc[:, 0].to_numpy(), joined.iloc[:, 1].to_numpy()
    var_b = float(b.var(ddof=1))
    if var_b < 1e-12:                     # constant / near-constant benchmark slice
        return 0.0, 0.0
    beta = float(np.cov(r, b, ddof=1)[0, 1] / var_b)
    alpha_daily = float(r.mean() - beta * b.mean())
    return alpha_daily * TRADING_DAYS, beta


def deflated_sharpe_prob(returns: pd.Series, n_trials: int) -> float:
    """Probability the observed Sharpe beats the multiple-testing noise floor
    (Bailey & López de Prado's Deflated Sharpe Ratio).

    The benchmark Sharpe is the expected MAXIMUM Sharpe a pure-noise search of
    `n_trials` candidates would produce on this many observations. Evolutionary
    candidates are highly correlated, so callers should pass an effective
    (correlation-adjusted) trial count rather than the raw iteration count.
    Returns a probability in [0, 1]; ~0.5 means "no better than the best noise".
    """
    from statistics import NormalDist

    T = len(returns)
    if T < 30 or n_trials < 1:
        return 0.0
    r = returns.to_numpy()
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    sr = float(r.mean() / sd)                      # per-period (daily) Sharpe
    skew = float(pd.Series(r).skew())
    kurt = float(pd.Series(r).kurt()) + 3.0        # raw kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    nd = NormalDist()
    gamma = 0.5772156649
    n = max(int(n_trials), 1)
    if n == 1:
        sr_null = 0.0
    else:
        e = np.e
        z1 = nd.inv_cdf(max(1e-12, min(1 - 1 / n, 1 - 1e-12)))
        z2 = nd.inv_cdf(max(1e-12, min(1 - 1 / (n * e), 1 - 1e-12)))
        sr_null = np.sqrt(1.0 / T) * ((1 - gamma) * z1 + gamma * z2)

    denom = 1 - skew * sr + ((kurt - 1) / 4.0) * sr ** 2
    if denom <= 0:
        return 0.0
    z = (sr - sr_null) * np.sqrt(T - 1) / np.sqrt(denom)
    return float(nd.cdf(z))


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
