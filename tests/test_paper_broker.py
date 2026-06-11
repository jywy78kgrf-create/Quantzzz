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
