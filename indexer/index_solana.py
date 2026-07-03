"""Independent Solana x402 settlement indexer.

Per facilitator relayer: fetch signatures newer than the stored cursor, decode
each tx's USDC settlements, insert idempotently, then advance the cursor — but
ONLY after the batch commits, so a crash re-does the batch rather than skipping
it. Sellers are self-discovered as transfer recipients' owners.

Correctness posture mirrors the Base indexer:
- idempotent inserts keyed on (signature, instruction_index);
- per-relayer cursor advanced only post-commit (no silent skip);
- `until`=cursor guarantees no gap above the cursor within a run;
- reorg-safe by indexing finalized data (getTransaction returns finalized).

Usage:
  python index_solana.py --to-head     # all relayers, newer-than-cursor
  python index_solana.py --status
"""

from __future__ import annotations

import argparse
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from decode_solana import decode_solana_settlements
from solana_chain import SolanaClient
from storage import Store

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "indexer" / "base_settlements.sqlite"  # shared DB
REGISTRY = ROOT / "data" / "indexer" / "relayer_registry.json"
# The free public endpoint 429-throttles under sustained load — fine for
# spot checks, NOT for bulk indexing. Point --rpc / X402_SOLANA_RPC at a keyed
# free-tier endpoint (Helius / Triton / QuickNode) for real operation.
DEFAULT_RPC = os.environ.get("X402_SOLANA_RPC", "https://api.mainnet-beta.solana.com")
CHAIN = "solana"
TX_PAUSE = 0.05   # gentle pacing; raise if your RPC still throttles


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def relayers() -> list[str]:
    return json.load(open(REGISTRY))["solana_relayers"]


def index_relayer(client: SolanaClient, store: Store, relayer: str,
                  bootstrap_pages: int = 1) -> int:
    last_sig, _ = store.get_solana_cursor(relayer)
    if last_sig is None:
        # FRESH relayer: bootstrap forward from now — take only the most recent
        # page(s), not the entire signature history (which for a busy relayer is
        # 100k+ sigs and would be an unbounded first run). Full history is an
        # explicit backfill (walk `before` from the oldest cursor). This mirrors
        # the Base indexer's forward-bootstrap.
        recent = client._call("getSignaturesForAddress",
                              [relayer, {"limit": 1000 * bootstrap_pages}])
        if not recent:
            return 0
        sigs = list(reversed(recent))   # chronological
    else:
        sigs = client.signatures_since(relayer, last_sig)
    if not sigs:
        return 0
    written = 0
    newest = None
    for s in sigs:
        sig = s["signature"]
        if s.get("err") is not None:
            newest = (sig, s.get("slot"))
            continue
        tx = client.get_transaction(sig)
        time.sleep(TX_PAUSE)
        if tx is None:
            # not yet available/finalized — stop here so we retry from this
            # point next run rather than skipping it
            break
        rows = decode_solana_settlements(tx, sig)
        if rows:
            written += store.commit_solana_batch(rows)
        newest = (sig, s.get("slot"))
        # advance cursor per tx so a mid-relayer crash resumes precisely
        store.set_solana_cursor(relayer, sig, s.get("slot"), utcnow())
    return written


def run(client: SolanaClient, store: Store) -> None:
    rels = relayers()
    print(f"[sol] indexing {len(rels)} relayers")
    total = 0
    for i, r in enumerate(rels):
        try:
            n = index_relayer(client, store, r)
        except Exception as e:
            print(f"[sol] relayer {r[:10]} FAILED: {e} (cursor preserved; "
                  f"will resume next run)")
            continue
        total += n
        if n:
            print(f"[sol] {i+1}/{len(rels)} {r[:10]}… +{n} settlements")
    print(f"[sol] done: {total} settlements this run")


def cmd_status(store: Store) -> None:
    st = store.stats(CHAIN)
    cursors = store.db.execute(
        "SELECT relayer,last_slot,updated_at FROM solana_cursors "
        "ORDER BY updated_at DESC").fetchall()
    print(json.dumps({**st, "relayers_with_cursor": len(cursors)}, indent=2))
    for r, slot, ts in cursors[:10]:
        print(f"  {r[:12]}… slot={slot} @ {ts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    ap.add_argument("--to-head", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()
    store = Store(Path(args.db))
    if args.status:
        cmd_status(store)
        store.close()
        return
    if args.to_head:
        run(SolanaClient(args.rpc), store)
    else:
        print("specify --to-head or --status")
    store.close()


if __name__ == "__main__":
    main()
