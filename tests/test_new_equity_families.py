from __future__ import annotations

import random

import numpy as np
import pandas as pd

from quantzzz.data import features as F
from quantzzz.research.strategies.equity import (
    FIFTY_TWO_HIGH,
    LOW_VOL,
    STRATEGIES,
    fifty_two_week_high_signal,
    low_volatility_signal,
)

_CASES = [
    ("low_volatility", low_volatility_signal, LOW_VOL),
    ("fifty_two_week_high", fifty_two_week_high_signal, FIFTY_TWO_HIGH),
]


def _bundle(periods=400, n=30, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=periods)
    tk = [f"T{i}" for i in range(n)]
    px = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0.0003, 0.02, (periods, n)), 0),
        index=dates, columns=tk,
    )
    return F.FeatureBundle(desk="equity", prices=px,
                           volume=pd.DataFrame(1e6, index=dates, columns=tk))


def test_new_families_registered():
    fams = [s[0].family for s in STRATEGIES]
    assert "low_volatility" in fams
    assert "fifty_two_week_high" in fams


def test_new_families_emit_valid_weights():
    b = _bundle()
    for name, fn, sp in _CASES:
        for seed in range(6):
            w = fn(b, sp.random_params(random.Random(seed)))
            assert w.shape == b.prices.shape, name
            rs = w.sum(axis=1)
            assert rs.between(-1e-6, 1 + 1e-6).all(), (name, rs.max())
            assert not w.isna().any().any(), name


def test_new_families_are_point_in_time():
    """A signal row must not change when FUTURE bars are appended (no lookahead)."""
    full = _bundle(periods=400)
    cut = 300
    truncated = F.FeatureBundle(
        desk="equity", prices=full.prices.iloc[:cut],
        volume=full.volume.iloc[:cut])
    for name, fn, sp in _CASES:
        p = sp.random_params(random.Random(3))
        w_full = fn(full, p).iloc[:cut]
        w_trunc = fn(truncated, p)
        # the last row is the freshest decision; it must be identical either way
        pd.testing.assert_series_equal(
            w_full.iloc[-1], w_trunc.iloc[-1], check_names=False,
            obj=f"{name} last-row causality")
