"""Alpha Vantage client: cache-first, budget-aware, snapshot fallback.

The API tier is unknown, so every network call goes through a persisted daily
budget. Daily history is cached for a full trading day and mirrored into the
parquet snapshot bundle so backtests never need the network.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import requests

from ..config import Config
from ..db import insert, utcnow
from .cache import Cache
from .ratelimit import DailyBudget, RateLimiter, with_backoff
from .snapshots import SnapshotStore

BASE_URL = "https://www.alphavantage.co/query"
DAY_S = 24 * 3600


class AlphaVantageClient:
    def __init__(self, cfg: Config, conn: sqlite3.Connection, store: SnapshotStore):
        self.cfg = cfg
        self.conn = conn
        self.cache = Cache(conn)
        self.store = store
        self.limiter = RateLimiter(calls_per=cfg.av_calls_per_min, period_s=60)
        self.budget = DailyBudget(conn, "alphavantage", cfg.av_daily_budget)

    def _health(self, status: str, ticker: str | None, detail: str) -> None:
        insert(self.conn, "data_health", ts=utcnow(), source="alphavantage",
               ticker=ticker, status=status, detail=detail)

    def _get(self, params: dict) -> dict:
        params = {**params, "apikey": self.cfg.alpha_vantage_key}
        self.limiter.wait()
        resp = with_backoff(lambda: requests.get(BASE_URL, params=params, timeout=30))
        resp.raise_for_status()
        data = resp.json()
        # AV returns 200 with an error/limit message body instead of HTTP errors
        for bad_key in ("Error Message", "Information", "Note"):
            if bad_key in data:
                raise RuntimeError(f"alphavantage: {data[bad_key][:200]}")
        return data

    def daily_adjusted(self, ticker: str) -> pd.DataFrame | None:
        """Full adjusted daily history. Cache (1 day TTL) -> network -> snapshot."""
        key = f"av:daily:{ticker}"
        cached = self.cache.get(key)
        if cached is not None:
            return self._parse_daily(cached)

        if self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({
                    "function": "TIME_SERIES_DAILY_ADJUSTED",
                    "symbol": ticker,
                    "outputsize": "full",
                })
                self.cache.put(key, "alphavantage", data, ttl_s=DAY_S)
                df = self._parse_daily(data)
                if df is not None:
                    self.store.save_prices(ticker, df)
                    self._health("ok", ticker, f"daily history {len(df)} rows")
                return df
            except Exception as e:  # fall through to snapshot
                self._health("error", ticker, str(e)[:300])
        else:
            self._health("budget_exhausted", ticker, "using snapshot")

        snap = self.store.load_prices(ticker)
        if snap is not None:
            return snap
        stale = self.cache.get(key, allow_stale=True)
        return self._parse_daily(stale) if stale is not None else None

    @staticmethod
    def _parse_daily(data: dict) -> pd.DataFrame | None:
        series = data.get("Time Series (Daily)")
        if not series:
            return None
        rows = {
            date: {
                "close": float(v["5. adjusted close"]),
                "raw_close": float(v["4. close"]),
                "volume": float(v["6. volume"]),
            }
            for date, v in series.items()
        }
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def latest_quote(self, ticker: str) -> float | None:
        """Latest price: short-TTL quote cache -> network -> last snapshot close."""
        key = f"av:quote:{ticker}"
        cached = self.cache.get(key)
        if cached is not None:
            return float(cached["price"])

        if self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({"function": "GLOBAL_QUOTE", "symbol": ticker})
                px = float(data["Global Quote"]["05. price"])
                self.cache.put(key, "alphavantage", {"price": px}, ttl_s=900)
                return px
            except Exception as e:
                self._health("error", ticker, str(e)[:300])

        snap = self.store.load_prices(ticker)
        if snap is not None and len(snap):
            return float(snap["close"].iloc[-1])
        return None
