"""Point-in-time correctness + reconciliation-flag enforcement for the external
biotech signal export and the families that consume it."""

import numpy as np
import pandas as pd
import pytest

from quantzzz.data import external_signals as X
from quantzzz.data.external_signals import ExternalSignals
from quantzzz.data.features import (
    FeatureBundle, external_days_to_catalyst_frame, external_signal_frame,
)
from quantzzz.research.strategies import biotech as B


def _make_signals():
    """A tiny hand-built export covering all three as_of semantics."""
    history = pd.DataFrame([
        # candle signal (event-pinned), AAA: daily, value = day index
        {"ticker": "AAA", "as_of_date": "2023-01-02", "signal_name": "rsi_14d", "value": 40.0, "event_id": 1.0},
        {"ticker": "AAA", "as_of_date": "2023-01-09", "signal_name": "rsi_14d", "value": 55.0, "event_id": 1.0},
        # the SAME (ticker, day) recurs under an overlapping event -> dedupe to last
        {"ticker": "AAA", "as_of_date": "2023-01-09", "signal_name": "rsi_14d", "value": 99.0, "event_id": 2.0},
        # options signal (null event_id), stamped on an options market day
        {"ticker": "AAA", "as_of_date": "2023-01-04", "signal_name": "iv_atm_30d", "value": 0.80, "event_id": np.nan},
        {"ticker": "BBB", "as_of_date": "2023-01-04", "signal_name": "iv_atm_30d", "value": 0.40, "event_id": np.nan},
        # signed risk reversal: one positive, one negative -> |RR| equalizes magnitude
        {"ticker": "AAA", "as_of_date": "2023-01-04", "signal_name": "risk_reversal_25d", "value": -0.15, "event_id": np.nan},
        {"ticker": "BBB", "as_of_date": "2023-01-04", "signal_name": "risk_reversal_25d", "value": 0.15, "event_id": np.nan},
        # insider signal (null event_id), stamped on a filing date
        {"ticker": "AAA", "as_of_date": "2023-01-05", "signal_name": "insider_net_purchase_value_90d", "value": 250_000.0, "event_id": np.nan},
        # a deny-listed signal that must never survive the loader
        {"ticker": "AAA", "as_of_date": "2023-01-04", "signal_name": "short_float", "value": 12.0, "event_id": np.nan},
    ])
    history["as_of_date"] = pd.to_datetime(history["as_of_date"])
    events = pd.DataFrame([
        {"event_id": 1, "ticker": "AAA", "catalyst_type": "PDUFA",
         "catalyst_date": "2023-02-01", "indication_text": "x", "is_cns": 0, "status": "occurred"},
        {"event_id": 3, "ticker": "BBB", "catalyst_type": "Phase2",
         "catalyst_date": "2023-02-15", "indication_text": "y", "is_cns": 0, "status": "occurred"},
        # cancelled / undated rows must be ignored by the calendar
        {"event_id": 4, "ticker": "AAA", "catalyst_type": "Other",
         "catalyst_date": None, "indication_text": "z", "is_cns": 0, "status": "occurred"},
    ])
    events["catalyst_date"] = pd.to_datetime(events["catalyst_date"], errors="coerce")
    # mimic the loader's deny-list filtering (keep signed RR for |RR| derivation)
    drop = X.EXCLUDED_SIGNALS - {"risk_reversal_25d"}
    history = history[~history["signal_name"].isin(drop)]
    return ExternalSignals(history=history, events=events)


def _bundle(ext, tickers=("AAA", "BBB")):
    dates = pd.bdate_range("2023-01-02", "2023-01-12")
    prices = pd.DataFrame(100.0, index=dates, columns=list(tickers))
    return FeatureBundle(desk="biotech", prices=prices, external=ext)


def test_pit_no_lookahead_on_observation_day():
    """A signal is unknown before its as_of_date and known from it forward."""
    ext = _make_signals()
    b = _bundle(ext)
    iv = external_signal_frame(b, "iv_atm_30d")
    # the iv print is 2023-01-04; before that it must be NaN
    assert pd.isna(iv.loc["2023-01-03", "AAA"])
    assert iv.loc["2023-01-04", "AAA"] == pytest.approx(0.80)
    assert iv.loc["2023-01-05", "AAA"] == pytest.approx(0.80)  # carried forward


def test_candle_dedup_keeps_last_overlapping_event():
    ext = _make_signals()
    b = _bundle(ext)
    rsi = external_signal_frame(b, "rsi_14d")
    # 2023-01-09 had two rows (events 1 and 2); last (99.0) wins
    assert rsi.loc["2023-01-09", "AAA"] == pytest.approx(99.0)


