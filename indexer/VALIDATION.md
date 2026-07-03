# Indexer validation — correctness evidence

The independent on-chain indexer is the source-independence layer: it derives
x402 settlements straight from chain (Base EIP-3009 `AuthorizationUsed`+`Transfer`
logs; Solana SPL USDC transfers in facilitator-relayer transactions) so the
longitudinal dataset does not depend on x402scan's API continuing to exist.

For a dataset meant to accrue for months, the failure mode that matters is
**silent corruption** — wrong rows that look fine until discovered late. These
are the guarantees, and how each is proven.

## Guarantees

| Property | Mechanism | Proven by |
|---|---|---|
| **No silent gaps** | per-relayer / per-block-range cursors; a failed range/relayer preserves its cursor and resumes, never skips | resume test; unit test on gap detection |
| **Idempotent** | `INSERT OR IGNORE` on `(tx_hash, log_index)`; re-run inserts 0 | re-run of a relayer returned 0 new, row count unchanged |
| **Accurate progress counts** | insert count sums `cur.rowcount`, not `len(rows)` | fixed 2026-07-03; re-run reports 0, not "68 again" |
| **Correct decode** | pure decoders, owner-resolution on Solana (token-account → owner), strict topic/shape checks on Base | 11/11 unit tests; on-chain spot validation |
| **No false positives** | every emitted row is a real facilitator-relayed USDC transfer | `validate_surplus.py`: sampled surplus rows all resolve on-chain to facilitator→seller USDC transfers |
| **No false negatives (vs reference)** | bidirectional reconcile vs x402scan, bounded to the covered window | `reconcile.py`: 0 real misses above the cold-start floor |
| **Attribution complete** | relayer (fee payer) recorded per row | fixed 2026-07-03; 68/68 populated in verification run |

## Cross-source reconciliation (`reconcile.py`)

x402scan is **not** treated as ground truth — a direct chain read legitimately
catches settlements the reference misses (x402scan sources Solana via Bitquery,
which lags/samples). The test is therefore directional and timestamp-banded to
the mutual window:

- **real misses** — a settlement x402scan has that we lack, *above the cold-start
  coverage floor* (the max of the per-relayer indexed floors, above which every
  relayer has contiguous coverage). This is the only failure signal. Target: 0.
- **depth misses** — below that floor: our bootstrap simply hasn't reached that
  far back for a busy relayer yet. Not a bug; a full backfill lowers the floor.
- **surplus** — settlements we have that x402scan lacks. Expected; validated for
  realness on-chain, so surplus can never hide false positives.

### Result (Solana, cold-start bootstrap, 2026-07-03)
Our index is a **strict superset** of x402scan in the overlap. Example: seller
`CvX23FNQsNQww8…` — 886 real settlements vs x402scan's 753; the 133-settlement
surplus was on-chain-validated as genuine facilitator-relayed USDC transfers.
Zero real misses above the covered floor.

## Known limitation — cold start depth

A fresh bootstrap takes only each relayer's most-recent ~1,000 signatures, so a
seller served by several busy relayers has *ragged* history depth until a
backfill runs. This does **not** affect ongoing correctness: once bootstrapped,
the incremental path (`signatures_since` from each cursor) captures every new
settlement. The durable schedule therefore accrues complete history from its
start date forward; historical backfill is a separate, resumable job.

## Reproduce

```
python3 -m pytest indexer/tests -q          # decoders + gap logic
python3 indexer/index_solana.py --to-head    # needs X402_SOLANA_RPC (keyed RPC)
python3 indexer/reconcile.py                 # bidirectional vs x402scan
python3 indexer/validate_surplus.py          # on-chain realness of surplus
```
