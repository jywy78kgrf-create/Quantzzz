import pytest

from quantzzz.config import RiskLimits
from quantzzz.trading.broker import Account, Order, Position
from quantzzz.trading.risk import RiskManager

LIMITS = RiskLimits(max_position_pct=0.08, max_gross_exposure=1.0, max_positions=5,
                    stop_loss_pct=0.10, drawdown_halt_pct=0.15, target_vol=0.15)


def _rm():
    return RiskManager(LIMITS)


def test_single_name_cap_resizes():
    acct = Account("equity", 1_000_000, 1_000_000)
    order = Order("equity", "AAA", "buy", 2000)  # 2000*100 = 200k = 20% > 8%
    v = _rm().check_entry(order, acct, [], price=100)
    assert v.decision == "resized"
    assert v.qty == pytest.approx(800)  # 8% of 1M / 100


def test_max_positions_rejects():
    acct = Account("equity", 1_000_000, 1_000_000)
    positions = [Position(f"P{i}", 10, 100) for i in range(5)]
    v = _rm().check_entry(Order("equity", "AAA", "buy", 10), acct, positions, 100)
    assert v.decision == "rejected"
    assert "max positions" in v.reason


def test_gross_exposure_cap_rejects():
    acct = Account("equity", 0, 1_000_000)
    # already fully invested at gross == equity
    positions = [Position("P0", 10000, 100)]  # 1,000,000 gross
    v = _rm().check_entry(Order("equity", "AAA", "buy", 10), acct, positions, 100)
    assert v.decision == "rejected"


def test_approved_within_limits():
    acct = Account("equity", 1_000_000, 1_000_000)
    v = _rm().check_entry(Order("equity", "AAA", "buy", 500), acct, [], 100)
    assert v.decision == "approved"


def test_stop_price():
    assert _rm().stop_price(100) == pytest.approx(90)


def test_drawdown_halt():
    rm = _rm()
    assert rm.drawdown_halted(-0.16)
    assert not rm.drawdown_halted(-0.10)
