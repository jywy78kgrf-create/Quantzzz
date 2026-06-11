"""Vectorized daily backtester.

A strategy produces a DataFrame of target weights (index: dates, columns:
tickers). The backtester shifts weights one bar (no lookahead), applies
per-unit-turnover transaction costs, and returns the daily portfolio return
series plus round-trip trade P&L extracted from weight transitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    returns: pd.Series                       # daily portfolio returns (net of costs)
    weights: pd.DataFrame                    # held weights (post-shift)
    trade_pnls: list[float] = field(default_factory=list)  # per round-trip, in return units

    @property
    def n_days(self) -> int:
        return len(self.returns)


def _round_trip_pnls(held: pd.DataFrame, asset_rets: pd.DataFrame) -> list[float]:
    """Compound each ticker's return over every contiguous holding episode."""
    pnls: list[float] = []
    held_mask = held.to_numpy() != 0
    rets = asset_rets.to_numpy()
    weights = held.to_numpy()
    for j in range(held.shape[1]):
        col = held_mask[:, j]
        if not col.any():
            continue
        # episode boundaries: starts where mask turns on, ends where it turns off
        change = np.diff(col.astype(int), prepend=0)
        starts = np.where(change == 1)[0]
        ends = np.where(change == -1)[0]
        if len(ends) < len(starts):
            ends = np.append(ends, len(col))
        for s, e in zip(starts, ends):
            seg_r = rets[s:e, j]
            seg_w = weights[s:e, j]
            seg = seg_w * np.nan_to_num(seg_r)
            pnls.append(float(np.prod(1 + seg) - 1))
    return pnls


class Backtester:
    def __init__(self, cost_bps: float = 10.0):
        self.cost_bps = cost_bps

    def run(self, target_weights: pd.DataFrame, prices: pd.DataFrame) -> BacktestResult:
        """target_weights and prices share tickers; prices is daily close."""
        prices = prices.reindex(columns=target_weights.columns)
        asset_rets = prices.pct_change()

        # align, forward-fill missing target days, shift 1 bar: today's signal
        # earns tomorrow's return
        tw = target_weights.reindex(asset_rets.index).ffill().fillna(0.0)
        held = tw.shift(1).fillna(0.0)

        gross = (held * asset_rets).sum(axis=1, skipna=True)
        turnover = (tw - held).abs().sum(axis=1)
        costs = turnover * (self.cost_bps / 1e4)
        net = (gross - costs).fillna(0.0)

        # drop leading days before the first position to avoid diluting stats
        active = held.abs().sum(axis=1) > 0
        if active.any():
            first = active.idxmax()
            net = net.loc[first:]
            held = held.loc[first:]
            asset_rets = asset_rets.loc[first:]

        return BacktestResult(
            returns=net,
            weights=held,
            trade_pnls=_round_trip_pnls(held, asset_rets),
        )


def chronological_split(
    dates: pd.DatetimeIndex, train_frac: float = 0.7, embargo_days: int = 21
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Train/test split in time order with an embargo gap to stop leakage."""
    n = len(dates)
    cut = int(n * train_frac)
    return dates[:cut], dates[min(cut + embargo_days, n):]
