import pytest

from quantzzz.trading import sizing


def test_kelly_zero_when_no_edge():
    # hit_rate 0.5 with payoff 1 -> f = 0.5 - 0.5/1 = 0
    assert sizing.kelly_fraction(0.5, 1.0) == pytest.approx(0.0)


def test_kelly_zero_below_breakeven():
    assert sizing.kelly_fraction(0.3, 1.0) == 0.0


def test_kelly_capped():
    # very high edge would exceed cap
    assert sizing.kelly_fraction(0.9, 5.0, cap=0.25) == 0.25


def test_kelly_zero_payoff():
    assert sizing.kelly_fraction(0.6, 0.0) == 0.0


def test_vol_target_scales_inverse_with_vol():
    low = sizing.vol_target_qty(1_000_000, 100, 0.2, 0.15, 10)
    high = sizing.vol_target_qty(1_000_000, 100, 0.6, 0.15, 10)
    assert low > high  # lower-vol name gets a larger position


def test_final_qty_respects_position_cap():
    qty = sizing.final_qty(
        equity=1_000_000, price=10, ticker_vol_annual=0.1, target_vol=0.15,
        max_positions=5, hit_rate=0.9, payoff=5.0, weight_multiplier=2.0,
        kelly_cap=0.25, max_position_pct=0.05)
    # cap = 5% of 1M / $10 = 5000 shares
    assert qty <= 5000 + 1e-6


def test_final_qty_zero_price():
    assert sizing.final_qty(1_000_000, 0, 0.2, 0.15, 5, 0.6, 2.0, 1.0, 0.25, 0.05) == 0.0
