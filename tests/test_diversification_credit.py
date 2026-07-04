"""The uncorrelated-edge DSR credit: a diversifying candidate clears a slightly
lower deflated-Sharpe bar; a redundant one still faces the full bar."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantzzz.config import PROMOTION_THRESHOLDS
from quantzzz.research.promotion import (
    DSR_DIVERSIFY_CREDIT,
    Evaluation,
    check_promotion,
)

THR = PROMOTION_THRESHOLDS["equity"]


def _passing_eval(oos_returns, dsr):
    """An Evaluation that clears every gate EXCEPT possibly DSR/correlation."""
    return Evaluation(
        is_sharpe=1.2, oos_sharpe=max(THR.min_oos_sharpe + 0.3, 1.4),
        oos_alpha=THR.min_oos_alpha + 0.05, oos_beta=0.3,
        max_dd=0.05, n_trades=THR.min_trades + 50, hit_rate=0.55, fitness=1.0,
        oos_returns=oos_returns, window_sharpes=[1.0, 1.1, 0.9, 1.2, 1.0],
        dsr_prob=dsr, bench_max_dd=0.30,
        bootstrap_q05=THR.min_bootstrap_q05 + 0.2, downside_capture=0.5)


def _series(seed, n=260):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(rng.normal(0.001, 0.01, n), index=idx)


def test_uncorrelated_candidate_gets_credit():
    book = _series(1)                       # the one promoted strategy
    indep = _series(999)                    # ~uncorrelated with the book
    # DSR sits in the credit band: below the 0.60 bar, above the 0.50 floor
    dsr = THR.min_dsr_prob - DSR_DIVERSIFY_CREDIT + 0.02
    passed, reasons, _ = check_promotion(_passing_eval(indep, dsr), THR, [(1, book)])
    assert passed, f"uncorrelated {dsr:.2f}-DSR edge should clear the trimmed bar: {reasons}"


def test_redundant_candidate_still_blocked_at_same_dsr():
    book = _series(1)
    corr_ret = book * 1.0 + _series(2) * 0.02   # nearly identical to the book
    dsr = THR.min_dsr_prob - DSR_DIVERSIFY_CREDIT + 0.02
    passed, reasons, _ = check_promotion(_passing_eval(corr_ret, dsr), THR, [(1, book)])
    assert not passed
    # blocked by correlation and/or the FULL dsr bar (no credit when redundant)
    assert any("correlated" in r or "noise floor" in r for r in reasons), reasons


def test_credit_never_promotes_deep_noise():
    book = _series(1)
    indep = _series(999)
    # far below even the floored bar -> still rejected
    passed, reasons, _ = check_promotion(
        _passing_eval(indep, THR.min_dsr_prob - DSR_DIVERSIFY_CREDIT - 0.05), THR, [(1, book)])
    assert not passed
    assert any("noise floor" in r for r in reasons)


def test_no_book_means_full_credit_but_other_gates_hold():
    indep = _series(999)
    # first-ever edge (empty book): gets full credit, but a weak Sharpe still fails
    ev = _passing_eval(indep, THR.min_dsr_prob - 0.05)
    ev.oos_sharpe = 0.1   # break a different gate
    passed, reasons, _ = check_promotion(ev, THR, [])
    assert not passed
    assert any("oos_sharpe" in r for r in reasons)
