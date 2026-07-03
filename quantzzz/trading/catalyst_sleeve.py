"""Event-driven catalyst sleeve — a discrete per-event trader that runs in
tandem with the continuous-rebalance portfolio trader.

Why a separate subsystem: the portfolio trader tracks a target weight vector and
rebalances every session, which washes out the catalyst edge. That edge is a
per-event drift — enter ~T-60 before a binary readout, EXIT at ~T-1 before it
resolves — captured only by discrete, event-timed positions. This sleeve trades
exactly that, on its own isolated paper book (``fund='biotech_catalyst'``), one
position per qualifying event, gated on E1 (top-quintile 180d run-up) and
optionally E2 (volume confirmation). It writes per-event closed trades and its
own equity snapshots, so the forward record is the referee here too. The
portfolio trader never sees these positions.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import Config
from ..db import insert, utcnow
from .broker import Order
from .paper_broker import PaperBroker

FUND = "biotech_catalyst"


class CatalystSleeve:
    def __init__(self, cfg: Config, conn: sqlite3.Connection, *,
                 entry_days_before: int = 84,    # ~60 trading days
                 exit_days_before: int = 2,      # ~1 trading day: out before the readout
                 momentum_lookback_days: int = 180,
                 momentum_min: float = 0.40,     # E1: top-quintile 180d run-up bar
                 vol_ratio_min: float = 1.39,    # E2: 63d/252d volume confirmation
                 require_volume: bool = True,
                 price_floor: float = 10.0,      # validated rule: price >= $10 at entry
                 # validated catalyst-type filter (Replit disclosure: "PDUFA /
                 # Phase 2 / Phase 3 only"); excludes the vague "Other" bucket
                 # and early-stage Phase 1. None = trade every type.
                 catalyst_types=("PDUFA", "Phase3", "Phase2", "Phase2/3"),
                 max_positions: int = 12,
                 store=None, events: pd.DataFrame | None = None):
        self.cfg = cfg
        self.conn = conn
        self.entry_days = entry_days_before
        self.exit_days = exit_days_before
        self.lookback_days = momentum_lookback_days
        self.mom_min = momentum_min
        self.vol_min = vol_ratio_min
        self.require_volume = require_volume
        self.price_floor = price_floor
        self.catalyst_types = frozenset(catalyst_types) if catalyst_types else None
        self.max_positions = max_positions
        if store is None:
            from ..data.snapshots import SnapshotStore
            store = SnapshotStore(cfg.snapshot_dir)
        self.store = store
        if events is None:
            from ..data.external_signals import load_external_signals
            sig = load_external_signals(cfg.snapshot_dir)
            events = sig.events if sig is not None else pd.DataFrame()
        self.events = events if events is not None else pd.DataFrame()
        self._px_cache: dict = {}
        self.broker = PaperBroker(cfg, FUND, conn, self._quote)
        self._strategy_id = self._ensure_strategy()

    # ---- data ----
    def _prices(self, ticker: str):
        if ticker not in self._px_cache:
            self._px_cache[ticker] = self.store.load_prices(ticker)
        return self._px_cache[ticker]

    def _quote(self, ticker: str):
        df = self._prices(ticker)
        if df is None or not len(df):
            return None
        day = getattr(self, "_asof", None)
        s = df["close"] if day is None else df.loc[df.index <= day, "close"]
        return float(s.iloc[-1]) if len(s) else None

    def _momentum(self, ticker: str, day: pd.Timestamp):
        df = self._prices(ticker)
        if df is None or not len(df):
            return None
        now = df.loc[df.index <= day, "close"]
        past = df.loc[df.index <= day - pd.Timedelta(days=self.lookback_days), "close"]
        if len(now) < 5 or len(past) < 5 or past.iloc[-1] <= 0:
            return None
        return float(now.iloc[-1] / past.iloc[-1] - 1)

    def _vol_ratio(self, ticker: str, day: pd.Timestamp):
        df = self._prices(ticker)
        if df is None or "volume" not in df:
            return None
        v = df.loc[df.index <= day, "volume"]
        if len(v) < 252:
            return None
        long = v.iloc[-252:].mean()
        return float(v.iloc[-63:].mean() / long) if long else None

    def _ensure_strategy(self) -> int:
        row = self.conn.execute(
            "SELECT id FROM strategies WHERE spec_hash='catalyst_event_sleeve'").fetchone()
        if row:
            return row["id"]
        return insert(self.conn, "strategies", desk="biotech_catalyst", family="catalyst_event",
                      params_json="{}", spec_hash="catalyst_event_sleeve",
                      status="promoted", origin="external", created_ts=utcnow(),
                      promoted_ts=utcnow(), forward_verified=0)

    # ---- session ----
    def _market_date(self):
        df = self.store.load_prices("XBI")    # benchmark = market-day reference
        return df.index[-1].date().isoformat() if df is not None and len(df) else None

    def session(self, as_of=None) -> str:
        if as_of is not None:
            today = pd.Timestamp(as_of).normalize()
            self.broker.session_ts = today.strftime("%Y-%m-%dT00:00:00Z")
            self.broker.session_source = "replay"
        else:
            today = pd.Timestamp.now("UTC").tz_localize(None).normalize()
            # skip a forward session on days with no new market data (weekend/holiday)
            md = self._market_date()
            last = self.conn.execute(
                "SELECT last_session_price_date FROM fund_state WHERE fund=?", (FUND,)).fetchone()
            if md is not None and last and last["last_session_price_date"] == md:
                return f"catalyst sleeve: no new market data since {md} (market closed) — skipped"
            self.broker.session_ts = utcnow()
            self.broker.session_source = "live"
        self._asof = today              # quotes/marks are as-of the session date

        n_exit = self._do_exits(today)
        n_enter = self._do_entries(today)

        quotes = {p.ticker: self._quote(p.ticker) for p in self.broker.get_positions()}
        self.broker.mark_to_market({k: v for k, v in quotes.items() if v is not None},
                                   ts=self.broker.session_ts)
        if as_of is None:
            md = self._market_date()
            if md:
                self.conn.execute("UPDATE fund_state SET last_session_price_date=? WHERE fund=?",
                                  (md, FUND))
        self.conn.commit()
        return (f"catalyst sleeve: {n_enter} entered, {n_exit} exited, "
                f"{len(self.broker.get_positions())} open")

    def _do_exits(self, today: pd.Timestamp) -> int:
        n = 0
        rows = self.conn.execute(
            "SELECT * FROM catalyst_sleeve WHERE fund=?", (FUND,)).fetchall()
        for r in rows:
            cat = pd.Timestamp(r["catalyst_date"])
            if today >= cat - pd.Timedelta(days=self.exit_days):
                reason = "pre-catalyst exit" if today < cat else "catalyst passed"
                self._exit(r, reason)
                n += 1
        return n

    def _do_entries(self, today: pd.Timestamp) -> int:
        if self.events is None or not len(self.events):
            return 0
        held = {r["ticker"] for r in self.conn.execute(
            "SELECT ticker FROM catalyst_sleeve WHERE fund=?", (FUND,))}
        slots = self.max_positions - len(held)
        if slots <= 0:
            return 0
        ev = self.events.dropna(subset=["catalyst_date"]).copy()
        if self.catalyst_types is not None and "catalyst_type" in ev:
            ev = ev[ev["catalyst_type"].isin(self.catalyst_types)]
        ev["catalyst_date"] = pd.to_datetime(ev["catalyst_date"], errors="coerce")
        ev = ev[(ev["catalyst_date"] - pd.Timedelta(days=self.entry_days) <= today)
                & (today <= ev["catalyst_date"] - pd.Timedelta(days=self.exit_days))]
        ev = ev[~ev["ticker"].isin(held)]
        ev = ev.sort_values("catalyst_date").drop_duplicates("ticker", keep="first")
        cands = []
        for _, e in ev.iterrows():
            px = self._quote(e["ticker"])
            if px is None or px < self.price_floor:   # validated $10 floor at entry
                continue
            mom = self._momentum(e["ticker"], today)
            if mom is None or mom < self.mom_min:
                continue
            if self.require_volume:
                vr = self._vol_ratio(e["ticker"], today)
                if vr is None or vr < self.vol_min:
                    continue
            cands.append((e, mom))
        cands.sort(key=lambda x: -x[1])         # strongest run-up first
        n = 0
        for e, mom in cands[:slots]:
            if self._enter(e, mom):
                n += 1
        return n

    def _enter(self, e, mom: float) -> bool:
        ticker = e["ticker"]
        px = self._quote(ticker)
        if px is None or px <= 0:
            return False
        equity = self.broker.get_account().equity
        qty = (equity / self.max_positions) / px
        if qty <= 0:
            return False
        fill = self.broker.submit_order(
            Order(FUND, ticker, "buy", qty, strategy_id=self._strategy_id))
        if fill is None:
            return False
        insert(self.conn, "catalyst_sleeve", fund=FUND, ticker=ticker,
               event_id=str(e.get("event_id") or ""), catalyst_type=e.get("catalyst_type"),
               catalyst_date=str(pd.Timestamp(e["catalyst_date"]).date()),
               entry_ts=self.broker.session_ts, entry_px=fill.price, qty=fill.qty,
               runup_180d=round(float(mom), 4))
        return True

    def _exit(self, r, reason: str) -> None:
        held = self.broker._position(r["ticker"])
        sell_qty = min(r["qty"], held.qty) if held else 0.0
        if sell_qty <= 0:
            # position already gone (closed elsewhere / orphaned) — just untrack
            self.conn.execute("DELETE FROM catalyst_sleeve WHERE id=?", (r["id"],))
            return
        fill = self.broker.submit_order(
            Order(FUND, r["ticker"], "sell", sell_qty, strategy_id=self._strategy_id))
        if fill is None:
            return    # couldn't sell (no quote / halt) — keep tracking, retry next session
        pnl = (fill.price - r["entry_px"]) * fill.qty
        pnl_pct = (fill.price / r["entry_px"] - 1) if r["entry_px"] else 0.0
        insert(self.conn, "trades", fund=FUND, strategy_id=self._strategy_id,
               ticker=r["ticker"], entry_ts=r["entry_ts"], exit_ts=self.broker.session_ts,
               entry_px=r["entry_px"], exit_px=fill.price, qty=fill.qty, pnl=pnl,
               pnl_pct=pnl_pct, exit_reason=reason, source=self.broker.session_source)
        self.conn.execute("DELETE FROM catalyst_sleeve WHERE id=?", (r["id"],))
