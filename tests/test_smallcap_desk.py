"""The biotech_smallcap sub-desk: sub-$10 + liquidity-filtered universe, biotech
families reused, its own risk/promotion config, survivorship-honest research set."""

import numpy as np
import pandas as pd

from quantzzz.config import BENCHMARKS, FUNDS, RISK_LIMITS, load_config
from quantzzz.data.snapshots import SnapshotStore
from quantzzz.research.strategies import families_for
from quantzzz.universe import research_universe_for, universe_for


def _save(store, sym, price, volume, fresh=True):
    end = pd.Timestamp(pd.Timestamp.now("UTC").date()) if fresh else pd.Timestamp("2024-01-01")
    idx = pd.bdate_range(end=end, periods=70)
    close = np.full(70, float(price))
    store.save_prices(sym, pd.DataFrame(
        {"close": close, "raw_close": close, "volume": float(volume)}, index=idx))


def test_smallcap_universe_filters_price_and_liquidity(tmp_path):
    store = SnapshotStore(tmp_path)
    (tmp_path / "bpiq").mkdir(parents=True, exist_ok=True)
    (tmp_path / "bpiq" / "universe.json").write_text('["AAA","BBB","CCC","DDD"]')
    _save(store, "AAA", price=5.0, volume=100_000)    # <$10, $500k/day -> keep
    _save(store, "BBB", price=50.0, volume=100_000)   # >$10 -> drop
    _save(store, "CCC", price=5.0, volume=1_000)      # <$10 but $5k/day -> drop (thin)
    _save(store, "DDD", price=8.0, volume=50_000)     # <$10, $400k/day -> keep

    live = universe_for("biotech_smallcap", tmp_path)
    assert set(live) == {"AAA", "DDD"}


def test_smallcap_research_universe_is_survivorship_subset(tmp_path):
    # research universe should be the sub-$10 filter applied to the FULL biotech
    # research set (live + dead + catalyst), so it never silently excludes
    # failed sub-$10 names — just verify it returns a subset of biotech research.
    store = SnapshotStore(tmp_path)
    (tmp_path / "bpiq").mkdir(parents=True, exist_ok=True)
    (tmp_path / "bpiq" / "universe.json").write_text('["AAA","BBB"]')
    _save(store, "AAA", price=4.0, volume=200_000)
    _save(store, "BBB", price=80.0, volume=200_000)
    research = research_universe_for("biotech_smallcap", tmp_path)
    full_bio = research_universe_for("biotech", tmp_path)
    assert set(research).issubset(set(full_bio))
    assert "AAA" in research and "BBB" not in research   # price band enforced


def test_smallcap_reuses_biotech_families():
    assert set(families_for("biotech_smallcap")) == set(families_for("biotech"))
    assert "options_iv_runup" in families_for("biotech_smallcap")


def test_smallcap_desk_wired_in_config():
    assert "biotech_smallcap" in FUNDS
    assert BENCHMARKS["biotech_smallcap"] == "XBI"
    assert RISK_LIMITS["biotech_smallcap"].max_position_pct == 0.04
    cfg = load_config()
    assert cfg.risk_limits("biotech_smallcap").max_positions == 20
    assert cfg.promotion_for("biotech_smallcap").min_trades == 25
