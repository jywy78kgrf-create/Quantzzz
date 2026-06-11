"""Position sizing: volatility targeting and capped fractional Kelly."""

from __future__ import annotations


def vol_target_qty(equity: float, price: float, ticker_vol_annual: float,
                   target_vol: float, max_positions: int) -> float:
    """Shares so the position's standalone vol ≈ target_vol / max_positions of equity."""
    if price <= 0 or ticker_vol_annual <= 0:
        return 0.0
    per_name_budget = target_vol / max(max_positions, 1)
    dollar_alloc = equity * (per_name_budget / ticker_vol_annual)
    return dollar_alloc / price


def kelly_fraction(hit_rate: float, payoff: float, cap: float = 0.25) -> float:
    """Fractional Kelly f* = p - (1-p)/b, floored at 0 and capped."""
    if payoff <= 0:
        return 0.0
    f = hit_rate - (1 - hit_rate) / payoff
    return max(0.0, min(cap, f))


def final_qty(equity: float, price: float, ticker_vol_annual: float, target_vol: float,
              max_positions: int, hit_rate: float, payoff: float,
              weight_multiplier: float, kelly_cap: float, max_position_pct: float) -> float:
    """Combine vol-target and Kelly, apply the learned multiplier and the hard cap."""
    base = vol_target_qty(equity, price, ticker_vol_annual, target_vol, max_positions)
    kelly = kelly_fraction(hit_rate, payoff, kelly_cap)
    # scale the vol-target size by Kelly confidence (0.5 baseline when no history)
    confidence = kelly / kelly_cap if kelly_cap > 0 else 0.5
    confidence = max(0.25, confidence) if hit_rate == 0 else confidence
    qty = base * confidence * weight_multiplier
    # hard cap on single-name exposure
    max_qty = (equity * max_position_pct) / price if price > 0 else 0.0
    return max(0.0, min(qty, max_qty))
