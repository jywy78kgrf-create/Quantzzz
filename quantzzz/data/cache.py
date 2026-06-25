"""SQLite-backed payload cache with per-entry TTL."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import utcnow


class Cache:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, key: str, allow_stale: bool = False):
        row = self.conn.execute(
            "SELECT payload, fetched_at, ttl_s FROM api_cache WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return None
        payload, fetched_at, ttl_s = row["payload"], row["fetched_at"], row["ttl_s"]
        if not allow_stale:
            expires = datetime.fromisoformat(fetched_at) + timedelta(seconds=ttl_s)
            if datetime.now(timezone.utc) > expires:
                return None
        return json.loads(payload)

    def put(self, key: str, source: str, payload, ttl_s: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO api_cache (key, source, fetched_at, ttl_s, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, source, utcnow(), ttl_s, json.dumps(payload)),
        )
        self.conn.commit()

    def get_or_fetch(self, key: str, source: str, ttl_s: int, fetch_fn):
        """Fresh cache hit, else fetch; on fetch failure fall back to stale cache."""
        hit = self.get(key)
        if hit is not None:
            return hit
        try:
            payload = fetch_fn()
        except Exception:
            stale = self.get(key, allow_stale=True)
            if stale is not None:
                return stale
            raise
        if payload is not None:
            self.put(key, source, payload, ttl_s)
        return payload
