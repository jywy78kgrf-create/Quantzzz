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


def test_downside_capture_distinguishes_beta_from_robust():
    import numpy as np, pandas as pd
    from quantzzz.research.metrics import downside_capture
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=200)
    bench = pd.Series(rng.normal(0.0, 0.02, 200), index=idx)
    # leveraged beta: 1.8x the benchmark -> loses MORE on down days
    lev = bench * 1.8
    cap_lev = downside_capture(lev, bench)
    assert cap_lev is not None and cap_lev > 1.5
    # defensive: half the downside -> loses LESS on down days
    defensive = bench * 0.4
    cap_def = downside_capture(defensive, bench)
    assert cap_def is not None and cap_def < 0.6
    # too few down days -> None (can't judge)
    flat = pd.Series(0.01, index=idx)
    assert downside_capture(flat, pd.Series(0.01, index=idx)) is None


def test_downside_capture_gate_rejects_amplifier():
    import numpy as np, pandas as pd
    from quantzzz.research.promotion import Evaluation, check_promotion
    from quantzzz.config import PROMOTION_THRESHOLDS
    thr = PROMOTION_THRESHOLDS["biotech"]
    ev = Evaluation(is_sharpe=2, oos_sharpe=2, oos_alpha=0.5, oos_beta=1.8,
                    max_dd=0.2, n_trades=80, hit_rate=0.6, fitness=2,
                    oos_returns=pd.Series(dtype=float),
                    window_sharpes=[1, 1, 1, 1, 1], dsr_prob=0.99,
                    bootstrap_q05=0.5, downside_capture=2.1)
    passed, reasons, _ = check_promotion(ev, thr, [])
    assert not passed and any("downside capture" in r for r in reasons)
