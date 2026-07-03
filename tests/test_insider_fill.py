"""The Form-4 insider fetch must merge into the EDGAR files non-destructively,
skip names that already carry the key (no re-fetch), respect the per-cycle
limit, and leave the fundamentals the working families read untouched."""

import dataclasses

from quantzzz.config import load_config
from quantzzz.data import refresh as R
from quantzzz.data.edgar import EdgarClient
from quantzzz.data.snapshots import SnapshotStore


def _cfg(tmp_path):
    return dataclasses.replace(load_config(), snapshot_dir=tmp_path,
                               db_path=tmp_path / "t.db",
                               edgar_user_agent="test agent x@y.z")


def test_insider_fill_merges_without_clobbering_fundamentals(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    # an existing fundamentals file with NO insider key (the real-world state)
    store.save_json("edgar/AAA.json",
                    {"ticker": "AAA", "cik": "1", "eps": [{"end": "2025-12-31"}],
                     "revenue": [], "cash": [], "op_cash_flow": []})

    sample = [{"filed": "2026-01-05", "code": "P", "shares": 100.0, "value": 5000.0}]
    monkeypatch.setattr(EdgarClient, "insider_transactions",
                        lambda self, t, **k: sample)

    res = R._edgar_insider_fill(_cfg(tmp_path), store, ["AAA"], limit=12)
    out = store.load_json("edgar/AAA.json")
    assert out["insider"] == sample            # key added
    assert out["eps"] == [{"end": "2025-12-31"}]  # fundamentals preserved
    assert out["ticker"] == "AAA"
    assert "1 names" in res and "1 insider txns" in res


def test_insider_fill_skips_already_populated_and_missing(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    store.save_json("edgar/HAVE.json", {"ticker": "HAVE", "insider": []})
    # NONE.json deliberately absent

    calls = []
    monkeypatch.setattr(EdgarClient, "insider_transactions",
                        lambda self, t, **k: calls.append(t) or [])

    res = R._edgar_insider_fill(_cfg(tmp_path), store, ["HAVE", "NONE"], limit=12)
    assert calls == []                         # neither fetched
    assert "0 names" in res


def test_insider_fill_respects_limit(tmp_path, monkeypatch):
    store = SnapshotStore(tmp_path)
    for t in ["A", "B", "C", "D"]:
        store.save_json(f"edgar/{t}.json", {"ticker": t})
    calls = []
    monkeypatch.setattr(EdgarClient, "insider_transactions",
                        lambda self, t, **k: calls.append(t) or [])

    R._edgar_insider_fill(_cfg(tmp_path), store, ["A", "B", "C", "D"], limit=2)
    assert len(calls) == 2                      # capped per cycle
