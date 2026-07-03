# Independent x402 settlement indexer (Base)

Reads x402 / agentic-commerce settlements **straight from Base via JSON-RPC** —
no dependency on x402scan or any API we don't control. This is the source-
independent backbone of the longitudinal dataset: even if x402scan changes or
closes its API, this keeps producing history.

## What counts as a settlement (the definition — stated, not implied)

A settlement is a **USDC `Transfer` whose payer authorized it via EIP-3009
(`AuthorizationUsed`) in the same transaction** — i.e. a gasless / signed
("authorized") USDC payment, which is exactly the x402 payment mechanism. The
seller is the transfer's recipient (self-discovered; no prior seller list).

This is a **superset** of x402scan's view, which is scoped to registered
*facilitator* relayers. Empirically ~96–98% of these settlements are facilitator-
relayed (verified by resolving `tx.from`); the remainder are other gasless USDC
payments to sellers. You choose the slice:

- **All gasless settlements** (default, broadest "agentic sales") — the raw index.
- **Facilitator-x402 only** (matches x402scan) — run `enrich_facilitators.py`
  to tag each settlement's relayer, then filter `facilitator != ''`.

Reconciliation (`reconcile.py`) confirms that in the block window x402scan has
ingested, our chain-derived tx set matches theirs **100%** — the differences are
only (a) we're fresher (we read the tip; they lag ~minutes) and (b) we're broader
(non-facilitator gasless). Neither is a decode error.

## Correctness guarantees (why months of unattended runs won't silently rot)

- **Idempotent** — settlements keyed on `(tx_hash, log_index)` with INSERT OR
  IGNORE; re-runs, crashes, and reorg re-scans cannot double-count.
- **Visible gaps** — a block range is recorded as indexed only after its rows
  commit, in one transaction. Coverage is derived from that ledger, so a missed
  or failed range is a detectable gap. `daily_snapshot.py` **hard-aborts** rather
  than snapshot over a hole.
- **Resume never jumps a hole** — `covered_frontier` stops at the first gap.
- **Fail-loud on timeless data** — if the RPC stops returning `blockTimestamp`,
  indexing raises rather than write a time-series with null times.
- **Reorg-safe tip** — never indexes closer than 30 blocks (~60s) to head.
- **Schema-versioned** — a DB/code schema mismatch refuses to run.
- **Adaptive range** — `get_logs_chunked` splits on the RPC's range cap so a
  provider swap can't silently truncate results.
- **Unit-tested** — decode (address padding, uint parse, non-standard-log
  rejection) and gap/frontier logic: `tests/test_decode_and_gaps.py`.

## Files

| File | Role |
|---|---|
| `build_relayer_registry.py` | Parse facilitator relayer addresses from x402scan source (structured, not grep) → `data/indexer/relayer_registry.json` |
| `chain.py` | Defensive JSON-RPC client (retries, adaptive getLogs chunking) |
| `decode.py` | Pure, unit-tested log decoders (EIP-3009 Transfer / AuthorizationUsed) |
| `storage.py` | SQLite: idempotent settlements + block-completion ledger + gap logic |
| `index_base.py` | The range-walker (resume / backfill / status) |
| `enrich_facilitators.py` | Optional `tx.from` → facilitator tagging |
| `reconcile.py` | Cross-source correctness check vs x402scan (lag-aware) |
| `daily_snapshot.py` | Daily runner: index → gap-check → immutable per-seller snapshot |
| `tests/` | Unit tests |

## Operations

```bash
# one-time: build the relayer registry from an x402scan clone
python build_relayer_registry.py /path/to/x402scan

# daily (cron): index to tip + write today's immutable snapshot
python daily_snapshot.py

# status / coverage / gaps (no network)
python index_base.py --status

# backfill an explicit older range (patient; large for full history)
python index_base.py --from 29700000 --to 29800000

# optional: tag facilitators for the facilitator-x402 slice
python enrich_facilitators.py            # all unresolved
```

Snapshots land immutably in `data/indexer/snapshots/<UTC-date>/`. The SQLite DB
(`data/indexer/base_settlements.sqlite`) is the queryable substrate; the dated
snapshots are the time series.

## Honest limits / roadmap

- **Full historical backfill is a long job.** Base does ~250k settlements/day;
  backfilling from x402's 2025-05 start is ~100M+ rows and many getLogs passes.
  Forward-indexing (the moat) starts cheaply today; backfill runs patiently in
  the background, or is the one place a paid archive RPC would pay off (flagged,
  not silently assumed).
- **Facilitator enrichment is per-tx** (`eth_getTransactionByHash`); fine for
  daily volumes, slower for full backfill. The default index doesn't need it.
- **Deep reorgs** (>30 blocks on Base) are not reverted; negligible for
  aggregates, noted for completeness.

## Solana (`index_solana.py`)

Solana is ~15% of sellers / ~22% of transactions / ~14% of volume (per the
census), so it's material — indexed as a second module sharing the same DB and
settlements table (`chain='solana'`, `tx_hash`=signature, `log_index`=
instruction index, `block_number`=slot).

Different mechanics from Base (no log-topic filter): per facilitator relayer we
walk `getSignaturesForAddress` (cursor-based) and `getTransaction` each new sig.
A settlement is an SPL `transfer`/`transferChecked` of USDC (`EPjFW…`) whose
payer/seller are the **owners** of the source/destination token accounts —
resolved via the tx's pre/postTokenBalances (decoding the token accounts naively
would misattribute every seller; the unit tests pin this).

Correctness parity with Base: idempotent `(signature, ix_index)` inserts; a
per-relayer signature **cursor** advanced only post-commit; `until`=cursor makes
each run gap-free above the cursor; failed/unavailable txs stop-and-resume rather
than skip; **forward bootstrap** (fresh relayer seeds only its most-recent page,
never its entire history) so the first run is bounded; finalized data only.

```bash
python index_solana.py --to-head     # index all relayers newer-than-cursor
python index_solana.py --status
```

`daily_snapshot.py` runs the Solana step after Base; a Solana RPC outage is
caught and never blocks the Base snapshot. Full Solana history is an opt-in
backfill (walk `before` from the oldest cursor) — same posture as Base.

**RPC requirement (flag-and-stop).** Base runs fine on the free public RPC.
Solana does NOT: `api.mainnet-beta.solana.com` returns HTTP 429 under sustained
`getTransaction` load, so it's usable for spot checks but not bulk indexing.
Point `X402_SOLANA_RPC` (or `--rpc`) at a **keyed free-tier** endpoint
(Helius / Triton / QuickNode all have free tiers) before running Solana at
scale. The client honors `Retry-After` and backs off, but no backoff beats a
hard per-IP cap. Validation status: the Solana **decoder** is unit-tested and
verified against real mainnet transactions (token-account→owner resolution
confirmed on-chain); the **bulk walker** is built and logic-verified but its
full live end-to-end run is gated on a non-throttling RPC. Cross-source
reconciliation vs x402scan (as done for Base) is the remaining step once a real
RPC is wired.
