"""Trader-agent smoke test: a promoted strategy produces a full order chain."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantzzz.config import load_config
from quantzzz.data.snapshots import SnapshotStore
from quantzzz.db import insert, utcnow
from quantzzz.trading.trader import TraderAgent


@pytest.fixture
def seeded(tmp_path, tmp_db, monkeypatch):
    """A snapshot dir with trending prices and one promoted momentum strategy."""
    snap = tmp_path / "snapshots"
    store = SnapshotStore(snap)
    dates = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(3)
    # build the equity universe tickers plus SPY benchmark with upward drift
    from quantzzz.universe import EQUITY_UNIVERSE
    for i, t in enumerate(EQUITY_UNIVERSE[:12] + ["SPY"]):
        drift = 0.001 if i % 2 == 0 else 0.0003
        rets = rng.normal(drift, 0.015, len(dates))
        close = 100 * np.cumprod(1 + rets)
        store.save_prices(t, pd.DataFrame(
            {"close": close, "raw_close": close, "volume": 1e6}, index=dates))

    insert(tmp_db, "strategies", desk="equity", family="momentum",
           params_json='{"lookback": 60, "rebalance": 5, "skip": 0, "top_n": 4, "vol_filter": 0.0}',
           spec_hash="testmom", status="promoted", origin="random", created_ts=utcnow())

    import dataclasses
    cfg = dataclasses.replace(load_config(), snapshot_dir=snap)
    return cfg, tmp_db


def test_trader_session_produces_orders(seeded):
    cfg, conn = seeded
    agent = TraderAgent(cfg, "equity", conn)
    report = agent.session()
    assert "equity" in report
    n_orders = conn.execute("SELECT COUNT(*) c FROM orders WHERE fund='equity'").fetchone()["c"]
    assert n_orders >= 1
    n_journal = conn.execute(
        "SELECT COUNT(*) c FROM journal_entries WHERE fund='equity' AND entry_type='entry'"
    ).fetchone()["c"]
    assert n_journal >= 1


def test_replay_timestamps_use_as_of(seeded):
    cfg, conn = seeded
    agent = TraderAgent(cfg, "equity", conn)
    as_of = pd.Timestamp("2024-01-15")
    agent.session(as_of=as_of)
    row = conn.execute(
        "SELECT ts FROM equity_snapshots WHERE fund='equity' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["ts"].startswith("2024-01-15")


def test_source_tags_split_replay_from_live(seeded):
    """Replayed sessions must never count toward the forward (live) record."""
    cfg, conn = seeded
    agent = TraderAgent(cfg, "equity", conn)
    agent.session(as_of=pd.Timestamp("2024-01-15"))   # replayed history
    agent.session()                                    # real-time session
    rows = conn.execute(
        "SELECT source, COUNT(*) c FROM equity_snapshots WHERE fund='equity' "
        "GROUP BY source ORDER BY source").fetchall()
    counts = {r["source"]: r["c"] for r in rows}
    assert counts.get("replay", 0) >= 1 and counts.get("live", 0) >= 1
    # every backdated snapshot is replay; every current-time one is live
    mismatch = conn.execute(
        "SELECT COUNT(*) c FROM equity_snapshots WHERE fund='equity' AND "
        "((ts LIKE '2024-01-15%' AND source != 'replay') OR "
        " (ts NOT LIKE '2024-01-15%' AND source != 'live'))").fetchone()["c"]
    assert mismatch == 0
    trade_srcs = {r["source"] for r in conn.execute(
        "SELECT source FROM trades WHERE fund='equity'")}
    assert trade_srcs <= {"replay", "live"}


def test_shadow_marking_forward_only(seeded):
    """Live sessions mark shadow NAV once per market day; replays never do."""
    from quantzzz.db import insert as _insert
    cfg, conn = seeded
    _insert(conn, "shadow_book", strategy_id=1, fund="equity",
            registered_ts=utcnow(), expected_oos_sharpe=2.0, expected_dsr=0.7,
            status="active", note="test trial")
    agent = TraderAgent(cfg, "equity", conn)

    agent.session(as_of=pd.Timestamp("2024-01-15"))     # replay: must not mark
    assert conn.execute("SELECT COUNT(*) c FROM shadow_nav").fetchone()["c"] == 0

    agent.session()                                     # live: marks
    agent.session()                                     # same market day: no dup
    rows = conn.execute("SELECT nav FROM shadow_nav WHERE shadow_id=1").fetchall()
    assert len(rows) == 1 and rows[0]["nav"] > 0
    w = conn.execute("SELECT last_weights_json FROM shadow_book WHERE id=1"
                     ).fetchone()["last_weights_json"]
    assert w is not None                                # pinned spec produced targets
