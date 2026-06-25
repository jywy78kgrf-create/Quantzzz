"""BPIQ biotech catalyst data provider.

Live-first against the BPIQ REST API (https://api.bpiq.com/api/v1/info/, Token
auth), with JSON snapshots in data/snapshots/bpiq/ as the offline fallback. The
biotech universe is derived from the all-companies screener.
"""

from __future__ import annotations

import sqlite3

import requests

from ..config import Config
from .cache import Cache
from .ratelimit import RateLimiter, with_backoff
from .snapshots import SnapshotStore

BASE_URL = "https://api.bpiq.com/api/v1/info"
DAY_S = 24 * 3600


class BpiqProvider:
    def __init__(self, cfg: Config, conn: sqlite3.Connection, store: SnapshotStore):
        self.cfg = cfg
        self.cache = Cache(conn)
        self.store = store
        self.headers = {
            "Authorization": f"Token {cfg.bpiq_api_key}",
            "Accept": "application/json",
        }
        self.limiter = RateLimiter(calls_per=4, period_s=1)

    def _paged(self, endpoint: str, params: dict | None = None, max_items: int = 1000) -> list[dict]:
        """Walk the paginated `results` list up to max_items."""
        out: list[dict] = []
        url = f"{BASE_URL}/{endpoint}"
        params = {**(params or {}), "limit": 250}
        while url and len(out) < max_items:
            self.limiter.wait()
            resp = with_backoff(
                lambda: requests.get(url, headers=self.headers, params=params, timeout=30)
            )
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("results", []))
            url = data.get("next")
            params = None  # `next` already carries query params
        return out[:max_items]

    def _live_or_snapshot(self, snap_name: str, endpoint: str,
                          params: dict | None = None, max_items: int = 1000) -> list[dict]:
        relpath = f"bpiq/{snap_name}.json"
        if self.cfg.bpiq_api_key:
            try:
                data = self._paged(endpoint, params, max_items)
                if data:
                    self.store.save_json(relpath, data)
                    return data
            except Exception:
                pass
        snap = self.store.load_json(relpath)
        return snap or []

    # ---- public surface ----
    def companies(self) -> list[dict]:
        return self._live_or_snapshot("companies", "all-companies/")

    def catalysts(self) -> list[dict]:
        return self._live_or_snapshot("catalysts", "catalysts/")

    def pdufa_catalysts(self) -> list[dict]:
        """PDUFA / regulatory-decision catalysts, filtered from the calendar."""
        out = []
        for c in self.catalysts():
            label = ((c.get("stage_event") or {}).get("event_label") or "").lower()
            stage = ((c.get("stage_event") or {}).get("stage_label") or "").lower()
            if "pdufa" in label or "pdufa" in stage or "fda decision" in label:
                out.append(c)
        return out

    def historical_catalysts(self, ticker: str) -> list[dict]:
        return self._live_or_snapshot(
            f"hist_{ticker}", "historical-catalysts/", {"ticker": ticker}, max_items=250
        )

    def universe(self, min_market_cap: float = 5e7, max_market_cap: float = 5e10,
                 limit: int = 60) -> list[str]:
        """Biotech tickers with catalyst relevance, sized small/mid cap."""
        companies = self.companies()
        catalyst_tickers = {c.get("ticker") for c in self.catalysts() if c.get("ticker")}
        scored = []
        for c in companies:
            tk = c.get("ticker")
            mc = c.get("market_cap") or 0
            if not tk or "." in tk:  # skip foreign-listed dual tickers
                continue
            if not (min_market_cap <= mc <= max_market_cap):
                continue
            has_cat = tk in catalyst_tickers
            scored.append((has_cat, mc, tk))
        # prefer names with upcoming catalysts, then larger (more liquid) caps
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        tickers = [tk for _, _, tk in scored][:limit]
        if tickers:
            self.store.save_json("bpiq/universe.json", tickers)
        return tickers
