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

    def daily_adjusted(self, ticker: str, force: bool = False) -> pd.DataFrame | None:
        """Full adjusted daily history. Cache (1 day TTL) -> network -> snapshot.
        force=True skips the cache read to pull a just-finalized bar (post-close
        EOD refresh), then overwrites the cache with the fresh series."""
        key = f"av:daily:{ticker}"
        cached = self.cache.get(key)
        if cached is not None and not force:
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
        rows = {}
        for date, v in series.items():
            raw_close = float(v["4. close"])
            adj_close = float(v["5. adjusted close"])
            f = adj_close / raw_close if raw_close else 1.0
            rows[date] = {
                "close": adj_close,
                "raw_close": raw_close,
                "open": float(v["1. open"]) * f,
                "high": float(v["2. high"]) * f,
                "low": float(v["3. low"]) * f,
                "volume": float(v["6. volume"]),
            }
        df = pd.DataFrame.from_dict(rows, orient="index")
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def index_data(self, symbol: str) -> pd.DataFrame | None:
        """Daily OHLC for a market index (VIX, VIX3M, SKEW, ...) via INDEX_DATA.

        Indices aren't equities, so TIME_SERIES doesn't serve them — this is the
        volatility-regime data path. Stored as a price series (close only; no
        splits/dividends/volume) so it rides the existing snapshot infra and the
        regime feature can read it with load_prices. Same cache -> network ->
        snapshot fallback as daily_adjusted; a failure (e.g. the key tier not
        serving INDEX_DATA) is logged to data_health and degrades to None, which
        the observe-only regime feature treats as 'no signal' — never an error."""
        key = f"av:index:{symbol}"
        cached = self.cache.get(key)
        if cached is not None:
            return self._parse_index(cached)
        if self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({
                    "function": "INDEX_DATA",
                    "symbol": symbol,
                    "interval": "daily",
                })
                self.cache.put(key, "alphavantage", data, ttl_s=DAY_S)
                df = self._parse_index(data)
                if df is not None:
                    self.store.save_prices(symbol, df)
                    self._health("ok", symbol, f"index history {len(df)} rows")
                return df
            except Exception as e:
                self._health("error", symbol, str(e)[:300])
        else:
            self._health("budget_exhausted", symbol, "using snapshot")
        snap = self.store.load_prices(symbol)
        if snap is not None:
            return snap
        stale = self.cache.get(key, allow_stale=True)
        return self._parse_index(stale) if stale is not None else None

    @staticmethod
    def _parse_index(data: dict) -> pd.DataFrame | None:
        rows_in = data.get("data")
        if not rows_in:
            return None
        rows = {}
        for r in rows_in:
            d, c = r.get("date"), r.get("close")
            if not d or c in (None, ""):
                continue
            close = float(c)
            rows[d] = {
                "close": close, "raw_close": close,   # indices: no splits/divs
                "open": float(r.get("open") or close),
                "high": float(r.get("high") or close),
                "low": float(r.get("low") or close),
                "volume": 0.0,
            }
        if not rows:
            return None
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
        spot = None
        px = self.store.load_prices(ticker)
        if px is not None and len(px):
            spot = float(px["raw_close"].iloc[-1] if "raw_close" in px.columns
                         else px["close"].iloc[-1])
        summary = summarize_chain(rows, spot)
        # accumulate a history of daily summaries for future options strategies
        hist = self.store.load_json(f"av_options/{ticker}.json") or []
        if isinstance(hist, dict):
            hist = [hist]
        if not any(h.get("date") == summary["date"] for h in hist):
            hist.append(summary)
        hist.sort(key=lambda h: h.get("date") or "")
        self.store.save_json(f"av_options/{ticker}.json", hist[-4000:])
        return summary

    def options_summary_on(self, ticker: str, date: str) -> dict | None:
        """Vendor-grade chain summary for a specific historical date (premium
        HISTORICAL_OPTIONS supports per-date queries). Cached permanently —
        a historical chain never changes."""
        key = f"av:options:{ticker}:{date}"
        data = self.cache.get(key)
        if data is None and self.cfg.alpha_vantage_key and self.budget.consume():
            try:
                data = self._get({"function": "HISTORICAL_OPTIONS",
                                  "symbol": ticker, "date": date})
                self.cache.put(key, "alphavantage", data, ttl_s=365 * DAY_S)
            except Exception as e:
                self._health("error", ticker, f"options@{date}: {e}"[:300])
                return None
        if not data:
            return None
        rows = data.get("data", [])
        if not rows:
            return None
        spot = None
        px = self.store.load_prices(ticker)
        if px is not None and len(px):
            asof = px.loc[px.index <= date]
            if len(asof):
                spot = float(asof["raw_close"].iloc[-1]
                             if "raw_close" in asof.columns else asof["close"].iloc[-1])
        summary = summarize_chain(rows, spot)
        if summary is None:
            return None
        hist = self.store.load_json(f"av_options/{ticker}.json") or []
        if isinstance(hist, dict):
            hist = [hist]
        if not any(h.get("date") == summary["date"] for h in hist):
            hist.append(summary)
            hist.sort(key=lambda h: h.get("date") or "")
            self.store.save_json(f"av_options/{ticker}.json", hist[-4000:])
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


