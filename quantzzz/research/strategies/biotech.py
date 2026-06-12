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


# ============================================================================
# External-signal families (data/snapshots/external/ — contaminated-discovery
# candidates; promoted only under the stricter `biotech_external` gate and
# refereed by the forward paper record). Reconciliation flags from the spec are
# enforced in quantzzz.data.external_signals: unsigned |RR| only, no short_float,
# rc_* excluded, one IV-cluster member counts.
# ============================================================================

from ...data import external_signals as X  # noqa: E402  (kept near its users)


def _in_catalyst_window(dtc: pd.DataFrame, entry: int, exit_: int) -> pd.DataFrame:
    """Boolean mask: inside the (exit, entry]-day pre-catalyst run-up window."""
    return (dtc <= entry) & (dtc > exit_)


def _ranked_top(score: pd.DataFrame, eligible: pd.DataFrame,
                max_positions: int, top_quantile: float | None = None) -> pd.DataFrame:
    """Equal-weight the highest-scoring eligible names per row.

    Optionally restrict to the cross-sectional top ``top_quantile`` by score
    before taking the first ``max_positions`` — matches the export's
    ``topNPct(...)`` percentile gating on options signals.
    """
    masked = score.where(eligible)
    if top_quantile is not None:
        thresh = masked.quantile(1.0 - top_quantile, axis=1)
        masked = masked.where(masked.ge(thresh, axis=0))
    ranks = masked.rank(axis=1, ascending=False)
    keep = ranks.le(max_positions) & masked.notna()
    return keep.div(keep.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)


# ---- options-IV run-up: high pre-catalyst implied vol drifts up into events ----
# Research (Phase 22.5/22.6): top-quintile ATM IV before a catalyst predicts the
# largest moves (atm_iv_t30 TIER 1, CLEAN look-ahead). A long-only book captures
# the positioning/vol-risk-premium drift by entering the run-up and exiting
# before the binary print. Only iv_atm_30d is used (Cluster-1 representative).
OPTIONS_IV_RUNUP = ParamSpace("options_iv_runup", "biotech", [
    ParamDef("entry_days_before", "int", 10, 60, step=5),
    ParamDef("exit_days_before", "int", 2, 10, step=1),
    ParamDef("iv_top_quantile", "float", 0.20, 0.50, step=0.05),
    ParamDef("max_positions", "int", 3, 10, step=1),
    ParamDef("bullish_skew_filter", "choice", choices=(0, 1)),
])


def options_iv_runup_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    dtc = F.external_days_to_catalyst_frame(bundle).reindex(columns=bundle.tickers)
    iv = F.external_signal_frame(bundle, X.IV_CLUSTER_REPRESENTATIVE).reindex(columns=bundle.tickers)
    if dtc.isna().all().all() or iv.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    eligible = _in_catalyst_window(dtc, int(p["entry_days_before"]),
                                   int(p["exit_days_before"])).fillna(False) & iv.notna()
    if int(p["bullish_skew_filter"]):
        # call-heavy positioning = low put/call OI ratio (bottom-half of cross-section)
        pcr = F.external_signal_frame(bundle, "put_call_oi_ratio").reindex(columns=bundle.tickers)
        bullish = pcr.le(pcr.median(axis=1), axis=0)
        eligible = eligible & bullish.fillna(False)
    return _ranked_top(iv, eligible, int(p["max_positions"]), float(p["iv_top_quantile"]))


# ---- insider conviction: point-in-time net Form-4 buying (signal I2) ----
# insider_net_purchase_value_90d is stamped on filing dates (the third as_of
# semantic) and forward-filled across its trailing-90d window. I2's live gate is
# net value > $100k; we let the threshold and a catalyst-proximity switch vary.
INSIDER_CONVICTION = ParamSpace("insider_conviction", "biotech", [
    ParamDef("min_net_purchase_k", "float", 50.0, 500.0, step=50.0),  # $thousands
    ParamDef("max_positions", "int", 3, 12, step=1),
    ParamDef("hold_days", "choice", choices=(21, 42, 63)),
    ParamDef("require_catalyst_days", "choice", choices=(0, 60, 120)),
])


def insider_conviction_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    net = F.external_signal_frame(bundle, "insider_net_purchase_value_90d").reindex(columns=bundle.tickers)
    if net.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    qualified = net.gt(float(p["min_net_purchase_k"]) * 1_000.0)
    horizon = int(p["require_catalyst_days"])
    if horizon:
        dtc = F.external_days_to_catalyst_frame(bundle).reindex(columns=bundle.tickers)
        qualified = qualified & (dtc <= horizon).fillna(False)
    w = _ranked_top(net, qualified.fillna(False), int(p["max_positions"]))
    rb = int(p["hold_days"])
    sel = np.zeros(len(w), dtype=bool)
    sel[::rb] = True
    return w.where(pd.Series(sel, index=w.index), other=np.nan).ffill().fillna(0.0)


# ---- event-anchored: trade the pinned catalyst calendar, rank by one signal ----
# The flagship external family. Entries are anchored to catalyst_events_export's
# pinned event_ids; among names inside the run-up window, candidates are ranked
# by a single chosen external signal. rank_signal offers exactly one IV-cluster
# member and only unsigned |RR| — the reconciliation flags made concrete.
EVENT_ANCHORED = ParamSpace("event_anchored", "biotech", [
    ParamDef("entry_days_before", "int", 10, 60, step=5),
    ParamDef("exit_days_before", "int", 2, 10, step=1),
    ParamDef("max_positions", "int", 3, 10, step=1),
    ParamDef("rank_signal", "choice", choices=X.RANKABLE_SIGNALS),
    ParamDef("catalyst_scope", "choice", choices=("all", "pivotal")),
])


def event_anchored_signal(bundle: F.FeatureBundle, p: dict) -> pd.DataFrame:
    scope = X.PIVOTAL_TYPES if p["catalyst_scope"] == "pivotal" else None
    dtc = F.external_days_to_catalyst_frame(bundle, scope).reindex(columns=bundle.tickers)
    if dtc.isna().all().all():
        return pd.DataFrame(0.0, index=bundle.dates, columns=bundle.tickers)
    rank_name = str(p["rank_signal"])
    score = F.external_signal_frame(bundle, rank_name).reindex(columns=bundle.tickers)
    # put/call ratio is bullish when LOW, so rank it ascending (negate the score)
    if rank_name == "put_call_oi_ratio":
        score = -score
    eligible = _in_catalyst_window(dtc, int(p["entry_days_before"]),
                                   int(p["exit_days_before"])).fillna(False)
    if score.isna().all().all():
        # signal absent (e.g. no options coverage): fall back to nearest-catalyst
        score = -dtc
    eligible = eligible & score.notna()
    return _ranked_top(score, eligible, int(p["max_positions"]))


STRATEGIES = [
    (PDUFA_RUNUP, pdufa_runup_signal),
    (POST_DRIFT, post_catalyst_drift_signal),
    (CASH_RUNWAY, cash_runway_signal),
    (BIO_NEWS, bio_news_momentum_signal),
    (OPTIONS_IV_RUNUP, options_iv_runup_signal),
    (INSIDER_CONVICTION, insider_conviction_signal),
    (EVENT_ANCHORED, event_anchored_signal),
]

# Families sourced from the external contaminated-discovery export. The research
# loop holds these to a stricter promotion bar than the price-native families.
EXTERNAL_FAMILIES = frozenset({
    "options_iv_runup", "insider_conviction", "event_anchored",
})
