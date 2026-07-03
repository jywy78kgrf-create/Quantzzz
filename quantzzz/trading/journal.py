"""Structured decision journal — the 'why' behind every trader action."""

from __future__ import annotations

import sqlite3

from ..db import dumps, insert, utcnow


class DecisionJournal:
    def __init__(self, conn: sqlite3.Connection, fund: str):
        self.conn = conn
        self.fund = fund

    def record(self, entry_type: str, reasoning: str, *, ticker: str | None = None,
               action: str | None = None, inputs: dict | None = None,
               ref_table: str | None = None, ref_id: int | None = None) -> int:
        return insert(self.conn, "journal_entries", fund=self.fund, ts=utcnow(),
                      entry_type=entry_type, ticker=ticker, action=action,
                      inputs_json=dumps(inputs or {}), reasoning=reasoning,
                      ref_table=ref_table, ref_id=ref_id)
