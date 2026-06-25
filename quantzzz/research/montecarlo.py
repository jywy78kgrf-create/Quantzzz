"""Monte Carlo evaluation layer: bootstrap robustness, drawdown-halt risk,
and catalyst scenario statistics.

These functions evaluate decisions under uncertainty — they never generate
signals. All resampling is from REAL return/event data (block bootstrap keeps
fat tails and autocorrelation), so the simulations inherit the data's
properties rather than a parametric fantasy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def block_bootstrap_paths(returns: pd.Series | np.ndarray, n_paths: int,
                          horizon: int | None = None, block_size: int = 10,
                          seed: int | None = None) -> np.ndarray | None:
    """Resample contiguous blocks of real returns into (n_paths, horizon) paths."""
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if len(r) < block_size * 3:
        return None
    rng = np.random.default_rng(seed)
    T = horizon or len(r)
    n_blocks = int(np.ceil(T / block_size))
    starts = rng.integers(0, len(r) - block_size + 1, size=(n_paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block_size)[None, None, :]).reshape(n_paths, -1)
    return r[idx[:, :T]]


def bootstrap_sharpe_quantile(returns: pd.Series, n_paths: int = 500,
                              q: float = 0.05, seed: int | None = 7) -> float | None:
    """The q-quantile of annualized Sharpe across bootstrap resamples.

    A strategy whose 5th-percentile bootstrap Sharpe is below zero is profitable
    on the realized path but not robustly so — likely curve-fit to luck.
    """
    paths = block_bootstrap_paths(returns, n_paths, seed=seed)
    if paths is None:
        return None
    means = paths.mean(axis=1)
    stds = paths.std(axis=1, ddof=1)
    stds[stds == 0] = np.nan
    sharpes = means / stds * np.sqrt(TRADING_DAYS)
    sharpes = sharpes[np.isfinite(sharpes)]
    if len(sharpes) < n_paths * 0.5:
        return None
    return float(np.quantile(sharpes, q))


def drawdown_halt_probability(portfolio_returns: pd.Series, halt_pct: float,
                              horizon_days: int = 63, n_paths: int = 5000,
                              seed: int | None = 11) -> float | None:
    """P(max drawdown >= halt_pct within the horizon), from bootstrapped paths
    of the portfolio's own recent return history."""
    paths = block_bootstrap_paths(portfolio_returns, n_paths,
                                  horizon=horizon_days, seed=seed)
    if paths is None:
        return None
    curves = np.cumprod(1 + paths, axis=1)
    running_max = np.maximum.accumulate(curves, axis=1)
    max_dd = (1 - curves / running_max).max(axis=1)
    return float((max_dd >= halt_pct).mean())


def catalyst_scenario_stats(moves: list[float], kelly_cap: float = 0.25) -> dict | None:
    """Empirical scenario statistics from historical catalyst price reactions.

    `moves` are fractional one-day reactions (e.g. -0.40 = -40% on a failed
    readout). Returns expected value, tail risk, and a continuous-Kelly
    fraction (EV/variance, capped) for sizing positions held into events.
    """
    arr = np.asarray([m for m in moves if m is not None and np.isfinite(m)], dtype=float)
    if len(arr) < 8:
        return None
    ev = float(arr.mean())
    var = float(arr.var(ddof=1))
    kelly = float(np.clip(ev / var, 0.0, kelly_cap)) if var > 0 else 0.0
    return {
        "n_events": int(len(arr)),
        "ev": ev,
        "p_loss": float((arr < 0).mean()),
        "downside_q05": float(np.quantile(arr, 0.05)),
        "upside_q95": float(np.quantile(arr, 0.95)),
        "kelly": kelly,
    }
