"""Live broker adapter stub (e.g. Alpaca).

Intentionally unimplemented. Reaching this class requires LIVE_TRADING=true AND
broker credentials — the make_broker factory routes to PaperBroker otherwise.
Implement submit_order/get_positions/get_account/mark_to_market against the
broker REST API to go live, keeping the same Broker interface.
"""

from __future__ import annotations

from .broker import Account, Broker, Fill, Order, Position


class AlpacaBroker(Broker):
    def __init__(self, cfg, fund, conn, quote_fn):
        raise NotImplementedError(
            "Live trading adapter is not implemented. Set LIVE_TRADING=false to use "
            "the paper broker, or implement AlpacaBroker against your broker API."
        )

    def submit_order(self, order: Order) -> Fill | None: ...
    def get_positions(self) -> list[Position]: ...
    def get_account(self) -> Account: ...
    def mark_to_market(self, quotes: dict[str, float]) -> None: ...
