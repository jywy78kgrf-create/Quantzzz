"""SQLite storage for the x402 settlement index.

Two properties protect a dataset that accretes for months:

1. IDEMPOTENCY. `settlements` is keyed on (tx_hash, log_index) with INSERT OR
   IGNORE, so re-processing any block range — after a crash, a retry, a reorg
   re-scan — can never double-count.

2. VISIBLE GAPS. `indexed_ranges` records only ranges we *confirmed complete and
   committed*. Coverage/holes are derived from it, so a missed or failed run is
   a detectable gap, not silent missing data. Nothing is ever assumed indexed.

Schema is versioned in `meta`; a mismatch refuses to run rather than mixing
incompatible rows.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        # a concurrent writer (cron run + manual run) waits rather than erroring
        self.db.execute("PRAGMA busy_timeout=30000")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.db.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS settlements (
              tx_hash        TEXT NOT NULL,
              log_index      INTEGER NOT NULL,
              chain          TEXT NOT NULL,
              token          TEXT NOT NULL,
              payer          TEXT NOT NULL,
              seller         TEXT NOT NULL,
              amount         INTEGER NOT NULL,
              block_number   INTEGER NOT NULL,
              block_timestamp INTEGER,
              -- EIP-3009 = the settlement is a gasless/authorized transfer (our
              -- core signal). facilitator is resolved lazily (tx.from) by the
              -- optional enrichment pass: NULL = unresolved, '' = resolved but
              -- not a known facilitator, else the facilitator id.
              facilitator    TEXT,
              PRIMARY KEY (tx_hash, log_index)
            );
            CREATE INDEX IF NOT EXISTS ix_settlements_seller
              ON settlements(seller);
            CREATE INDEX IF NOT EXISTS ix_settlements_block
              ON settlements(block_number);
            CREATE INDEX IF NOT EXISTS ix_settlements_ts
              ON settlements(block_timestamp);

            CREATE TABLE IF NOT EXISTS indexed_ranges (
              chain      TEXT NOT NULL,
              from_block INTEGER NOT NULL,
              to_block   INTEGER NOT NULL,
              n_settlements INTEGER NOT NULL,
              indexed_at TEXT NOT NULL,
              PRIMARY KEY (chain, from_block, to_block)
            );

            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            -- Solana coverage is per-relayer cursor (signature history walked
            -- newest-first), not block-range. last_signature is the newest
            -- signature we've fully processed for this relayer; the next run
            -- fetches everything newer via getSignaturesForAddress(until=it).
            -- Additive table (no schema bump): a Base-only DB simply ignores it.
            CREATE TABLE IF NOT EXISTS solana_cursors (
              relayer        TEXT PRIMARY KEY,
              last_signature TEXT,
              last_slot      INTEGER,
              backfilled_to_start INTEGER NOT NULL DEFAULT 0,
              updated_at     TEXT
            );
            """
        )
        row = cur.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            cur.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)",
                        (str(SCHEMA_VERSION),))
        elif int(row[0]) != SCHEMA_VERSION:
            raise RuntimeError(
                f"DB schema v{row[0]} != code v{SCHEMA_VERSION}; refusing to run")
        self.db.commit()

    def set_meta(self, key: str, value) -> None:
        self.db.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value) if not isinstance(value, str) else value))
        self.db.commit()

    def get_meta(self, key: str):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def commit_range(self, chain: str, from_block: int, to_block: int,
                     rows: list[dict], indexed_at: str) -> int:
        """Insert settlements and record the range as complete IN ONE TXN.

        The range is only marked indexed if the inserts commit, so a crash
        mid-range leaves the range absent from indexed_ranges (a visible gap to
        re-do) rather than half-recorded-as-done.
        """
        cur = self.db.cursor()
        try:
            cur.execute("BEGIN")
            for r in rows:
                cur.execute(
                    "INSERT OR IGNORE INTO settlements "
                    "(tx_hash,log_index,chain,token,payer,seller,amount,"
                    " block_number,block_timestamp) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (r["tx_hash"], r["log_index"], r["chain"], r["token"],
                     r["payer"], r["seller"], r["amount"],
                     r["block_number"], r["block_timestamp"]))
            cur.execute(
                "INSERT OR REPLACE INTO indexed_ranges "
                "(chain,from_block,to_block,n_settlements,indexed_at) "
                "VALUES(?,?,?,?,?)",
                (chain, from_block, to_block, len(rows), indexed_at))
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return len(rows)

    def covered_frontier(self, chain: str, start_block: int) -> int:
        """Highest block B such that [start_block, B] is fully covered by
        contiguous indexed_ranges. Returns start_block-1 if nothing covered.
        This is the resume point; it will not jump over a hole."""
        ranges = self.db.execute(
            "SELECT from_block,to_block FROM indexed_ranges WHERE chain=? "
            "ORDER BY from_block", (chain,)).fetchall()
        frontier = start_block - 1
        for fb, tb in ranges:
            if fb <= frontier + 1:
                frontier = max(frontier, tb)
            elif fb > frontier + 1:
                break  # a gap: stop advancing
        return frontier

    def find_gaps(self, chain: str, start_block: int, end_block: int) -> list[tuple]:
        """Return uncovered [gap_from, gap_to] sub-ranges within
        [start_block, end_block]. Empty list == fully covered."""
        ranges = self.db.execute(
            "SELECT from_block,to_block FROM indexed_ranges WHERE chain=? "
            "AND to_block>=? AND from_block<=? ORDER BY from_block",
            (chain, start_block, end_block)).fetchall()
        gaps = []
        cursor = start_block
        for fb, tb in ranges:
            if fb > cursor:
                gaps.append((cursor, min(fb - 1, end_block)))
            cursor = max(cursor, tb + 1)
            if cursor > end_block:
                break
        if cursor <= end_block:
            gaps.append((cursor, end_block))
        return gaps

    def get_solana_cursor(self, relayer: str):
        row = self.db.execute(
            "SELECT last_signature, last_slot FROM solana_cursors WHERE relayer=?",
            (relayer,)).fetchone()
        return row if row else (None, None)

    def set_solana_cursor(self, relayer: str, signature: str, slot: int,
                          indexed_at: str) -> None:
        self.db.execute(
            "INSERT INTO solana_cursors(relayer,last_signature,last_slot,updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(relayer) DO UPDATE SET "
            "last_signature=excluded.last_signature, last_slot=excluded.last_slot, "
            "updated_at=excluded.updated_at",
            (relayer, signature, slot, indexed_at))
        self.db.commit()

    def commit_solana_batch(self, rows: list[dict]) -> int:
        """Idempotent insert of Solana settlement rows (same table/PK as Base:
        tx_hash=signature, log_index=instruction index)."""
        cur = self.db.cursor()
        inserted = 0
        try:
            cur.execute("BEGIN")
            for r in rows:
                cur.execute(
                    "INSERT OR IGNORE INTO settlements "
                    "(tx_hash,log_index,chain,token,payer,seller,amount,"
                    " block_number,block_timestamp,facilitator) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["tx_hash"], r["log_index"], r["chain"], r["token"],
                     r["payer"], r["seller"], r["amount"],
                     r["block_number"], r["block_timestamp"],
                     r.get("facilitator")))
                inserted += cur.rowcount  # 1 if inserted, 0 if ignored (dupe)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise
        return inserted

    def stats(self, chain: str) -> dict:
        c = self.db.cursor()
        n = c.execute("SELECT COUNT(*) FROM settlements WHERE chain=?", (chain,)).fetchone()[0]
        sellers = c.execute("SELECT COUNT(DISTINCT seller) FROM settlements WHERE chain=?", (chain,)).fetchone()[0]
        vol = c.execute("SELECT COALESCE(SUM(amount),0) FROM settlements WHERE chain=?", (chain,)).fetchone()[0]
        rng = c.execute("SELECT MIN(block_number),MAX(block_number) FROM settlements WHERE chain=?", (chain,)).fetchone()
        return {"settlements": n, "unique_sellers": sellers,
                "volume_base_units": vol, "min_block": rng[0], "max_block": rng[1]}

    def close(self) -> None:
        self.db.close()
