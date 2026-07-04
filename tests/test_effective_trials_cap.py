"""The effective-trials cap: the deflated-Sharpe noise floor must plateau instead
of rising without bound as the backtest count accumulates."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantzzz.research import metrics as M
from quantzzz.research.loop import ResearchDesk


class _FakeConn:
    def __init__(self, count):
        self._count = count

    def execute(self, *a, **k):
        cnt = self._count

        class _Cur:
            def fetchone(self_inner):
                return {"c": cnt}
        return _Cur()


def _desk(count):
    d = ResearchDesk.__new__(ResearchDesk)
    d.conn = _FakeConn(count)
    d.desk = "equity"
    d._oos_sample = []          # no correlation sample -> sqrt(N) path
    return d


def test_effective_trials_plateaus():
    small = _desk(400)._effective_trials()      # sqrt(400)=20, under the cap
    huge = _desk(28_543)._effective_trials()    # sqrt=169, would blow past cap
    assert small == 20
    assert huge == ResearchDesk.MAX_EFFECTIVE_TRIALS == 50
    # a 10x further increase in backtests must NOT raise the floor further
    assert _desk(300_000)._effective_trials() == 50


def test_cap_lets_a_strong_new_edge_clear_dsr():
    """At the capped trial count, a genuinely strong OOS Sharpe (~the greeks'
    1.7) clears DSR ~0.5; under the old uncapped 169 it did not."""
    T = 456
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-02", periods=T)
    # build a series with an EXACT realized annualized Sharpe of 1.8
    z = rng.normal(0, 1, T)
    z = (z - z.mean()) / z.std(ddof=1)            # exact zero mean, unit std (ddof=1)
    r = pd.Series((z + 1.8 / np.sqrt(252)) * 0.01, index=idx)
    dsr_capped = M.deflated_sharpe_prob(r, ResearchDesk.MAX_EFFECTIVE_TRIALS)
    dsr_uncapped = M.deflated_sharpe_prob(r, 169)
    assert dsr_capped > dsr_uncapped              # cap raises the probability
    assert dsr_capped >= 0.5                      # promotable at ~1.8 Sharpe
    assert dsr_uncapped < 0.5                     # the old floor blocked it
