"""Guards on the options-history backfill: it must skip chains already on disk
without re-fetching, and it must yield on its wall-clock budget so it never runs
into the cycle's CI timeout and gets cancelled mid-write."""

import dataclasses

import pandas as pd

from quantzzz.config import load_config
from quantzzz.data import external_refresh
from quantzzz.data.alphavantage import AlphaVantageClient
from quantzzz.data.snapshots import SnapshotStore


def _setup(tmp_path):
    snap = tmp_path / "snapshots"
    store = SnapshotStore(snap)
    dates = pd.bdate_range("2026-05-04", periods=20)
    store.save_prices("XBI", pd.DataFrame(
        {"close": 100.0, "raw_close": 100.0, "volume": 1e6}, index=dates))
    store.save_json("bpiq/universe.json", ["AAA", "BBB"])
    newest = [str(d.date()) for d in dates[-2:]]
    # AAA already holds the two newest days; BBB holds nothing
    store.save_json("av_options/AAA.json", [{"date": d} for d in newest])
    cfg = dataclasses.replace(load_config(), snapshot_dir=snap,
                              alpha_vantage_key="test")
    return cfg, newest


def test_backfill_skips_existing_chains_without_refetch(tmp_path, tmp_db, monkeypatch):
    cfg, newest = _setup(tmp_path)
    calls = []

    def fake_summary(self, t, day):
        calls.append((t, day))
        return True

    monkeypatch.setattr(AlphaVantageClient, "options_summary_on", fake_summary)
    res = external_refresh.backfill_options_history(
        cfg, tmp_db, max_calls=1000, since="2026-05-04")

    # days AAA already has on disk are never re-fetched
    assert ("AAA", newest[0]) not in calls
    assert ("AAA", newest[1]) not in calls
    # BBB has no chains, so its missing days are fetched
    assert ("BBB", newest[0]) in calls
    assert res["status"] == "gap filled"


def test_backfill_yields_on_time_budget(tmp_path, tmp_db, monkeypatch):
    cfg, _ = _setup(tmp_path)
    monkeypatch.setattr(AlphaVantageClient, "options_summary_on",
                        lambda self, t, day: True)
    # zero budget -> must return immediately rather than walk the calendar
    res = external_refresh.backfill_options_history(
        cfg, tmp_db, max_calls=10_000, since="2026-05-04", max_seconds=0)
    assert res["status"] == "time budget reached; resumes next cycle"
    assert res["calls"] == 0
