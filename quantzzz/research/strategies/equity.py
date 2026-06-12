"""Equity strategy families: momentum, mean-reversion, beat-and-raise, insider follow.

Each signal_fn returns target weights (dates x tickers). All ranking uses only
information available up to each date (the backtester additionally shifts one
bar), so signals are point-in-time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...data import features as F
from ..strategy_space import ParamDef, ParamSpace


def _equal_weight_top(score: pd.DataFrame, top_n: int, long_short: bool = False) -> pd.DataFrame:
    """Cross-sectional: long the top_n by score each row, optionally short bottom_n."""
    ranks = score.rank(axis=1, ascending=False)
    n_valid = score.notna().sum(axis=1)
    longs = ranks.le(top_n) & score.notna()
    weights = longs.div(longs.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
    if long_short:
        short_ranks = score.rank(axis=1, ascending=True)
        shorts = short_ranks.le(top_n) & score.notna() & (n_valid > top_n * 2).values[:, None]
        sw = shorts.div(shorts.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
        weights = weights - sw
    return weights


def _rebalanced(weights: pd.DataFrame, rebalance: int) -> pd.DataFrame:
    """Only update target weights every `rebalance` days; hold in between."""
    mask = np.zeros(len(weights), dtype=bool)
    mask[::rebalance] = True
    held = weights.where(pd.Series(mask, index=weights.index), other=np.nan)
    return held.ffill().fillna(0.0)


# ---- momentum ----
MOMENTUM = ParamSpace("momentum", "equity", [
    ParamDef("lookback", "int", 20, 252, step=10),
    ParamDef("skip", "int", 0, 21, step=1),
    ParamDef("top_n", "int", 3, 15, step=1),
    ParamDef("rebalance", "choice", choices=(5, 10, 21)),
    ParamDef("vol_filter", "float", 0.0, 1.0, step=0.1),
])


def momentum_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    mom = F.momentum(bundle.prices, int(p["lookback"]), int(p["skip"]))
    if p["vol_filter"] > 0.5:
        vol = F.realized_vol(bundle.prices, 60)
        mom = mom / vol.replace(0, np.nan)  # risk-adjusted momentum
    w = _equal_weight_top(mom, int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


# ---- mean reversion ----
MEANREV = ParamSpace("mean_reversion", "equity", [
    ParamDef("lookback", "int", 5, 60, step=5),
    ParamDef("top_n", "int", 3, 12, step=1),
    ParamDef("entry_z", "float", 0.5, 2.5, step=0.25),
    ParamDef("rebalance", "choice", choices=(1, 3, 5)),
])


def mean_reversion_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    z = F.zscore(bundle.prices, int(p["lookback"]))
    # buy the most oversold (most negative z) below -entry_z
    oversold = z.where(z < -float(p["entry_z"]))
    w = _equal_weight_top(-oversold, int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


# ---- beat and raise (EDGAR fundamentals) ----
BEAT_RAISE = ParamSpace("beat_and_raise", "equity", [
    ParamDef("top_n", "int", 3, 12, step=1),
    ParamDef("hold_days", "choice", choices=(21, 42, 63)),
    ParamDef("mom_tilt", "float", 0.0, 1.0, step=0.1),
])


def beat_and_raise_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    score = F.beat_and_raise_frame(bundle)
    if score.empty or score.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    score = score.reindex(columns=bundle.tickers)
    if p["mom_tilt"] > 0.5:
        mom = F.momentum(bundle.prices, 63).reindex(columns=bundle.tickers)
        score = score.rank(axis=1) + mom.rank(axis=1)
    w = _equal_weight_top(score, int(p["top_n"]))
    return _rebalanced(w, int(p["hold_days"]))


# ---- insider follow (Form 4) ----
INSIDER = ParamSpace("insider_follow", "equity", [
    ParamDef("top_n", "int", 2, 10, step=1),
    ParamDef("hold_days", "choice", choices=(21, 42, 63)),
])


def insider_follow_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    score = F.insider_frame(bundle)
    if score.empty or score.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    score = score.reindex(columns=bundle.tickers)
    # decay the buy signal over the holding window
    score = score.where(score > 0)
    w = _equal_weight_top(score, int(p["top_n"]))
    return _rebalanced(w, int(p["hold_days"]))


# ---- post-earnings-announcement drift (AV true surprises) ----
PEAD = ParamSpace("earnings_surprise", "equity", [
    ParamDef("min_surprise_pct", "float", 2.0, 20.0, step=2.0),
    ParamDef("hold_days", "choice", choices=(21, 42, 63)),
    ParamDef("top_n", "int", 3, 12, step=1),
])


def earnings_surprise_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    surprise = F.earnings_surprise_frame(bundle, hold_days=int(p["hold_days"]))
    if surprise.empty or surprise.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    surprise = surprise.reindex(columns=bundle.tickers)
    qualified = surprise.where(surprise >= float(p["min_surprise_pct"]))
    return _equal_weight_top(qualified, int(p["top_n"]))


# ---- news sentiment momentum (AV news feed) ----
NEWS_MOM = ParamSpace("news_momentum", "equity", [
    ParamDef("lookback", "int", 3, 21, step=2),
    ParamDef("min_sentiment", "float", 0.05, 0.35, step=0.05),
    ParamDef("top_n", "int", 3, 10, step=1),
    ParamDef("rebalance", "choice", choices=(3, 5, 10)),
])


def news_momentum_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    sent = F.news_sentiment_frame(bundle, lookback=int(p["lookback"]))
    if sent.empty or sent.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    sent = sent.reindex(columns=bundle.tickers)
    qualified = sent.where(sent >= float(p["min_sentiment"]))
    w = _equal_weight_top(qualified, int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


STRATEGIES = [
    (MOMENTUM, momentum_signal),
    (MEANREV, mean_reversion_signal),
    (BEAT_RAISE, beat_and_raise_signal),
    (INSIDER, insider_follow_signal),
    (PEAD, earnings_surprise_signal),
    (NEWS_MOM, news_momentum_signal),
]


# ---- volatility-regime momentum: VIX-style stress gating ----
# Momentum harvests trends in calm markets and bleeds in storms. This family
# measures market stress from SPY realized vol (the quantity VIX proxies) and
# de-risks - fully or partially - when stress exceeds a learned percentile.
VOL_REGIME = ParamSpace("vol_regime_momentum", "equity", [
    ParamDef("lookback", "int", 40, 252, step=10),
    ParamDef("top_n", "int", 3, 12, step=1),
    ParamDef("vol_window", "int", 10, 42, step=5),
    ParamDef("calm_pctile", "float", 0.5, 0.9, step=0.05),
    ParamDef("storm_exposure", "float", 0.0, 0.5, step=0.1),
    ParamDef("rebalance", "choice", choices=(5, 10, 21)),
])


def vol_regime_momentum_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    mom = F.momentum(bundle.prices, int(p["lookback"]))
    w = _equal_weight_top(mom, int(p["top_n"]))
    w = _rebalanced(w, int(p["rebalance"]))
    # market stress proxy: median cross-sectional realized vol of the universe
    rv = F.realized_vol(bundle.prices, int(p["vol_window"])).median(axis=1)
    calm_bar = rv.rolling(252, min_periods=60).quantile(float(p["calm_pctile"]))
    stressed = (rv > calm_bar).reindex(w.index).fillna(False)
    scale = pd.Series(1.0, index=w.index).where(~stressed, float(p["storm_exposure"]))
    return w.mul(scale, axis=0)


STRATEGIES.append((VOL_REGIME, vol_regime_momentum_signal))