def test_staleness_tolerance_drops_old_values():
    """Beyond the per-class tolerance a carried value becomes NaN."""
    ext = _make_signals()
    dates = pd.bdate_range("2023-01-02", "2023-03-01")  # >10d past the options print
    prices = pd.DataFrame(100.0, index=dates, columns=["AAA", "BBB"])
    b = FeatureBundle(desk="biotech", prices=prices, external=ext)
    iv = external_signal_frame(b, "iv_atm_30d")
    assert iv.loc["2023-01-04", "AAA"] == pytest.approx(0.80)
    # ~6 weeks later, far beyond the 10-day options tolerance
    assert pd.isna(iv.loc["2023-02-20", "AAA"])


def test_abs_risk_reversal_is_unsigned_only():
    """|RR| is exposed; the signed series is deny-listed and equal-magnitude
    opposite-sign inputs collapse to the same value."""
    ext = _make_signals()
    b = _bundle(ext)
    arr = external_signal_frame(b, "abs_risk_reversal_25d")
    assert arr.loc["2023-01-04", "AAA"] == pytest.approx(0.15)
    assert arr.loc["2023-01-04", "BBB"] == pytest.approx(0.15)  # was -0.15 / +0.15
    # the rankable set offers |RR| but never the signed form
    assert "abs_risk_reversal_25d" in X.RANKABLE_SIGNALS
    assert "risk_reversal_25d" not in X.RANKABLE_SIGNALS


def test_short_float_and_rc_excluded_from_loader_and_rankables():
    ext = _make_signals()
    b = _bundle(ext)
    # short_float never materializes as a panel
    sf = external_signal_frame(b, "short_float")
    assert sf.isna().all().all()
    # deny-list and rankable registry hold the spec's flags
    for s in ("short_float", "insider_own", "rc_vol_ratio",
              "rc_vol_ratio_180d", "rc_vol_ratio_cat"):
        assert s in X.EXCLUDED_SIGNALS
        assert s not in X.RANKABLE_SIGNALS


def test_only_one_iv_cluster_member_is_rankable():
    """Cluster-1 (IV tenor ladder) contributes exactly one rankable member."""
    rankable_iv = [s for s in X.RANKABLE_SIGNALS if s in X.IV_CLUSTER]
    assert rankable_iv == [X.IV_CLUSTER_REPRESENTATIVE]


def test_days_to_catalyst_uses_pinned_events_pointing_forward():
    ext = _make_signals()
    b = _bundle(ext)
    dtc = external_days_to_catalyst_frame(b)
    # AAA catalyst 2023-02-01; on 2023-01-02 that is 30 calendar days out
    assert dtc.loc["2023-01-02", "AAA"] == pytest.approx(30.0)
    # never negative (only forward-looking next catalyst)
    assert (dtc.dropna(how="all").fillna(0) >= 0).all().all()


def test_pivotal_scope_filters_catalyst_types():
    ext = _make_signals()
    b = _bundle(ext)
    pivotal = external_days_to_catalyst_frame(b, X.PIVOTAL_TYPES)
    # BBB's only event is Phase2 (not pivotal) -> no forward catalyst under scope
    assert pivotal["BBB"].isna().all()
    # AAA's PDUFA is pivotal -> still present
    assert pivotal["AAA"].notna().any()


def test_event_anchored_weights_are_valid_and_in_window():
    ext = _make_signals()
    b = _bundle(ext)
    p = {"entry_days_before": 40, "exit_days_before": 2, "max_positions": 5,
         "rank_signal": "iv_atm_30d", "catalyst_scope": "all"}
    w = B.event_anchored_signal(b, p)
    assert (w.abs().sum(axis=1) <= 1.0001).all()
    assert (w >= 0).all().all()                      # long-only
    assert (w.abs().sum(axis=1) > 0).any()           # actually trades


def test_external_families_face_stricter_promotion_gate():
    from quantzzz.config import load_config, PROMOTION_THRESHOLDS_EXTERNAL
    cfg = load_config()
    for fam in B.EXTERNAL_FAMILIES:
        thr = cfg.promotion_for("biotech", fam)
        assert thr is PROMOTION_THRESHOLDS_EXTERNAL
        assert thr.min_dsr_prob >= 0.90
        assert thr.min_positive_windows == 5   # ALL walk-forward windows
    # a price-native biotech family keeps the standard biotech gate
    standard = cfg.promotion_for("biotech", "pdufa_runup")
    assert standard is not PROMOTION_THRESHOLDS_EXTERNAL


def test_families_degrade_gracefully_without_external():
    """No external export → families emit no positions rather than erroring."""
    dates = pd.bdate_range("2023-01-02", "2023-01-12")
    prices = pd.DataFrame(100.0, index=dates, columns=["AAA", "BBB"])
    b = FeatureBundle(desk="biotech", prices=prices, external=None)
    for fam, fn in [("options_iv_runup", B.options_iv_runup_signal),
                    ("insider_conviction", B.insider_conviction_signal),
                    ("event_anchored", B.event_anchored_signal)]:
        space = next(s for s, _ in B.STRATEGIES if s.family == fam)
        w = fn(b, space.random_params(__import__("random").Random(0)))
        assert (w.abs().sum(axis=1) == 0).all(), fam
