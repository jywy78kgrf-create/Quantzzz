"""Paper-trading broker: fills from latest quotes with a slippage model, full
cash/position ledger persisted in SQLite so state survives restarts."""

from __future__ import annotations

import sqlite3

from ..config import Config
from ..db import insert, utcnow
from .broker import Account, Broker, Fill, Order, Position


class PaperBroker(Broker):
    def __init__(self, cfg: Config, fund: str, conn: sqlite3.Connection, quote_fn):
        self.cfg = cfg
        self.fund = fund
        self.conn = conn
        self.quote_fn = quote_fn          # ticker -> latest price (or None)
        self._ensure_account()

    def _ensure_account(self) -> None:
        row = self.conn.execute(
            "SELECT fund FROM accounts WHERE fund=?", (self.fund,)).fetchone()
        if row is None:
            insert(self.conn, "accounts", fund=self.fund, cash=self.cfg.starting_cash,
                   starting_cash=self.cfg.starting_cash, updated_ts=utcnow())
            insert(self.conn, "fund_state", fund=self.fund, mode="normal",
                   hwm=self.cfg.starting_cash)

    # ---- account / positions ----
    def _cash(self) -> float:
        return self.conn.execute(
            "SELECT cash FROM accounts WHERE fund=?", (self.fund,)).fetchone()["cash"]

    def _set_cash(self, cash: float) -> None:
        self.conn.execute("UPDATE accounts SET cash=?, updated_ts=? WHERE fund=?",
                          (cash, utcnow(), self.fund))
        self.conn.commit()

    def get_positions(self) -> list[Position]:
        rows = self.conn.execute(
            "SELECT ticker, qty, avg_cost FROM positions WHERE fund=? AND qty != 0",
            (self.fund,)).fetchall()
        return [Position(r["ticker"], r["qty"], r["avg_cost"]) for r in rows]

    def _position(self, ticker: str) -> Position | None:
        r = self.conn.execute(
            "SELECT ticker, qty, avg_cost FROM positions WHERE fund=? AND ticker=?",
            (self.fund, ticker)).fetchone()
        return Position(r["ticker"], r["qty"], r["avg_cost"]) if r else None

    def get_account(self) -> Account:
        cash = self._cash()
        mkt = 0.0
        for pos in self.get_positions():
            px = self.quote_fn(pos.ticker) or pos.avg_cost
            mkt += pos.qty * px
        return Account(self.fund, cash, cash + mkt)

    # ---- execution ----
    def _slippage_price(self, px: float, side: str) -> tuple[float, float]:
        bps = self.cfg.slippage_bps
        signed = bps if side == "buy" else -bps
        return px * (1 + signed / 1e4), bps

    def submit_order(self, order: Order) -> Fill | None:
        px = self.quote_fn(order.ticker)
        if px is None or order.qty <= 0:
            self._record_order(order, "rejected", reason="no quote / zero qty")
            return None

        fill_px, slip = self._slippage_price(px, order.side)
        cost = fill_px * order.qty

        if order.side == "buy" and cost > self._cash() + 1e-6:
            self._record_order(order, "rejected", reason="insufficient cash")
            return None
        pos = self._position(order.ticker)
        if order.side == "sell" and (pos is None or pos.qty < order.qty - 1e-9):
            self._record_order(order, "rejected", reason="insufficient shares")
            return None

        order_id = self._record_order(order, "filled")
        insert(self.conn, "fills", order_id=order_id, ts=utcnow(), qty=order.qty,
               price=fill_px, slippage_bps=slip)
        self._apply_fill(order, fill_px)
        return Fill(order_id, order.ticker, order.qty, fill_px, slip)

    def _apply_fill(self, order: Order, fill_px: float) -> None:
        pos = self._position(order.ticker)
        cash = self._cash()
        if order.side == "buy":
            self._set_cash(cash - fill_px * order.qty)
            if pos is None:
                insert(self.conn, "positions", fund=self.fund, ticker=order.ticker,
                       qty=order.qty, avg_cost=fill_px, opened_ts=utcnow(),
                       strategy_id=order.strategy_id)
            else:
                new_qty = pos.qty + order.qty
                new_cost = (pos.avg_cost * pos.qty + fill_px * order.qty) / new_qty
                self.conn.execute(
                    "UPDATE positions SET qty=?, avg_cost=? WHERE fund=? AND ticker=?",
                    (new_qty, new_cost, self.fund, order.ticker))
        else:  # sell
            self._set_cash(cash + fill_px * order.qty)
            new_qty = (pos.qty if pos else 0) - order.qty
            if abs(new_qty) < 1e-9:
                self.conn.execute("DELETE FROM positions WHERE fund=? AND ticker=?",
                                  (self.fund, order.ticker))
            else:
                self.conn.execute(
                    "UPDATE positions SET qty=? WHERE fund=? AND ticker=?",
                    (new_qty, self.fund, order.ticker))
        self.conn.commit()

    def _record_order(self, order: Order, status: str, reason: str | None = None) -> int:
        return insert(self.conn, "orders", fund=self.fund, ts=utcnow(),
                      strategy_id=order.strategy_id, ticker=order.ticker,
                      side=order.side, qty=order.qty, order_type=order.order_type,
                      status=status, reject_reason=reason, journal_id=order.journal_id)

    def mark_to_market(self, quotes: dict[str, float]) -> None:
        acct = self.get_account()
        positions = self.get_positions()
        gross = sum(abs(p.qty) * (quotes.get(p.ticker) or p.avg_cost) for p in positions)
        net = sum(p.qty * (quotes.get(p.ticker) or p.avg_cost) for p in positions)
        state = self.conn.execute(
            "SELECT hwm FROM fund_state WHERE fund=?", (self.fund,)).fetchone()
        hwm = max(state["hwm"] if state else acct.equity, acct.equity)
        drawdown = 0.0 if hwm == 0 else (acct.equity - hwm) / hwm
        self.conn.execute("UPDATE fund_state SET hwm=? WHERE fund=?", (hwm, self.fund))
        insert(self.conn, "equity_snapshots", fund=self.fund, ts=utcnow(),
               equity=acct.equity, cash=acct.cash,
               gross_exposure=gross / acct.equity if acct.equity else 0,
               net_exposure=net / acct.equity if acct.equity else 0,
               drawdown=drawdown)
        self.conn.commit()
