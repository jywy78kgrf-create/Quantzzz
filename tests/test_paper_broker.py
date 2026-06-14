import pytest

from quantzzz.config import load_config
from quantzzz.trading.broker import Order
from quantzzz.trading.paper_broker import PaperBroker


@pytest.fixture
def broker(tmp_db):
    cfg = load_config()
    quotes = {"AAA": 100.0, "BBB": 50.0}
    return PaperBroker(cfg, "equity", tmp_db, lambda t: quotes.get(t))


def test_buy_then_account_conserved(broker):
    start = broker.get_account().equity
    fill = broker.submit_order(Order("equity", "AAA", "buy", 100))
    assert fill is not None
    acct = broker.get_account()
    # equity changes only by slippage cost (fill above mid)
    assert acct.equity == pytest.approx(start - fill.qty * (fill.price - 100.0), abs=1e-6)
    assert acct.cash == pytest.approx(start - fill.price * 100)


def test_sell_realizes_cash(broker):
    broker.submit_order(Order("equity", "AAA", "buy", 100))
    cash_after_buy = broker.get_account().cash
    broker.submit_order(Order("equity", "AAA", "sell", 100))
    assert broker.get_account().cash > cash_after_buy
    assert broker.get_positions() == []


def test_reject_insufficient_cash(broker):
    fill = broker.submit_order(Order("equity", "AAA", "buy", 1_000_000))
    assert fill is None


def test_reject_oversell(broker):
    broker.submit_order(Order("equity", "AAA", "buy", 10))
    assert broker.submit_order(Order("equity", "AAA", "sell", 50)) is None


def test_reject_no_quote(broker):
    assert broker.submit_order(Order("equity", "ZZZ", "buy", 10)) is None


def test_avg_cost_updates_on_add(broker):
    broker.submit_order(Order("equity", "AAA", "buy", 100))
    broker.submit_order(Order("equity", "AAA", "buy", 100))
    pos = broker.get_positions()[0]
    assert pos.qty == 200
    assert pos.avg_cost == pytest.approx(100 * (1 + 5 / 1e4))  # both filled with buy slippage


def test_mark_to_market_writes_snapshot(broker, tmp_db):
    broker.submit_order(Order("equity", "AAA", "buy", 100))
    broker.mark_to_market({"AAA": 110.0})
    row = tmp_db.execute("SELECT equity, drawdown FROM equity_snapshots ORDER BY id DESC LIMIT 1").fetchone()
    assert row["equity"] > 0


def test_zero_quote_honored_not_masked_at_cost(tmp_db):
    from quantzzz.config import load_config
    px = {"AAA": 100.0}
    b = PaperBroker(load_config(), "equity", tmp_db, lambda t: px.get(t))
    b.submit_order(Order("equity", "AAA", "buy", 100))
    cash = b.get_account().cash
    px["AAA"] = 0.0                       # the name wipes out to a real zero
    # position now worth 0, NOT marked back at cost
    assert b.get_account().equity == pytest.approx(cash)


def test_replay_does_not_ratchet_hwm(tmp_db):
    from quantzzz.config import load_config
    px = {"AAA": 100.0}
    b = PaperBroker(load_config(), "equity", tmp_db, lambda t: px.get(t))
    b.submit_order(Order("equity", "AAA", "buy", 100))
    b.session_source = "replay"
    b.mark_to_market({"AAA": 300.0})     # a hindsight replay peak
    hwm = tmp_db.execute("SELECT hwm FROM fund_state WHERE fund='equity'").fetchone()["hwm"]
    assert hwm == pytest.approx(1_000_000)   # replay never moves the live high-water mark


def test_flat_live_book_resets_hwm_so_it_can_recover(tmp_db):
    from quantzzz.config import load_config
    b = PaperBroker(load_config(), "equity", tmp_db, lambda t: None)
    # a crashed-then-liquidated fund: stale high peak, now flat with less cash
    tmp_db.execute("UPDATE accounts SET cash=600000 WHERE fund='equity'")
    tmp_db.execute("UPDATE fund_state SET hwm=1000000 WHERE fund='equity'")
    tmp_db.commit()
    b.session_source = "live"
    b.mark_to_market({})                  # flat: no positions
    fs = tmp_db.execute("SELECT hwm FROM fund_state WHERE fund='equity'").fetchone()
    snap = tmp_db.execute("SELECT drawdown FROM equity_snapshots WHERE fund='equity' "
                          "ORDER BY id DESC LIMIT 1").fetchone()
    assert fs["hwm"] == pytest.approx(600000)   # reset to cash, not pinned at the old peak
    assert abs(snap["drawdown"]) < 1e-9         # drawdown heals -> liquidate_only can recover
