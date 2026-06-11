"""Rate limiting and retry helpers for external APIs."""

from __future__ import annotations

import sqlite3
import time
from datetime import date


class RateLimiter:
    """Simple min-interval limiter: at most `calls_per` calls per `period_s`."""

    def __init__(self, calls_per: int, period_s: float):
        self.min_interval = period_s / max(calls_per, 1)
        self._last_call = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        delta = now - self._last_call
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last_call = time.monotonic()


class DailyBudget:
    """Persistent per-source daily call budget (survives restarts via SQLite)."""

    def __init__(self, conn: sqlite3.Connection, source: str, limit: int):
        self.conn = conn
        self.source = source
        self.limit = limit

    def used_today(self) -> int:
        row = self.conn.execute(
            "SELECT calls_used FROM api_budget WHERE source=? AND date=?",
            (self.source, date.today().isoformat()),
        ).fetchone()
        return row[0] if row else 0

    def remaining(self) -> int:
        return max(self.limit - self.used_today(), 0)

    def consume(self, n: int = 1) -> bool:
        """Reserve n calls; returns False if the budget is exhausted."""
        if self.remaining() < n:
            return False
        self.conn.execute(
            "INSERT INTO api_budget (source, date, calls_used) VALUES (?, ?, ?) "
            "ON CONFLICT(source, date) DO UPDATE SET calls_used = calls_used + ?",
            (self.source, date.today().isoformat(), n, n),
        )
        self.conn.commit()
        return True


def with_backoff(fn, retries: int = 3, base_delay: float = 2.0):
    """Call fn(); on exception retry with exponential backoff. Re-raises last error."""
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception:
            if attempt == retries:
                raise
            time.sleep(base_delay * (2 ** attempt))
