"""Position sizing: volatility targeting and capped fractional Kelly."""

from __future__ import annotations


def vol_target_qty(equity: float, price: float, ticker_vol_annual: float,
                   target_vol: float, max_positions: int) -> float:
    """Shares for a per-name vol budget of target_vol / sqrt(max_positions).

    Imperfectly-correlated position vols add roughly in quadrature, so dividing
    the portfolio vol target linearly by position count under-deploys by ~4x at
    20 names; sqrt scaling targets the portfolio-level vol correctly.
    """
    if price <= 0 or ticker_vol_annual <= 0:
        return 0.0
    per_name_budget = target_vol / max(max_positions, 1) ** 0.5
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
    if hit_rate == 0:
        confidence = 0.5            # unproven strategy: half strength until trades close
    else:
        confidence = max(0.25, kelly / kelly_cap) if kelly_cap > 0 else 0.5
    qty = base * confidence * weight_multiplier
    # hard cap on single-name exposure
    max_qty = (equity * max_position_pct) / price if price > 0 else 0.0
    return max(0.0, min(qty, max_qty))
