"""Point-in-time access to the distilled options-greeks signals.

``data/snapshots/external/options_signals.parquet`` is the compact distillation
of ~4.6 years of full option chains (112 equity/ETF underlyings, per-contract
greeks) produced offline by ``scripts/distill_options.py`` — one row per
(ticker, chain date) with the daily signal scalars:

    iv_atm_30d/60d/90d/180d, iv_term_structure_30_180, iv_skew_25d,
    put_call_oi_ratio, put_call_volume_ratio, gamma_tilt, total_vega,
    iv_rank_252

Panels returned here are strictly point-in-time: the value shown at date ``d``
is the most recent chain observation with date <= d, and only while fresh
(STALE_DAYS); older values degrade to NaN rather than pretending to be live.
A ticker with no options coverage is simply all-NaN, so families degrade
gracefully to "no position" — the cross-sectional ranks then only ever see
names with real greeks.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

PARQUET_PATH = "external/options_signals.parquet"

# a chain summary older than this (trading days) is unknown, not stale-but-live
STALE_DAYS = 5

OPTION_SIGNALS = (
    "iv_atm_30d", "iv_atm_60d", "iv_atm_90d", "iv_atm_180d",
    "iv_term_structure_30_180", "iv_skew_25d",
    "put_call_oi_ratio", "put_call_volume_ratio",
    "gamma_tilt", "total_vega", "iv_rank_252",
)


class OptionsSignals:
    """Wide per-(ticker, date) signal table with point-in-time panel access."""

    def __init__(self, df: pd.DataFrame):
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        self.df = df
        self._panels: dict = {}

    def panel(self, signal: str, dates: pd.DatetimeIndex,
              tickers: list[str]) -> pd.DataFrame:
        """dates x tickers frame for ``signal``, ffilled at most STALE_DAYS."""
        key = (signal, id(dates), tuple(tickers))
        if key in self._panels:
            return self._panels[key]
        if signal not in self.df.columns:
            out = pd.DataFrame(float("nan"), index=dates, columns=tickers)
        else:
            wide = self.df.pivot_table(index="date", columns="ticker",
                                       values=signal, aggfunc="last")
            # union of native dates and requested dates, so ffill sees every
            # observation, then limit staleness and slice to the ask
            idx = wide.index.union(dates)
            out = (wide.reindex(idx).ffill(limit=STALE_DAYS)
                   .reindex(index=dates, columns=tickers))
        self._panels[key] = out
        return out


def load_options_signals(snapshot_dir: Path) -> OptionsSignals | None:
    path = Path(snapshot_dir) / PARQUET_PATH
    if not path.exists():
        return None
    try:
        return OptionsSignals(pd.read_parquet(path))
    except Exception:  # noqa: BLE001  (corrupt file -> degrade, don't crash)
        return None
