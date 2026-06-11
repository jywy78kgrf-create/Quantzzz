import numpy as np
import pandas as pd
import pytest

from quantzzz.research import metrics as m


def test_sharpe_hand_computed():
    # constant 0.1% daily return: vol ~ 0 except float noise -> use mixed series
    r = pd.Series([0.01, -0.005, 0.002, 0.007, -0.003] * 50)
    ann_ret = (1 + r).prod() ** (252 / len(r)) - 1
    ann_vol = r.std(ddof=1) * np.sqrt(252)
    assert m.sharpe(r) == pytest.approx(ann_ret / ann_vol)


def test_sharpe_zero_vol_is_zero():
    assert m.sharpe(pd.Series([0.0] * 100)) == 0.0


def test_max_drawdown_known_path():
    # equity path 1.0 -> 1.2 -> 0.9 -> 1.1 : max dd = 1 - 0.9/1.2 = 0.25
    curve = [1.2, 0.9, 1.1]
    rets = pd.Series(np.diff([1.0] + curve) / np.array([1.0] + curve[:-1]))
    assert m.max_drawdown(rets) == pytest.approx(0.25)


def test_max_drawdown_monotonic_up_is_zero():
    assert m.max_drawdown(pd.Series([0.01] * 50)) == pytest.approx(0.0)


def test_alpha_beta_perfect_tracking():
    idx = pd.bdate_range("2023-01-02", periods=300)
    bench = pd.Series(np.random.default_rng(1).normal(0.0004, 0.01, 300), index=idx)
    port = bench * 2.0  # beta 2, alpha 0
    alpha, beta = m.alpha_beta(port, bench)
    assert beta == pytest.approx(2.0)
    assert alpha == pytest.approx(0.0, abs=1e-10)


def test_alpha_positive_when_constant_edge():
    idx = pd.bdate_range("2023-01-02", periods=300)
    bench = pd.Series(np.random.default_rng(2).normal(0.0, 0.01, 300), index=idx)
    port = bench + 0.001  # 10 bps/day edge
    alpha, beta = m.alpha_beta(port, bench)
    assert beta == pytest.approx(1.0)
    assert alpha == pytest.approx(0.001 * 252)


def test_trade_stats():
    ts = m.trade_stats([0.10, -0.05, 0.20, -0.05])
    assert ts.n_trades == 4
    assert ts.hit_rate == 0.5
    assert ts.avg_win == pytest.approx(0.15)
    assert ts.avg_loss == pytest.approx(-0.05)
    assert ts.payoff == pytest.approx(3.0)


def test_trade_stats_empty():
    assert m.trade_stats([]).n_trades == 0
