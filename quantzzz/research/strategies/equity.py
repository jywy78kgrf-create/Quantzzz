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


# ============================================================================
# Combination families: condition one signal on another. Equity has historically
# been single-signal (unlike the biotech catalyst desk, which is combination-
# rich); these are hand-authored 2-factor interactions on PROVEN features, each
# with an OPTIONAL 3rd-factor toggle the search can flip on. Factor depth is
# therefore data-driven: the loop tries 2 vs 3 factors and the trade-count /
# deflated-Sharpe gates cull anything conditioned down to too few trades. Only
# proven inputs are combined here — regime/insider-conditioned combinations wait
# until those signals earn a forward record, then slot into this same pattern.
# ============================================================================

# ---- quality momentum: improving fundamentals AND price trend ----
QUALITY_MOM = ParamSpace("quality_momentum", "equity", [
    ParamDef("mom_lookback", "int", 60, 200, step=20),
    ParamDef("mom_pctile", "float", 0.4, 0.8, step=0.1),    # how strong a trend to require
    ParamDef("top_n", "int", 3, 12, step=1),
    ParamDef("hold_days", "choice", choices=(21, 42, 63)),
    ParamDef("volume_confirm", "choice", choices=(0, 1)),   # optional 3rd factor
])


def quality_momentum_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    fund = F.beat_and_raise_frame(bundle)
    if fund.empty or fund.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    fund = fund.reindex(columns=bundle.tickers)
    mom = F.momentum(bundle.prices, int(p["mom_lookback"])).reindex(columns=bundle.tickers)
    # 2-factor AND gate: improving fundamentals AND top-pctile momentum
    eligible = (fund > 0) & (mom.rank(axis=1, pct=True) >= float(p["mom_pctile"])).fillna(False)
    if int(p["volume_confirm"]) and not bundle.volume.empty:    # optional 3rd factor
        volr = (bundle.volume.rolling(21).mean()
                / bundle.volume.rolling(63).mean()).reindex(columns=bundle.tickers)
        eligible = eligible & (volr > 1.0).fillna(False)
    score = fund.rank(axis=1) + mom.rank(axis=1)               # blended rank among eligible
    w = _equal_weight_top(score.where(eligible), int(p["top_n"]))
    return _rebalanced(w, int(p["hold_days"]))


# ---- oversold quality: buy the dip, but only on fundamentally sound names ----
OVERSOLD_QUALITY = ParamSpace("oversold_quality", "equity", [
    ParamDef("zlookback", "int", 5, 40, step=5),
    ParamDef("entry_z", "float", 0.5, 2.0, step=0.25),
    ParamDef("top_n", "int", 3, 10, step=1),
    ParamDef("rebalance", "choice", choices=(3, 5, 10)),
    ParamDef("uptrend_filter", "choice", choices=(0, 1)),   # optional 3rd factor
])


def oversold_quality_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    fund = F.beat_and_raise_frame(bundle)
    if fund.empty or fund.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    fund = fund.reindex(columns=bundle.tickers)
    z = F.zscore(bundle.prices, int(p["zlookback"])).reindex(columns=bundle.tickers)
    # 2-factor AND gate: oversold (price) AND quality (fundamentals) — not a
    # falling knife, a quality name on a dip
    eligible = (z < -float(p["entry_z"])).fillna(False) & (fund > 0).fillna(False)
    if int(p["uptrend_filter"]):                              # optional 3rd factor
        lt = F.momentum(bundle.prices, 200).reindex(columns=bundle.tickers)
        eligible = eligible & (lt > 0).fillna(False)          # dip within a longer uptrend
    w = _equal_weight_top((-z).where(eligible), int(p["top_n"]))   # most oversold first
    return _rebalanced(w, int(p["rebalance"]))


STRATEGIES.append((QUALITY_MOM, quality_momentum_signal))
STRATEGIES.append((OVERSOLD_QUALITY, oversold_quality_signal))


