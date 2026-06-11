"""Broker abstraction. PaperBroker is the only reachable implementation unless
real trading is explicitly enabled (LIVE_TRADING=true AND a broker key present)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Order:
    fund: str
    ticker: str
    side: str          # buy | sell
    qty: float
    strategy_id: int | None = None
    order_type: str = "market"
    journal_id: int | None = None


@dataclass
class Fill:
    order_id: int
    ticker: str
    qty: float
    price: float
    slippage_bps: float


@dataclass
class Position:
    ticker: str
    qty: float
    avg_cost: float


@dataclass
class Account:
    fund: str
    cash: float
    equity: float


class Broker(ABC):
    @abstractmethod
    def submit_order(self, order: Order) -> Fill | None: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def mark_to_market(self, quotes: dict[str, float]) -> None: ...


def make_broker(cfg, fund: str, conn, quote_fn):
    """Factory enforcing the live-trading safety gate."""
    from .paper_broker import PaperBroker
    if cfg.live_trading and cfg.alpaca_api_key and cfg.alpaca_api_secret:
        from .live_broker import AlpacaBroker  # pragma: no cover
        return AlpacaBroker(cfg, fund, conn, quote_fn)
    return PaperBroker(cfg, fund, conn, quote_fn)
