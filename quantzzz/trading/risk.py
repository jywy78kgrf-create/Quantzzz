"""Risk manager: position/exposure caps, stops, and fund-level drawdown halt."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import RiskLimits
from .broker import Account, Order, Position


@dataclass
class RiskVerdict:
    decision: str          # approved | resized | rejected
    qty: float
    reason: str = ""


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check_entry(self, order: Order, account: Account, positions: list[Position],
                    price: float) -> RiskVerdict:
        if account.equity <= 0:
            return RiskVerdict("rejected", 0, "no equity")
        if len(positions) >= self.limits.max_positions:
            return RiskVerdict("rejected", 0, "max positions reached")

        qty = order.qty
        # single-name cap
        max_name_qty = (account.equity * self.limits.max_position_pct) / price
        if qty > max_name_qty:
            qty = max_name_qty
        # gross exposure cap
        gross = sum(abs(p.qty) * price for p in positions)  # approx with current price
        room = account.equity * self.limits.max_gross_exposure - gross
        if room <= 0:
            return RiskVerdict("rejected", 0, "gross exposure cap")
        max_by_gross = room / price
        if qty > max_by_gross:
            qty = max_by_gross

        if qty < 1e-6 or qty * price < 1:
            return RiskVerdict("rejected", 0, "sized below minimum")
        if qty < order.qty * 0.999:
            return RiskVerdict("resized", qty, "capped by risk limits")
        return RiskVerdict("approved", qty)

    def stop_price(self, entry_px: float, ticker_vol_annual: float | None = None) -> float:
        """Volatility-aware disaster stop.

        The configured stop_loss_pct is a FLOOR, not a target: strategies are
        validated holding through normal drawdowns, so the stop must sit beyond
        a typical month's noise (2.5x a 21-day vol move) or it converts dips
        into realized losses. Hard-capped at 35%.
        """
        import numpy as np
        pct = self.limits.stop_loss_pct
        if ticker_vol_annual and ticker_vol_annual > 0:
            monthly_move = 2.5 * (ticker_vol_annual / np.sqrt(252)) * np.sqrt(21)
            pct = min(max(pct, monthly_move), 0.35)
        return entry_px * (1 - pct)

    def drawdown_halted(self, drawdown: float) -> bool:
        return drawdown <= -self.limits.drawdown_halt_pct
