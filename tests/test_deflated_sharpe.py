import numpy as np
import pandas as pd
import pytest

from quantzzz.research.backtest import walk_forward_windows
from quantzzz.research.metrics import deflated_sharpe_prob


def _rets(mean, n=750, seed=0):
    return pd.Series(np.random.default_rng(seed).normal(mean, 0.01, n))


def test_strong_edge_high_probability():
    # 15 bps/day on 1% vol = daily SR 0.15 (~2.4 annualized) over 3y
    assert deflated_sharpe_prob(_rets(0.0015), n_trials=10) > 0.95


def test_noise_low_probability():
    assert deflated_sharpe_prob(_rets(0.0), n_trials=50) < 0.6


def test_more_trials_raises_the_bar():
    r = _rets(0.0006, seed=3)
    p_few = deflated_sharpe_prob(r, n_trials=2)
    p_many = deflated_sharpe_prob(r, n_trials=500)
    assert p_many < p_few


def test_short_series_rejected():
    assert deflated_sharpe_prob(_rets(0.01, n=10), n_trials=5) == 0.0


def test_walk_forward_windows_disjoint_and_ordered():
    dates = pd.bdate_range("2020-01-01", periods=1000)
    is_dates, windows = walk_forward_windows(dates, n_windows=3, test_frac=0.4,
                                             embargo_days=21)
    assert len(windows) == 3
    # IS strictly before all OOS, with embargo
    assert is_dates.max() < windows[0].min()
    assert (windows[0].min() - is_dates.max()).days >= 21
    # windows disjoint and chronological
    for a, b in zip(windows, windows[1:]):
        assert a.max() < b.min()
    # combined OOS covers ~40%
    total_oos = sum(len(w) for w in windows)
    assert abs(total_oos - 400) <= 3


def test_should_replace_decisions():
    import pandas as pd
    from quantzzz.research.promotion import Evaluation, should_replace

    def ev(sharpe, fit, boot):
        return Evaluation(1.5, sharpe, 0.1, 1.0, 0.2, 50, 0.55, fit,
                          pd.Series(dtype=float), [1, 1, 1], 0.9, 0.3, boot)

    inc = {"oos_sharpe": 1.2, "fitness": 1.0, "bootstrap_q05": 0.5, "live_mult": 1.0}
    ok, why = should_replace(ev(1.45, 1.3, 0.6), inc)      # +21%, stronger everywhere
    assert ok
    ok, _ = should_replace(ev(1.25, 1.3, 0.6), inc)        # +4%: inside noise
    assert not ok
    ok, _ = should_replace(ev(1.45, 1.3, 0.4), inc)        # less robust bootstrap
    assert not ok
    live = {**inc, "live_mult": 1.4}                        # incumbent winning live
    ok, why = should_replace(ev(1.45, 1.3, 0.6), live)
    assert not ok and "live" in why
