from __future__ import annotations

import pandas as pd
import pytest

from quantzzz.cockpit import _forward_realized
from quantzzz.data.snapshots import SnapshotStore


def _add_trade(conn, ticker, qty, entry_px, exit_px, entry_ts, source="live"):
    conn.execute(
        "INSERT INTO trades (fund, ticker, entry_ts, exit_ts, entry_px, exit_px, "
        "qty, pnl, source) VALUES ('equity', ?, ?, '2026-06-15T00:00:00', ?, ?, ?, ?, ?)",
        (ticker, entry_ts, entry_px, exit_px, qty, (exit_px - entry_px) * qty, source),
    )
    conn.commit()


def test_forward_realized_rebases_carried_positions(tmp_db, tmp_path):
    store = SnapshotStore(tmp_path / "snaps")
    golive = "2026-06-12T00:00:00"
    # CARRIED: bought cheap in the backtest, already marked at go-live, sells flat.
    # Raw gain is huge ($872k) but the forward move is ~zero.
    idx = pd.bdate_range("2025-07-01", "2026-06-12")
    carried = pd.DataFrame(
        {"close": [109.0] * (len(idx) - 1) + [981.0], "volume": [1e6] * len(idx)},
        index=idx,
    )
    store.save_prices("MU", carried)
    _add_trade(tmp_db, "MU", 1000, 109.11, 981.12, "2025-07-22T00:00:00")
    # FORWARD: opened and closed after go-live -> counts in full.
    _add_trade(tmp_db, "NEW", 100, 50.0, 60.0, "2026-06-13T00:00:00")
    # REPLAY close: excluded entirely (source != live).
    _add_trade(tmp_db, "OLD", 100, 10.0, 90.0, "2025-01-01T00:00:00", source="replay")

    realized = _forward_realized(tmp_db, store, "equity", golive)

    # MU re-based to its go-live close (981.0): (981.12 - 981.0) * 1000 = 120
    # NEW counts in full: (60 - 50) * 100 = 1000
    # OLD (replay) excluded.
    assert realized == pytest.approx(120.0 + 1000.0)

    # the naive sum would wrongly include MU's $871,890 backtest run-up
    naive = tmp_db.execute(
        "SELECT COALESCE(SUM(pnl),0) FROM trades WHERE source='live' "
        "AND exit_ts IS NOT NULL"
    ).fetchone()[0]
    assert naive > 800_000  # demonstrates the contamination the rebase removes


def test_forward_realized_missing_mark_falls_back_to_entry(tmp_db, tmp_path):
    store = SnapshotStore(tmp_path / "snaps")   # no price files saved
    _add_trade(tmp_db, "GHOST", 10, 20.0, 30.0, "2025-01-01T00:00:00")
    realized = _forward_realized(tmp_db, store, "equity", "2026-06-12T00:00:00")
    # no go-live mark available -> degrade to raw entry basis, no crash
    assert realized == (30.0 - 20.0) * 10
