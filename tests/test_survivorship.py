import json

import pandas as pd

from quantzzz.config import load_config
from quantzzz.universe import EQUITY_UNIVERSE, research_universe_for, universe_for


def test_research_universe_includes_delisted(tmp_path):
    snap = tmp_path
    (snap / "delisted.json").write_text(json.dumps(
        [{"ticker": "DEADCO", "name": "Dead Co", "delistingDate": "2022-01-01",
          "ipoDate": "1990-01-01"}]))
    research = research_universe_for("equity", snap)
    live = universe_for("equity", snap)
    assert "DEADCO" in research
    assert "DEADCO" not in live
    assert set(live).issubset(set(research))


def test_real_delisted_pool_in_research_universe():
    cfg = load_config()
    research = research_universe_for("equity", cfg.snapshot_dir)
    extra = set(research) - set(EQUITY_UNIVERSE)
    # the committed snapshot bundle ships a real survivorship pool
    assert len(extra) >= 20


def test_trader_universe_stays_live_only():
    cfg = load_config()
    live = universe_for("equity", cfg.snapshot_dir)
    assert set(live) == set(EQUITY_UNIVERSE)


def test_earnings_blackout_logic(tmp_path, tmp_db):
    import dataclasses
    import numpy as np
    from quantzzz.data.snapshots import SnapshotStore
    from quantzzz.trading.trader import TraderAgent

    snap = tmp_path / "snapshots"
    store = SnapshotStore(snap)
    dates = pd.bdate_range("2024-01-01", periods=300)
    close = 100 * np.cumprod(1 + np.random.default_rng(0).normal(0.001, 0.01, 300))
    store.save_prices("AAPL", pd.DataFrame(
        {"close": close, "raw_close": close, "volume": 1e6}, index=dates))
    store.save_json("av_earnings_calendar.json",
                    [{"ticker": "AAPL", "reportDate": "2025-03-05", "estimate": "2.0"}])

    cfg = dataclasses.replace(load_config(), snapshot_dir=snap)
    agent = TraderAgent(cfg, "equity", tmp_db)
    agent.as_of = pd.Timestamp("2025-03-03")     # 2 days before report
    assert agent._in_earnings_blackout("AAPL") is not None
    agent.as_of = pd.Timestamp("2025-02-10")     # well before
    assert agent._in_earnings_blackout("AAPL") is None
    agent.as_of = pd.Timestamp("2025-03-06")     # after report
    assert agent._in_earnings_blackout("AAPL") is None


def test_biotech_research_universe_includes_dead_biotechs(tmp_path):
    import json
    from quantzzz.universe import research_universe_for

    (tmp_path / "delisted_biotech.json").write_text(json.dumps(
        [{"ticker": "CLVS", "name": "Clovis Oncology", "exit": "bankruptcy 2022"}]))
    uni = research_universe_for("biotech", tmp_path)
    assert "CLVS" in uni
    # live universe unaffected when the pool file is absent
    assert "CLVS" not in research_universe_for("biotech", tmp_path / "nope")


def test_biotech_universe_widens_to_catalyst_tickers_with_prices(tmp_path):
    import csv
    from quantzzz.universe import research_universe_for
    (tmp_path / "external").mkdir(parents=True)
    (tmp_path / "prices").mkdir()
    # two catalyst tickers; only AAA has a price file
    with (tmp_path / "external" / "catalyst_events_export.csv").open("w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["event_id", "ticker", "catalyst_date"])
        w.writerow([1, "AAA", "2026-03-01"]); w.writerow([2, "ZZZ", "2026-04-01"])
    (tmp_path / "prices" / "AAA.parquet").write_bytes(b"x")
    uni = research_universe_for("biotech", tmp_path)
    assert "AAA" in uni                 # catalyst ticker with price -> included
    assert "ZZZ" not in uni             # catalyst ticker without price -> excluded
