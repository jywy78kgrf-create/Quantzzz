"""Independent Base x402 settlement indexer.

Reads USDC EIP-3009 settlements straight from Base via JSON-RPC — no dependency
on x402scan or any API we don't control. A settlement is a USDC `Transfer`
whose payer authorized it via `AuthorizationUsed` in the same tx (the gasless/
x402 fingerprint). Sellers are self-discovered as the `to` of each transfer.

Correctness posture (this thing runs unattended for months):
- Idempotent inserts + a block-completion ledger (see storage.py): re-runs and
  crashes cannot double-count or silently skip.
- Gap-driven: each run fills uncovered sub-ranges within the target; a failed
  sub-range stays an explicit gap for the next run instead of being stepped over.
- Reorg-safe tip: never indexes closer than `confirmations` blocks to head.
- Every value is decoded by the unit-tested pure functions in decode.py.

Usage:
  python index_base.py --to-head            # resume/extend to chain tip
  python index_base.py --from A --to B       # backfill an explicit range
  python index_base.py --status              # coverage + gaps, no network
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from chain import ChainClient
from decode import (AUTHORIZATION_USED_TOPIC, TRANSFER_TOPIC, USDC_BASE,
                    decode_transfer, topic_to_address)
from storage import Store

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "indexer" / "base_settlements.sqlite"
REGISTRY = ROOT / "data" / "indexer" / "relayer_registry.json"
DEFAULT_RPC = "https://mainnet.base.org"
# x402 (per x402scan) begins 2025-05; Base block ~ 29.7M at 2025-05-09. This is
# the anchor for an EXPLICIT historical backfill only. It is deliberately NOT
# the auto-default start: on first init we bootstrap start_block to the current
# head (see main) so "start the clock" indexes forward from launch and can never
# accidentally kick off an 18M-block backfill. Full history is an opt-in job:
#   index_base.py --from 29700000 --to <later>
HISTORY_ANCHOR_BLOCK = 29_700_000
CONFIRMATIONS = 30          # ~60s on Base; stay clear of tip reorgs
# On first init we seed this much recent history so day-1 isn't empty (Base ~2s/
# block, so 43,200 ≈ 24h). One-time, bounded; full backfill stays an opt-in job.
BOOTSTRAP_LOOKBACK_BLOCKS = 43_200
SUBRANGE = 400              # blocks per getLogs pass (tuned to result sizes)
CHAIN = "base"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def index_subrange(client: ChainClient, store: Store, lo: int, hi: int) -> int:
    """Index [lo, hi] inclusive. Returns settlements written."""
    # 1. EIP-3009 authorizations in range -> {tx_hash: {authorizer,...}}
    auth_by_tx: dict[str, set[str]] = {}
    for lg in client.get_logs_chunked(address=USDC_BASE,
                                       topics=[AUTHORIZATION_USED_TOPIC],
                                       from_block=lo, to_block=hi):
        tx = lg["transactionHash"].lower()
        auth_by_tx.setdefault(tx, set()).add(topic_to_address(lg["topics"][1]))
    if not auth_by_tx:
        return store.commit_range(CHAIN, lo, hi, [], utcnow())

    # 2. USDC transfers in range; keep those authorized by their payer in-tx
    rows = []
    for lg in client.get_logs_chunked(address=USDC_BASE,
                                       topics=[TRANSFER_TOPIC],
                                       from_block=lo, to_block=hi):
        tx = lg["transactionHash"].lower()
        authorizers = auth_by_tx.get(tx)
        if not authorizers:
            continue
        rec = decode_transfer(lg)
        if rec["payer"] in authorizers:
            rows.append(rec)
    # A timeless time-series is worse than none: if the RPC stopped returning
    # blockTimestamp on logs, fail loud instead of silently writing null times.
    missing_ts = [r for r in rows if r["block_timestamp"] is None]
    if missing_ts:
        raise RuntimeError(
            f"{len(missing_ts)}/{len(rows)} settlements in [{lo},{hi}] have no "
            f"block_timestamp — RPC not returning it. Refusing to write a "
            f"timeless series. (Use an RPC that includes blockTimestamp on logs.)")
    return store.commit_range(CHAIN, lo, hi, rows, utcnow())


def run(client: ChainClient, store: Store, start: int, end: int) -> None:
    gaps = store.find_gaps(CHAIN, start, end)
    if not gaps:
        print(f"[index] [{start},{end}] already fully covered")
        return
    total_missing = sum(g[1] - g[0] + 1 for g in gaps)
    print(f"[index] target [{start},{end}] "
          f"{len(gaps)} gap(s), {total_missing} blocks to index")
    done_blocks, written = 0, 0
    for gap_lo, gap_hi in gaps:
        lo = gap_lo
        while lo <= gap_hi:
            hi = min(lo + SUBRANGE - 1, gap_hi)
            n = index_subrange(client, store, lo, hi)
            written += n
            done_blocks += hi - lo + 1
            if done_blocks % (SUBRANGE * 25) < SUBRANGE:
                print(f"[index] …{done_blocks}/{total_missing} blocks, "
                      f"{written} settlements", flush=True)
            lo = hi + 1
    print(f"[index] done: {written} settlements over {done_blocks} blocks")


def cmd_status(store: Store) -> None:
    start = int(store.get_meta("start_block") or DEFAULT_START_BLOCK)
    frontier = store.covered_frontier(CHAIN, start)
    st = store.stats(CHAIN)
    print(json.dumps({
        "start_block": start,
        "covered_frontier": frontier,
        "contiguous_blocks_covered": max(0, frontier - start + 1),
        **st,
    }, indent=2))
    # report holes below the frontier explicitly
    if st["max_block"]:
        gaps = store.find_gaps(CHAIN, start, st["max_block"])
        print(f"gaps below max indexed block: {len(gaps)}")
        for g in gaps[:20]:
            print(f"  gap [{g[0]},{g[1]}] ({g[1]-g[0]+1} blocks)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    ap.add_argument("--from", dest="from_block", type=int)
    ap.add_argument("--to", dest="to_block", type=int)
    ap.add_argument("--to-head", action="store_true")
    ap.add_argument("--start-block", type=int, default=None,
                    help="bootstrap start (default: current head — start the "
                         "clock forward). Use with an old value only for backfill.")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    store = Store(Path(args.db))
    client = None
    if store.get_meta("start_block") is None:
        # Bootstrap: default to current head so we index FORWARD from launch.
        # Never silently anchor to genesis/history (would trigger a huge
        # backfill on the first run).
        if args.start_block is not None:
            boot = args.start_block
        else:
            client = ChainClient(args.rpc)
            boot = client.block_number() - CONFIRMATIONS - BOOTSTRAP_LOOKBACK_BLOCKS
        store.set_meta("start_block", str(boot))
        store.set_meta("chain", CHAIN)
        store.set_meta("usdc", USDC_BASE)
        store.set_meta("created_at", utcnow())
        if REGISTRY.exists():
            reg = json.load(open(REGISTRY))
            store.set_meta("relayer_registry_commit", reg.get("source_commit", "?"))

    if args.status:
        cmd_status(store)
        store.close()
        return

    if client is None:
        client = ChainClient(args.rpc)
    start = int(store.get_meta("start_block"))
    if args.from_block is not None and args.to_block is not None:
        run(client, store, args.from_block, args.to_block)
    elif args.to_head:
        head = client.block_number()
        end = head - CONFIRMATIONS
        frontier = store.covered_frontier(CHAIN, start)
        run(client, store, max(start, frontier + 1), end)
    else:
        print("specify --to-head, --from/--to, or --status")
    store.close()


if __name__ == "__main__":
    main()
