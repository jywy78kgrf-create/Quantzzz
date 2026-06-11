"""End-to-end smoke tests on synthetic data with the network fully disabled."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantzzz.config import load_config
from quantzzz.data.features import FeatureBundle
from quantzzz.research.loop import ResearchDesk


@pytest.fixture
def synthetic_bundle():
    dates = pd.bdate_range("2021-01-04", periods=600)
    tickers = [f"T{i}" for i in range(12)]
    rng = np.random.default_rng(7)
    rets = rng.normal(0.0004, 0.02, size=(len(dates), len(tickers)))
    prices = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=dates, columns=tickers)
    vol = pd.DataFrame(1e6, index=dates, columns=tickers)
    return FeatureBundle("equity", prices, vol)


def test_research_iterations_persist(tmp_db, synthetic_bundle, monkeypatch):
    cfg = load_config()
    desk = ResearchDesk(cfg, "equity", tmp_db, synthetic_bundle, llm=None)
    # benchmark from the bundle itself (no snapshot/network needed)
    monkeypatch.setattr(desk, "_benchmark_returns",
                        lambda store: synthetic_bundle.prices.mean(axis=1).pct_change())
    result = desk.run(8)
    assert result.iterations == 8
    n = tmp_db.execute("SELECT COUNT(*) c FROM research_iterations").fetchone()["c"]
    assert n >= 1


def test_research_runs_recorded(tmp_db, synthetic_bundle, monkeypatch):
    cfg = load_config()
    desk = ResearchDesk(cfg, "equity", tmp_db, synthetic_bundle, llm=None)
    monkeypatch.setattr(desk, "_benchmark_returns",
                        lambda store: synthetic_bundle.prices.mean(axis=1).pct_change())
    desk.run(5)
    run = tmp_db.execute("SELECT ended_ts, iterations FROM research_runs").fetchone()
    assert run["ended_ts"] is not None
    assert run["iterations"] == 5
