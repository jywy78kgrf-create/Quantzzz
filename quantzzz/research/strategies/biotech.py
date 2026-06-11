"""Biotech strategy families: PDUFA run-up, post-catalyst drift, cash-runway screen.

Catalyst dates come from the BPIQ bundle via FeatureBundle.catalysts. Signals
use only the price calendar plus catalyst timing relative to each date.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...data import features as F
from ..strategy_space import ParamDef, ParamSpace


def _equal_weight(mask: pd.DataFrame, max_positions: int) -> pd.DataFrame:
    """Equal-weight up to max_positions names per row from a boolean mask."""
    # cap positions by keeping the first max_positions True entries per row
    capped = mask & (mask.cumsum(axis=1).le(max_positions))
    return capped.div(capped.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


# ---- PDUFA / catalyst run-up: buy ahead of catalyst, exit before the event ----
PDUFA_RUNUP = ParamSpace("pdufa_runup", "biotech", [
    ParamDef("entry_days_before", "int", 10, 60, step=5),
    ParamDef("exit_days_before", "int", 1, 8, step=1),
    ParamDef("max_positions", "int", 3, 12, step=1),
])


def pdufa_runup_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    dtc = F.days_to_catalyst_frame(bundle).reindex(columns=bundle.tickers)
    if dtc.empty:
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    entry, exit_ = int(p["entry_days_before"]), int(p["exit_days_before"])
    in_window = (dtc <= entry) & (dtc > exit_)
    return _equal_weight(in_window.fillna(False), int(p["max_positions"]))


# ---- post-catalyst drift: ride momentum after a recent catalyst ----
POST_DRIFT = ParamSpace("post_catalyst_drift", "biotech", [
    ParamDef("drift_days", "int", 5, 40, step=5),
    ParamDef("mom_lookback", "int", 5, 20, step=5),
    ParamDef("max_positions", "int", 3, 12, step=1),
])


def post_catalyst_drift_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    dtc = F.days_to_catalyst_frame(bundle).reindex(columns=bundle.tickers)
    if dtc.empty:
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    # days since the most recent past catalyst = -(days to catalyst) when negative
    # days_to_catalyst is forward-looking; approximate "just had a catalyst" as
    # the window right after dtc resets (a new nearest-future catalyst appears).
    recent = (dtc.shift(1) - dtc) < 0  # nearest catalyst moved further out -> one just passed
    window = recent.rolling(int(p["drift_days"]), min_periods=1).max().fillna(0) > 0
    mom = F.momentum(bundle.prices, int(p["mom_lookback"])).reindex(columns=bundle.tickers)
    qualifying = window & (mom > 0)
    return _equal_weight(qualifying.fillna(False), int(p["max_positions"]))


# ---- cash-runway screen: own well-capitalized names, momentum-tilted ----
CASH_RUNWAY = ParamSpace("cash_runway_screen", "biotech", [
    ParamDef("min_runway_q", "float", 2.0, 12.0, step=1.0),
    ParamDef("mom_lookback", "int", 20, 120, step=20),
    ParamDef("max_positions", "int", 4, 14, step=1),
    ParamDef("rebalance", "choice", choices=(10, 21, 42)),
])


def cash_runway_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    runway = F.cash_runway_frame(bundle).reindex(columns=bundle.tickers)
    mom = F.momentum(bundle.prices, int(p["mom_lookback"])).reindex(columns=bundle.tickers)
    if runway.empty or runway.isna().all().all():
        # no fundamentals -> fall back to pure momentum screen
        safe = pd.DataFrame(True, index=bundle.dates, columns=bundle.tickers)
    else:
        safe = runway >= float(p["min_runway_q"])
    score = mom.where(safe)
    ranks = score.rank(axis=1, ascending=False)
    mask = ranks.le(int(p["max_positions"])) & score.notna()
    w = mask.div(mask.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    rb = int(p["rebalance"])
    sel = np.zeros(len(w), dtype=bool)
    sel[::rb] = True
    return w.where(pd.Series(sel, index=w.index), other=np.nan).ffill().fillna(0.0)


# ---- biotech news sentiment: catalyst-heavy names react hard to coverage ----
BIO_NEWS = ParamSpace("bio_news_momentum", "biotech", [
    ParamDef("lookback", "int", 3, 15, step=2),
    ParamDef("min_sentiment", "float", 0.05, 0.35, step=0.05),
    ParamDef("top_n", "int", 3, 10, step=1),
    ParamDef("rebalance", "choice", choices=(3, 5, 10)),
])


def bio_news_momentum_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    sent = F.news_sentiment_frame(bundle, lookback=int(p["lookback"]))
    if sent.empty or sent.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    sent = sent.reindex(columns=bundle.tickers)
    qualified = (sent >= float(p["min_sentiment"]))
    ranks = sent.rank(axis=1, ascending=False)
    mask = qualified & ranks.le(int(p["top_n"]))
    w = mask.div(mask.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    rb = int(p["rebalance"])
    sel = np.zeros(len(w), dtype=bool)
    sel[::rb] = True
    return w.where(pd.Series(sel, index=w.index), other=np.nan).ffill().fillna(0.0)


STRATEGIES = [
    (PDUFA_RUNUP, pdufa_runup_signal),
    (POST_DRIFT, post_catalyst_drift_signal),
    (CASH_RUNWAY, cash_runway_signal),
    (BIO_NEWS, bio_news_momentum_signal),
]
