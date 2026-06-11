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


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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

    def _get_csv(self, params: dict) -> list[dict]:
        """CSV endpoints (LISTING_STATUS, EARNINGS_CALENDAR) -> list of dicts."""
        import csv
        import io
        params = {**params, "apikey": self.cfg.alpha_vantage_key}
        self.limiter.wait()
        resp = with_backoff(lambda: requests.get(BASE_URL, params=params, timeout=60))
        resp.raise_for_status()
        text = resp.text
        if text.lstrip().startswith("{"):  # error payloads come back as JSON
            raise RuntimeError(f"alphavantage csv: {text[:200]}")
        return list(csv.DictReader(io.StringIO(text)))

    def listing_status(self, state: str = "delisted") -> list[dict]:
        """All active or delisted securities (symbol, exchange, ipo/delist dates)."""
        key = f"av:listing:{state}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                rows = self._get_csv({"function": "LISTING_STATUS", "state": state})
                self.cache.put(key, "alphavantage", rows, ttl_s=DAY_S * 7)
                return rows
            except Exception as e:
                self._health("error", None, f"listing_status: {e}"[:300])
        return self.cache.get(key, allow_stale=True) or []

    def earnings_calendar(self, horizon: str = "3month") -> list[dict]:
        """Upcoming earnings report dates with estimates for all symbols."""
        key = f"av:earnings_calendar:{horizon}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        if self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                rows = self._get_csv({"function": "EARNINGS_CALENDAR", "horizon": horizon})
                self.cache.put(key, "alphavantage", rows, ttl_s=DAY_S)
                return rows
            except Exception as e:
                self._health("error", None, f"earnings_calendar: {e}"[:300])
        return self.cache.get(key, allow_stale=True) or []

    # ---- premium feeds: earnings surprises, news sentiment, options ----
    def earnings_surprises(self, ticker: str) -> list[dict] | None:
        """Quarterly EPS actual-vs-estimate: [{reportedDate, surprisePct, ...}]."""
        key = f"av:earnings:{ticker}"
        data = self.cache.get(key)
        if data is None and self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({"function": "EARNINGS", "symbol": ticker})
                self.cache.put(key, "alphavantage", data, ttl_s=DAY_S * 3)
            except Exception as e:
                self._health("error", ticker, f"earnings: {e}"[:300])
                data = self.cache.get(key, allow_stale=True)
        if data is None:
            data = self.store.load_json(f"av_earnings/{ticker}.json")
            return data
        out = [
            {
                "reportedDate": q.get("reportedDate"),
                "fiscalDateEnding": q.get("fiscalDateEnding"),
                "reportedEPS": _f(q.get("reportedEPS")),
                "estimatedEPS": _f(q.get("estimatedEPS")),
                "surprisePct": _f(q.get("surprisePercentage")),
            }
            for q in data.get("quarterlyEarnings", [])
            if q.get("reportedDate") and q.get("surprisePercentage") not in (None, "None")
        ]
        if out:
            self.store.save_json(f"av_earnings/{ticker}.json", out)
        return out

    def news_sentiment(self, ticker: str, limit: int = 1000) -> list[dict] | None:
        """Recent news with per-ticker sentiment: [{date, sentiment, relevance}]."""
        key = f"av:news:{ticker}"
        data = self.cache.get(key)
        if data is None and self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({"function": "NEWS_SENTIMENT", "tickers": ticker,
                                  "limit": str(limit), "sort": "LATEST"})
                self.cache.put(key, "alphavantage", data, ttl_s=DAY_S)
            except Exception as e:
                self._health("error", ticker, f"news: {e}"[:300])
                data = self.cache.get(key, allow_stale=True)
        if data is None:
            return self.store.load_json(f"av_news/{ticker}.json")
        out = []
        for item in data.get("feed", []):
            ts = item.get("time_published", "")
            for s in item.get("ticker_sentiment", []):
                if s.get("ticker") == ticker:
                    out.append({
                        "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else None,
                        "sentiment": _f(s.get("ticker_sentiment_score")),
                        "relevance": _f(s.get("relevance_score")),
                    })
        out = [o for o in out if o["date"]]
        if out:
            self.store.save_json(f"av_news/{ticker}.json", out)
        return out

    def options_summary(self, ticker: str) -> dict | None:
        """Latest options chain summarized: put/call volume ratio, mean IV."""
        key = f"av:options:{ticker}"
        data = self.cache.get(key)
        if data is None and self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({"function": "HISTORICAL_OPTIONS", "symbol": ticker})
                self.cache.put(key, "alphavantage", data, ttl_s=DAY_S)
            except Exception as e:
                self._health("error", ticker, f"options: {e}"[:300])
                data = self.cache.get(key, allow_stale=True)
        if data is None:
            return self.store.load_json(f"av_options/{ticker}.json")
        rows = data.get("data", [])
        if not rows:
            return None
        call_vol = put_vol = 0.0
        ivs_c, ivs_p = [], []
        for r in rows:
            vol = _f(r.get("volume")) or 0
            iv = _f(r.get("implied_volatility"))
            if r.get("type") == "call":
                call_vol += vol
                if iv:
                    ivs_c.append(iv)
            else:
                put_vol += vol
                if iv:
                    ivs_p.append(iv)
        summary = {
            "date": rows[0].get("date"),
            "put_call_volume_ratio": round(put_vol / call_vol, 4) if call_vol else None,
            "mean_call_iv": round(sum(ivs_c) / len(ivs_c), 4) if ivs_c else None,
            "mean_put_iv": round(sum(ivs_p) / len(ivs_p), 4) if ivs_p else None,
            "total_volume": call_vol + put_vol,
            "n_contracts": len(rows),
        }
        # accumulate a history of daily summaries for future options strategies
        hist = self.store.load_json(f"av_options/{ticker}.json") or []
        if isinstance(hist, dict):
            hist = [hist]
        if not any(h.get("date") == summary["date"] for h in hist):
            hist.append(summary)
        self.store.save_json(f"av_options/{ticker}.json", hist[-500:])
        return summary

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
