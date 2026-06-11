import numpy as np
import pandas as pd
import pytest

from quantzzz.research import montecarlo as mc


def _series(mean, vol=0.01, n=600, seed=0):
    return pd.Series(np.random.default_rng(seed).normal(mean, vol, n))


def test_paths_shape_and_values_from_source():
    r = _series(0.001)
    paths = mc.block_bootstrap_paths(r, n_paths=50, horizon=100, seed=1)
    assert paths.shape == (50, 100)
    assert set(np.unique(paths)).issubset(set(r.to_numpy()))


def test_bootstrap_q05_positive_for_strong_edge():
    # 20 bps/day on 1% vol — strongly profitable
    assert mc.bootstrap_sharpe_quantile(_series(0.002), n_paths=300) > 0


def test_bootstrap_q05_negative_for_noise():
    assert mc.bootstrap_sharpe_quantile(_series(0.0), n_paths=300) < 0


def test_bootstrap_deterministic_with_seed():
    r = _series(0.0005, seed=4)
    a = mc.bootstrap_sharpe_quantile(r, n_paths=200, seed=9)
    b = mc.bootstrap_sharpe_quantile(r, n_paths=200, seed=9)
    assert a == b


def test_short_series_returns_none():
    assert mc.block_bootstrap_paths(pd.Series([0.01] * 5), 10) is None
    assert mc.bootstrap_sharpe_quantile(pd.Series([0.01] * 5)) is None


def test_halt_probability_increases_with_vol():
    calm = mc.drawdown_halt_probability(_series(0.0, vol=0.005), halt_pct=0.15,
                                        n_paths=1000)
    wild = mc.drawdown_halt_probability(_series(0.0, vol=0.03, seed=2), halt_pct=0.15,
                                        n_paths=1000)
    assert wild > calm


def test_halt_probability_decreases_with_threshold():
    r = _series(0.0, vol=0.02, seed=3)
    loose = mc.drawdown_halt_probability(r, halt_pct=0.30, n_paths=1000)
    tight = mc.drawdown_halt_probability(r, halt_pct=0.05, n_paths=1000)
    assert tight > loose


def test_catalyst_stats_positive_skew():
    # mostly small pops, occasional crater — like real readouts
    moves = [0.08, 0.12, 0.05, 0.10, -0.35, 0.07, 0.15, 0.06, -0.30, 0.09]
    s = mc.catalyst_scenario_stats(moves)
    assert s["n_events"] == 10
    assert s["downside_q05"] < -0.25
    assert 0 <= s["kelly"] <= 0.25
    assert s["p_loss"] == pytest.approx(0.2)


def test_catalyst_stats_negative_ev():
    s = mc.catalyst_scenario_stats([-0.10, -0.05, -0.20, 0.02, -0.08, -0.15, -0.03, -0.11])
    assert s["ev"] < 0
    assert s["kelly"] == 0.0


def test_catalyst_stats_insufficient_history():
    assert mc.catalyst_scenario_stats([0.1, 0.2]) is None
