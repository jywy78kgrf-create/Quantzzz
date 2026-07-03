import pytest

from quantzzz.db import insert
from quantzzz.rebaseline import rebaseline


def test_rebaseline_rescales_hwm(tmp_db):
    """The high-water mark must rescale with the book, or drawdown compares two
    scales and reads a phantom crash that false-triggers the risk halts."""
    insert(tmp_db, "accounts", fund="biotech", cash=2_000_000,
           starting_cash=1_000_000, updated_ts="t")
    insert(tmp_db, "fund_state", fund="biotech", mode="normal", hwm=2_000_000)
    insert(tmp_db, "equity_snapshots", fund="biotech", ts="2026-06-12T00:00:00Z",
           equity=2_000_000, cash=2_000_000, gross_exposure=0.0, net_exposure=0.0,
           drawdown=0.0, source="live")

    rebaseline(tmp_db)            # f = 1,000,000 / 2,000,000 = 0.5

    hwm = tmp_db.execute("SELECT hwm FROM fund_state WHERE fund='biotech'").fetchone()["hwm"]
    eq = tmp_db.execute("SELECT equity FROM equity_snapshots WHERE fund='biotech' "
                        "ORDER BY id DESC LIMIT 1").fetchone()["equity"]
    assert hwm == pytest.approx(1_000_000)        # rescaled, not stuck at 2M
    assert eq == pytest.approx(1_000_000)
    # drawdown is now ~0, not the phantom -50% that would halt the fund
    assert abs((eq - hwm) / hwm) < 0.01