def summarize_chain(rows: list[dict], spot: float | None) -> dict | None:
    """Vendor-grade daily options summary from a full chain.

    Computes a true ATM 30-day-tenor IV (per-expiry ATM strike, linear
    interpolation across the two expiries bracketing 30 calendar days), a true
    25-delta risk reversal (call IV at delta closest to +0.25 minus put IV at
    delta closest to -0.25, on the expiry nearest 30d), open-interest totals
    and ratios — replacing the earlier chain-mean approximations. Falls back
    gracefully when the chain is too thin or spot is unknown.
    """
    if not rows:
        return None
    obs_date = rows[0].get("date")
    call_vol = put_vol = call_oi = put_oi = 0.0
    by_exp: dict[str, list[dict]] = {}
    for r in rows:
        vol = _f(r.get("volume")) or 0.0
        oi = _f(r.get("open_interest")) or 0.0
        if r.get("type") == "call":
            call_vol += vol
            call_oi += oi
        else:
            put_vol += vol
            put_oi += oi
        if r.get("expiration"):
            by_exp.setdefault(r["expiration"], []).append(r)

    def _dte(exp: str) -> float:
        import datetime as _dt
        try:
            return ((_dt.date.fromisoformat(exp)
                     - _dt.date.fromisoformat(obs_date)).days)
        except (ValueError, TypeError):
            return -1.0

    def _atm_iv(contracts: list[dict]) -> float | None:
        if spot is None:
            return None
        best, best_d = [], None
        for r in contracts:
            k, iv = _f(r.get("strike")), _f(r.get("implied_volatility"))
            if k is None or not iv:
                continue
            d = abs(k - spot)
            if best_d is None or d < best_d - 1e-9:
                best, best_d = [iv], d
            elif abs(d - best_d) <= 1e-9:
                best.append(iv)
        return sum(best) / len(best) if best else None

    def _tenor_iv(target_days: float) -> float | None:
        pts = []
        for exp, contracts in by_exp.items():
            dte = _dte(exp)
            if dte < 3:
                continue
            iv = _atm_iv(contracts)
            if iv:
                pts.append((dte, iv))
        if not pts:
            return None
        pts.sort()
        lo = [p for p in pts if p[0] <= target_days]
        hi = [p for p in pts if p[0] >= target_days]
        if lo and hi and lo[-1][0] != hi[0][0]:
            (d0, v0), (d1, v1) = lo[-1], hi[0]
            w = (target_days - d0) / (d1 - d0)
            return v0 + w * (v1 - v0)
        return (hi[0][1] if hi else lo[-1][1])

    def _rr_25d() -> float | None:
        # the expiry nearest 30d with usable deltas
        cand = sorted(((abs(_dte(e) - 30), e) for e in by_exp if _dte(e) >= 3))
        for _, exp in cand[:3]:
            c_best = p_best = None
            c_gap = p_gap = None
            for r in by_exp[exp]:
                iv, dl = _f(r.get("implied_volatility")), _f(r.get("delta"))
                if not iv or dl is None:
                    continue
                if r.get("type") == "call":
                    g = abs(dl - 0.25)
                    if c_gap is None or g < c_gap:
                        c_best, c_gap = iv, g
                else:
                    g = abs(dl + 0.25)
                    if p_gap is None or g < p_gap:
                        p_best, p_gap = iv, g
            if (c_best is not None and p_best is not None
                    and c_gap is not None and c_gap < 0.15
                    and p_gap is not None and p_gap < 0.15):
                return c_best - p_best
        return None

    iv30 = _tenor_iv(30)
    iv180 = _tenor_iv(180)
    rr = _rr_25d()
    return {
        "date": obs_date,
        "put_call_volume_ratio": round(put_vol / call_vol, 4) if call_vol else None,
        "put_call_oi_ratio": round(put_oi / call_oi, 4) if call_oi else None,
        "total_open_interest": call_oi + put_oi,
        "atm_iv_30d": round(iv30, 4) if iv30 else None,
        "atm_iv_180d": round(iv180, 4) if iv180 else None,
        "iv_term_structure_30_180": (round(iv30 / iv180, 4)
                                     if iv30 and iv180 else None),
        "rr_25d": round(rr, 4) if rr is not None else None,
        "total_volume": call_vol + put_vol,
        "n_contracts": len(rows),
    }