# ---- short-term reversal: a daily-native swing trade ----
# The classic ~1-week reversal effect (Lehmann 1990 / Lo-MacKinlay): the biggest
# short-horizon losers tend to bounce. Close-only and entered at the close, so —
# unlike a breakout — it needs no intraday timing the EOD engine can't execute.
# Fast turnover (the swing horizon); optional trend filter to fade dips inside an
# uptrend rather than catch structural decliners. The portfolio-correlation gate
# will reject it if it's merely a re-expression of mean_reversion.
SHORT_REVERSAL = ParamSpace("short_term_reversal", "equity", [
    ParamDef("lookback", "int", 3, 15, step=1),          # short horizon (days)
    ParamDef("top_n", "int", 3, 12, step=1),
    ParamDef("rebalance", "choice", choices=(2, 3, 5)),  # fast turnover = swing
    ParamDef("trend_filter", "choice", choices=(0, 1)),  # optional: dip-in-uptrend only
])


def short_term_reversal_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    ret = F.momentum(bundle.prices, int(p["lookback"]))   # trailing short-horizon return
    score = -ret                                          # most negative return -> top long
    eligible = score.notna()
    if int(p["trend_filter"]):
        lt = F.momentum(bundle.prices, 120)               # longer-term trend still up
        eligible = eligible & (lt > 0).fillna(False)      # fade dips, not falling knives
    w = _equal_weight_top(score.where(eligible), int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


STRATEGIES.append((SHORT_REVERSAL, short_term_reversal_signal))


# ---- low-volatility factor ----
# The low-volatility anomaly: low-realized-vol names earn higher risk-adjusted
# returns than high-vol ones. A genuinely different KIND of edge from the
# momentum-heavy book — it is structurally ~orthogonal to it, so it has a real
# shot at clearing the portfolio-correlation gate the momentum variants keep
# tripping.
LOW_VOL = ParamSpace("low_volatility", "equity", [
    ParamDef("vol_lookback", "int", 20, 252, step=10),
    ParamDef("top_n", "int", 3, 15, step=1),
    ParamDef("rebalance", "choice", choices=(10, 21, 42)),
    ParamDef("mom_screen", "float", 0.0, 1.0, step=0.1),  # >0.5: skip downtrenders
])


def low_volatility_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    vol = F.realized_vol(bundle.prices, int(p["vol_lookback"]))
    score = 1.0 / vol.replace(0, np.nan)                  # lowest vol -> highest score
    if p["mom_screen"] > 0.5:
        mom = F.momentum(bundle.prices, 126)
        score = score.where(mom > 0)                      # defensive, but not falling
    w = _equal_weight_top(score, int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


STRATEGIES.append((LOW_VOL, low_volatility_signal))


# ---- 52-week-high proximity ----
# George & Hwang (2004): names trading near their trailing 1-year high keep
# outperforming. A different construction from return-momentum — it is anchored
# to the distance-from-high, not the magnitude of the move — so it captures a
# distinct slice even where it overlaps momentum thematically.
FIFTY_TWO_HIGH = ParamSpace("fifty_two_week_high", "equity", [
    ParamDef("lookback", "int", 126, 252, step=21),
    ParamDef("top_n", "int", 3, 15, step=1),
    ParamDef("rebalance", "choice", choices=(5, 10, 21)),
    ParamDef("vol_adjust", "float", 0.0, 1.0, step=0.1),  # >0.5: per-unit-risk proximity
])


def fifty_two_week_high_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    px = bundle.prices
    lb = int(p["lookback"])
    trailing_high = px.rolling(lb, min_periods=lb // 2).max()
    proximity = px / trailing_high.replace(0, np.nan)     # ~1.0 = sitting at its high
    if p["vol_adjust"] > 0.5:
        proximity = proximity / F.realized_vol(px, 60).replace(0, np.nan)
    w = _equal_weight_top(proximity, int(p["top_n"]))
    return _rebalanced(w, int(p["rebalance"]))


STRATEGIES.append((FIFTY_TWO_HIGH, fifty_two_week_high_signal))
