from __future__ import annotations

import random

import numpy as np
import pandas as pd

from quantzzz.data import features as F
from quantzzz.data.options_signals import STALE_DAYS, OptionsSignals
from quantzzz.research.strategies.equity import (
    GAMMA_TILT,
    IV_RANK,
    SKEW_SENT,
    STRATEGIES,
    gamma_tilt_flow_signal,
    iv_rank_positioning_signal,
    skew_sentiment_signal,
)

_CASES = [
    ("iv_rank_positioning", iv_rank_positioning_signal, IV_RANK),
    ("gamma_tilt_flow", gamma_tilt_flow_signal, GAMMA_TILT),
    ("skew_sentiment", skew_sentiment_signal, SKEW_SENT),
]


def _signals_df(dates, tickers, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in tickers:
        for d in dates:
            rows.append({
                "ticker": t, "date": d.strftime("%Y-%m-%d"),
                "iv_atm_30d": 0.2 + 0.1 * rng.random(),
                "iv_skew_25d": rng.normal(0.02, 0.01),
                "gamma_tilt": rng.uniform(-0.5, 0.5),
                "iv_rank_252": rng.random(),
            })
    return pd.DataFrame(rows)


def _bundle(periods=200, n=8, cover=6, seed=1):
    """Bundle with options coverage on the first `cover` of `n` tickers."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=periods)
    tickers = [f"T{i}" for i in range(n)]
    px = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(3e-4, 0.02, (periods, n)), 0),
        index=dates, columns=tickers)
    opts = OptionsSignals(_signals_df(dates, tickers[:cover]))
    return F.FeatureBundle(desk="equity", prices=px, options=opts)


def test_families_registered():
    fams = [s[0].family for s in STRATEGIES]
    for name in ("iv_rank_positioning", "gamma_tilt_flow", "skew_sentiment"):
        assert name in fams


def test_panel_is_point_in_time_and_staleness_bounded():
    dates = pd.bdate_range("2024-01-02", periods=60)
    # observations stop at day 30: values may persist only STALE_DAYS beyond
    obs = OptionsSignals(_signals_df(dates[:30], ["AAA"]))
    panel = obs.panel("iv_rank_252", dates, ["AAA"])
    assert panel.iloc[:30].notna().all().all()
    assert panel.iloc[30:30 + STALE_DAYS].notna().all().all()   # fresh enough
    assert panel.iloc[30 + STALE_DAYS + 1:].isna().all().all()  # stale -> NaN


def test_panel_never_uses_future_values():
    dates = pd.bdate_range("2024-01-02", periods=10)
    df = _signals_df(dates, ["AAA"])
    # spike the LAST day's iv_rank; earlier panel rows must not see it
    df.loc[df.index[-1], "iv_rank_252"] = 999.0
    panel = OptionsSignals(df).panel("iv_rank_252", dates, ["AAA"])
    assert (panel.iloc[:-1]["AAA"] < 999).all()
    assert panel.iloc[-1]["AAA"] == 999.0


def test_families_emit_valid_weights_and_skip_uncovered():
    b = _bundle()
    for name, fn, sp in _CASES:
        for seed in range(5):
            w = fn(b, sp.random_params(random.Random(seed)))
            assert w.shape == b.prices.shape, name
            rs = w.sum(axis=1)
            assert rs.between(-1e-6, 1 + 1e-6).all(), name
            assert not w.isna().any().any(), name
            # tickers without options coverage must never be selected
            assert (w[["T6", "T7"]] == 0).all().all(), name


def test_families_degrade_without_options():
    b = _bundle()
    bare = F.FeatureBundle(desk="equity", prices=b.prices, options=None)
    for name, fn, sp in _CASES:
        w = fn(bare, sp.random_params(random.Random(2)))
        assert (w == 0).all().all(), f"{name} should hold nothing without data"


def test_options_families_get_coverage_rewindow():
    """The loop must re-anchor walk-forward windows to the covered period for
    options families; otherwise the 1999-era in-sample region holds no
    positions and every candidate dies as weak-IS (the 2026-07-02 bug)."""
    import inspect

    from quantzzz.research import loop as L
    from quantzzz.research.strategies.equity import OPTIONS_FAMILIES

    assert OPTIONS_FAMILIES == {
        "iv_rank_positioning", "gamma_tilt_flow", "skew_sentiment"}
    src = inspect.getsource(L.ResearchDesk._evaluate_spec)
    assert "OPTIONS_FAMILIES" in src, "loop no longer re-windows options families"
