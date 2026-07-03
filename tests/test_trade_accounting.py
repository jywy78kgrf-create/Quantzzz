"""The learning loop reads CLOSED trades to promote/retire/graduate strategies,
so every realized sell — partial trims included — must land in the trade record
against the position's average cost. These lock that in."""

import pytest

from quantzzz.db import insert
from quantzzz.trading.trader import TraderAgent


class _Stub:
    """Minimal object exposing just the trade-accounting helpers on a tmp db."""
    def __init__(self, conn):
        self.fund = "equity"
        self.conn = conn

    def _ts(self):
        return "2026-06-14T00:00:00Z"

    def _source(self):
        return "live"

    _open_trade_row = TraderAgent._open_trade_row
    _record_buy = TraderAgent._record_buy
    _realize_sell = TraderAgent._realize_sell


@pytest.fixture
def stub(tmp_db):
    insert(tmp_db, "accounts", fund="equity", cash=1_000_000,
           starting_cash=1_000_000, updated_ts="t")
    return _Stub(tmp_db)


def test_scale_in_keeps_open_lot_in_sync(stub, tmp_db):
    insert(tmp_db, "positions", fund="equity", ticker="AAA", qty=100, avg_cost=10.0,
           opened_ts="t", strategy_id=7)
    stub._record_buy("AAA", 7)
    tmp_db.execute("UPDATE positions SET qty=150, avg_cost=12.0 WHERE ticker='AAA'")
    tmp_db.commit()
    stub._record_buy("AAA", 7)                      # scale-in
    row = tmp_db.execute("SELECT qty, entry_px FROM trades WHERE ticker='AAA' "
                         "AND exit_ts IS NULL").fetchone()
    assert row["qty"] == pytest.approx(150)          # not the stale 100
    assert row["entry_px"] == pytest.approx(12.0)    # blended avg cost


def test_partial_trim_books_realized_pnl(stub, tmp_db):
    insert(tmp_db, "positions", fund="equity", ticker="AAA", qty=150, avg_cost=12.0,
           opened_ts="t", strategy_id=7)
    stub._record_buy("AAA", 7)
    tmp_db.execute("UPDATE positions SET qty=100 WHERE ticker='AAA'")   # broker sold 50
    tmp_db.commit()
    stub._realize_sell("AAA", 50, 20.0, "trim")
    closed = tmp_db.execute("SELECT qty, pnl FROM trades WHERE ticker='AAA' "
                            "AND exit_ts IS NOT NULL").fetchone()
    assert closed is not None                        # the trim is recorded (was previously invisible)
    assert closed["qty"] == pytest.approx(50)
    assert closed["pnl"] == pytest.approx((20.0 - 12.0) * 50)
    remaining = tmp_db.execute("SELECT qty FROM trades WHERE ticker='AAA' "
                               "AND exit_ts IS NULL").fetchone()
    assert remaining["qty"] == pytest.approx(100)    # open lot shrank by the trimmed qty


def test_full_close_after_trim_leaves_two_closed_rows(stub, tmp_db):
    insert(tmp_db, "positions", fund="equity", ticker="AAA", qty=150, avg_cost=12.0,
           opened_ts="t", strategy_id=7)
    stub._record_buy("AAA", 7)
    tmp_db.execute("UPDATE positions SET qty=100 WHERE ticker='AAA'"); tmp_db.commit()
    stub._realize_sell("AAA", 50, 20.0, "trim")
    tmp_db.execute("UPDATE positions SET qty=0 WHERE ticker='AAA'"); tmp_db.commit()
    stub._realize_sell("AAA", 100, 15.0, "close")
    n_open = tmp_db.execute("SELECT COUNT(*) FROM trades WHERE ticker='AAA' "
                            "AND exit_ts IS NULL").fetchone()[0]
    n_closed = tmp_db.execute("SELECT COUNT(*) FROM trades WHERE ticker='AAA' "
                              "AND exit_ts IS NOT NULL").fetchone()[0]
    assert n_open == 0
    assert n_closed == 2                              # the trim and the final close
