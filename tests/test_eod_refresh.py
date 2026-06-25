"""Post-close forced price refresh: force=True bypasses the 24h cache to pull a
just-finalized bar, but stays idempotent — a ticker that already holds today's
date is not re-fetched."""

import dataclasses

import pandas as pd

from quantzzz.config import load_config
from quantzzz.data import refresh as R
from quantzzz.data.alphavantage import AlphaVantageClient
from quantzzz.data.snapshots import SnapshotStore


def test_force_refresh_is_idempotent_on_todays_bar(tmp_path, tmp_db, monkeypatch):
    store = SnapshotStore(tmp_path)
    today = pd.Timestamp(pd.Timestamp.now("UTC").date())
    fresh = pd.DatetimeIndex([today - pd.Timedelta(days=i) for i in range(4, -1, -1)])
    stale = pd.DatetimeIndex([today - pd.Timedelta(days=i) for i in range(12, 7, -1)])
    for sym, idx in [("FRESH", fresh), ("STALE", stale)]:
        store.save_prices(sym, pd.DataFrame(
            {"close": 100.0, "raw_close": 100.0, "volume": 1e6}, index=idx))

    calls = []

    def fake_daily(self, ticker, force=False):
        calls.append((ticker, force))
        return pd.DataFrame({"close": [1.0], "raw_close": [1.0], "volume": [1.0]},
                            index=[today])

    monkeypatch.setattr(AlphaVantageClient, "daily_adjusted", fake_daily)
    cfg = dataclasses.replace(load_config(), snapshot_dir=tmp_path, alpha_vantage_key="x")

    R.refresh_prices(cfg, ["FRESH", "STALE"], tmp_db, force=True)
    fetched = {t for t, _ in calls}
    assert "STALE" in fetched              # missing today's bar -> force-fetched
    assert "FRESH" not in fetched          # already has today -> skipped (idempotent)
    assert all(f is True for _, f in calls)  # force flag propagated to the client


def test_held_marks_only_refreshes_stale_held(tmp_path, tmp_db, monkeypatch):
    """refresh_held_marks force-refreshes only held names behind the bench's
    latest close — not held names already current, not unheld names."""
    store = SnapshotStore(tmp_path)
    today = pd.Timestamp(pd.Timestamp.now("UTC").date())

    def save(sym, last):
        idx = pd.DatetimeIndex([last - pd.Timedelta(days=i) for i in range(4, -1, -1)])
        store.save_prices(sym, pd.DataFrame(
            {"close": 100.0, "raw_close": 100.0, "volume": 1e6}, index=idx))

    save("SPY", today)                              # bench current
    save("HELDCUR", today)                          # held, already current
    save("HELDSTALE", today - pd.Timedelta(days=5))  # held, behind the bench
    for t in ("HELDCUR", "HELDSTALE"):
        tmp_db.execute("INSERT INTO positions (fund,ticker,qty,avg_cost,opened_ts) "
                       "VALUES (?,?,?,?,?)", ("equity", t, 10.0, 100.0, "2026-01-01"))
    tmp_db.commit()

    calls = []
    monkeypatch.setattr(AlphaVantageClient, "daily_adjusted",
                        lambda self, t, force=False: (calls.append((t, force)) or
                        pd.DataFrame({"close": [1.0], "raw_close": [1.0], "volume": [1.0]},
                                     index=[today])))
    cfg = dataclasses.replace(load_config(), snapshot_dir=tmp_path, alpha_vantage_key="x")
    res = R.refresh_held_marks(cfg, tmp_db, store, ["equity"], "SPY")
    fetched = {t for t, _ in calls}
    assert "HELDSTALE" in fetched and "HELDCUR" not in fetched
    assert res["held"] == 2 and res["stale"] == 1
