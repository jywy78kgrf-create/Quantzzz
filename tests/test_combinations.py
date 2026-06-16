"""Combination families require BOTH factors (an AND gate), expose an optional
3rd-factor toggle that further restricts, and degrade safely when a feature is
absent. Feature frames are monkeypatched so the combination logic is tested in
isolation from feature extraction."""

import numpy as np
import pandas as pd
import pytest

from quantzzz.data import features as F
from quantzzz.data.features import FeatureBundle
from quantzzz.research.strategies import equity as E


@pytest.fixture
def bundle():
    dates = pd.bdate_range("2022-01-03", periods=120)
    tickers = [f"T{i}" for i in range(8)]
    prices = pd.DataFrame(100.0, index=dates, columns=tickers)
    vol = pd.DataFrame(1e6, index=dates, columns=tickers)
    return FeatureBundle("equity", prices, vol)


def _const(bundle, vals):
    """A dates x tickers frame, constant over time; tickers missing from vals = NaN."""
    return pd.DataFrame(
        {t: [vals.get(t, np.nan)] * len(bundle.dates) for t in bundle.tickers},
        index=bundle.dates)


def test_quality_momentum_requires_both_factors(bundle, monkeypatch):
    # quality (fund>0): T0,T1,T2,T5 ; momentum increases with index so top half = T4..T7
    fund = _const(bundle, {"T0": 1, "T1": 1, "T2": 1, "T5": 1})
    mom = _const(bundle, {t: i for i, t in enumerate(bundle.tickers)})
    monkeypatch.setattr(F, "beat_and_raise_frame", lambda b: fund)
    monkeypatch.setattr(F, "momentum", lambda px, n, *a, **k: mom)

    p = {"mom_lookback": 100, "mom_pctile": 0.5, "top_n": 8,
         "hold_days": 21, "volume_confirm": 0}
    w = E.quality_momentum_signal(bundle, p)
    held = set(w.columns[(w != 0).any()])
    # intersection of quality {T0,T1,T2,T5} and top-half momentum {T4,T5,T6,T7} = {T5}
    assert held == {"T5"}


def test_oversold_quality_requires_both_factors(bundle, monkeypatch):
    fund = _const(bundle, {"T0": 1, "T1": 1, "T6": 1})          # quality names
    z = _const(bundle, {"T0": -2.0, "T3": -2.0, "T6": -2.0})    # oversold names
    monkeypatch.setattr(F, "beat_and_raise_frame", lambda b: fund)
    monkeypatch.setattr(F, "zscore", lambda px, n: z)

    p = {"zlookback": 10, "entry_z": 1.0, "top_n": 8,
         "rebalance": 5, "uptrend_filter": 0}
    w = E.oversold_quality_signal(bundle, p)
    held = set(w.columns[(w != 0).any()])
    # oversold {T0,T3,T6} AND quality {T0,T1,T6} = {T0,T6}
    assert held == {"T0", "T6"}


def test_optional_third_factor_further_restricts(bundle, monkeypatch):
    fund = _const(bundle, {"T0": 1, "T1": 1, "T6": 1})
    z = _const(bundle, {"T0": -2.0, "T6": -2.0})
    monkeypatch.setattr(F, "beat_and_raise_frame", lambda b: fund)
    monkeypatch.setattr(F, "zscore", lambda px, n: z)
    # uptrend filter on: only T0 has a positive long-term trend
    monkeypatch.setattr(F, "momentum", lambda px, n, *a, **k: _const(bundle, {"T0": 1.0, "T6": -1.0}))

    base = {"zlookback": 10, "entry_z": 1.0, "top_n": 8, "rebalance": 5}
    held_2f = set((lambda w: w.columns[(w != 0).any()])(
        E.oversold_quality_signal(bundle, {**base, "uptrend_filter": 0})))
    held_3f = set((lambda w: w.columns[(w != 0).any()])(
        E.oversold_quality_signal(bundle, {**base, "uptrend_filter": 1})))
    assert held_2f == {"T0", "T6"}            # 2-factor: oversold quality
    assert held_3f == {"T0"}                  # 3rd factor drops the downtrending T6


def test_combination_families_registered():
    names = {sp.family for sp, _ in E.STRATEGIES}
    assert {"quality_momentum", "oversold_quality"} <= names


def test_combination_safe_without_fundamentals(bundle, monkeypatch):
    monkeypatch.setattr(F, "beat_and_raise_frame", lambda b: pd.DataFrame())
    w = E.quality_momentum_signal(bundle, {"mom_lookback": 100, "mom_pctile": 0.5,
                                           "top_n": 5, "hold_days": 21, "volume_confirm": 0})
    assert (w == 0).all().all() and list(w.columns) == bundle.tickers


def test_llm_proposer_sees_full_family_menu(tmp_db):
    """The LLM must be handed every family for the desk (so it can reach for
    combination / unpromoted ones), not just the incumbents in the population —
    and told which families have already promoted."""
    from quantzzz.config import load_config
    from quantzzz.data.features import FeatureBundle
    from quantzzz.research.loop import ResearchDesk
    from quantzzz.research.strategy_space import StrategySpec

    captured = {}

    class FakeLLM:
        available = True

        def propose_strategies(self, desk, leaderboard, param_spaces, search_context=None):
            captured["spaces"] = param_spaces
            captured["context"] = search_context
            return []

    dates = pd.bdate_range("2022-01-03", periods=40)
    prices = pd.DataFrame(100.0, index=dates, columns=["T0", "T1"])
    desk = ResearchDesk(load_config(), "equity", tmp_db,
                        FeatureBundle("equity", prices), llm=FakeLLM())
    desk._llm_proposals([(StrategySpec("momentum", "equity", {}), 1.0)])

    # the combination families must be in the menu the LLM receives
    assert {"quality_momentum", "oversold_quality"} <= set(captured["spaces"])
    # and the structure context distinguishes promoted from unexplored
    assert "promoted_families" in captured["context"]
    assert "unpromoted_families" in captured["context"]
    assert "quality_momentum" in captured["context"]["unpromoted_families"]


def test_short_term_reversal_longs_losers_and_filters_trend(bundle, monkeypatch):
    # short-horizon return: T0,T1 are the losers; everyone else is up
    short_ret = _const(bundle, {"T0": -0.10, "T1": -0.08, **{t: 0.05 for t in
                       ["T2", "T3", "T4", "T5", "T6", "T7"]}})
    long_trend = _const(bundle, {"T1": -1.0, **{t: 1.0 for t in
                        ["T0", "T2", "T3", "T4", "T5", "T6", "T7"]}})
    monkeypatch.setattr(F, "momentum", lambda px, n, *a, **k: short_ret if n <= 15 else long_trend)

    # no trend filter: the two biggest losers are the longs
    w = E.short_term_reversal_signal(bundle, {"lookback": 5, "top_n": 2,
                                              "rebalance": 2, "trend_filter": 0})
    assert set(w.columns[(w != 0).any()]) == {"T0", "T1"}

    # trend filter on: T1 is downtrending -> a falling knife, dropped; T0 kept
    w2 = E.short_term_reversal_signal(bundle, {"lookback": 5, "top_n": 2,
                                               "rebalance": 2, "trend_filter": 1})
    held = set(w2.columns[(w2 != 0).any()])
    assert "T0" in held and "T1" not in held
