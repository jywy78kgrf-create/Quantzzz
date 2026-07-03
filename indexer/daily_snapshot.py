"""Daily snapshot runner — the moat-builder. Starts the history clock.

Each run, idempotently:
  1. Indexes new Base blocks to the (reorg-safe) tip.
  2. HALTS LOUDLY if there is any gap below the frontier — a longitudinal
     dataset with silent holes is worthless, so a hole is a hard error, not a
     warning that scrolls past.
  3. Writes an immutable, date-stamped per-seller aggregate snapshot to
     data/indexer/snapshots/<UTC-date>/ — never overwriting. These snapshots
     are the time series; the SQLite DB is the queryable substrate.

Run it from cron/systemd daily (or more often). Fully resumable; if a run is
missed, the next run's index step simply covers the wider range.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain import ChainClient  # noqa: E402
from decode import USDC_BASE  # noqa: E402
from index_base import (BOOTSTRAP_LOOKBACK_BLOCKS, CHAIN, CONFIRMATIONS,  # noqa: E402
                        DB_PATH, run)
from storage import Store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "indexer" / "snapshots"
REGISTRY = ROOT / "data" / "indexer" / "relayer_registry.json"


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def write_seller_snapshot(store: Store, snapshot_date: str, head: int) -> Path:
    out_dir = SNAP_DIR / snapshot_date
    out_dir.mkdir(parents=True, exist_ok=True)
    sellers_csv = out_dir / "seller_aggregates.csv"
    if sellers_csv.exists():
        raise FileExistsError(
            f"snapshot for {snapshot_date} already exists — refusing to "
            f"overwrite immutable history: {sellers_csv}")
    # group per (chain, seller) so a wallet active on both chains stays split
    rows = store.db.execute(
        "SELECT chain, seller, COUNT(*) tx_count, COUNT(DISTINCT payer) unique_payers, "
        "SUM(amount) volume, MIN(block_timestamp) first_ts, "
        "MAX(block_timestamp) last_ts, "
        "SUM(CASE WHEN payer=seller THEN 1 ELSE 0 END) self_pay_tx "
        "FROM settlements GROUP BY chain, seller ORDER BY volume DESC").fetchall()
    with open(sellers_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["chain", "seller", "tx_count", "unique_payers",
                    "volume_base_units", "first_ts", "last_ts", "self_pay_tx"])
        w.writerows(rows)
    meta = {
        "snapshot_date": snapshot_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head_block_base": head,
        "definition": ("settlement = USDC gasless/authorized transfer — Base via "
                       "EIP-3009, Solana via SPL transfer from a facilitator "
                       "relayer. Superset of facilitator-scoped x402."),
        "base": store.stats("base"),
        "solana": store.stats("solana"),
    }
    (out_dir / "snapshot_meta.json").write_text(json.dumps(meta, indent=2))
    return sellers_csv


def main() -> None:
    store = Store(DB_PATH)
    client = ChainClient("https://mainnet.base.org")
    head = client.block_number()
    end = head - CONFIRMATIONS
    # Bootstrap forward from launch on a fresh DB — never anchor to history
    # (that would try to backfill millions of blocks on the first run).
    if store.get_meta("start_block") is None:
        boot = end - BOOTSTRAP_LOOKBACK_BLOCKS
        store.set_meta("start_block", str(boot))
        store.set_meta("chain", CHAIN)
        store.set_meta("usdc", USDC_BASE)
        store.set_meta("created_at", datetime.now(timezone.utc).isoformat())
        if REGISTRY.exists():
            store.set_meta("relayer_registry_commit",
                           json.load(open(REGISTRY)).get("source_commit", "?"))
        print(f"[snapshot] first run: seeding ~{BOOTSTRAP_LOOKBACK_BLOCKS} blocks "
              f"of recent history from block {boot} (one-time bootstrap)")
    start = int(store.get_meta("start_block"))

    frontier = store.covered_frontier(CHAIN, start)
    run(client, store, max(start, frontier + 1), end)

    # HARD gap check — refuse to snapshot over holes
    max_blk = store.stats(CHAIN)["max_block"]
    if max_blk:
        gaps = store.find_gaps(CHAIN, start, max_blk)
        if gaps:
            print(f"[snapshot] ABORT: {len(gaps)} gap(s) below max indexed block "
                  f"{max_blk}. First: {gaps[0]}. Fix with "
                  f"`index_base.py --from {gaps[0][0]} --to {gaps[0][1]}` "
                  f"then re-run.", file=sys.stderr)
            store.close()
            sys.exit(1)

    # Solana: cursor-based per-relayer index (gap-free forward by construction —
    # no block-range gap check applies). Failures preserve per-relayer cursors
    # and resume next run; a Solana RPC outage never blocks the Base snapshot.
    try:
        from solana_chain import SolanaClient
        import index_solana
        index_solana.run(SolanaClient(index_solana.DEFAULT_RPC), store)
    except Exception as e:
        print(f"[snapshot] Solana index step error (Base snapshot unaffected): {e}",
              file=sys.stderr)

    # The index above always runs (keeps the DB current). The daily snapshot is
    # one-per-UTC-day and immutable: a same-day re-run advances the index but
    # cleanly skips re-writing the snapshot rather than crashing or clobbering.
    date = utc_date()
    if (SNAP_DIR / date / "seller_aggregates.csv").exists():
        print(f"[snapshot] {date} already captured; index advanced to "
              f"{store.stats(CHAIN)['max_block']}. Skipping duplicate snapshot.")
        store.close()
        return
    path = write_seller_snapshot(store, date, head)
    print(f"[snapshot] {date}: wrote {path}")
    print(json.dumps(store.stats(CHAIN), indent=2))
    store.close()


if __name__ == "__main__":
    main()
