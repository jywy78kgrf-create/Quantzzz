# Disclosure draft — x402scan seller-aggregate inflation

**To:** Merit Systems (maintainers of github.com/Merit-Systems/x402scan)
**Status:** DRAFT — not sent. Do not send without explicit authorization.
**Severity:** Data-integrity (public-facing metrics overstated ~3×)

## Summary

The seller-list aggregation in x402scan multiplies each seller's `tx_count`,
`total_amount`, and `unique_buyers` by the number of facilitators that have ever
settled for that seller. On the public snapshot we pulled on 2026-07-03 this
inflates the ecosystem's reported all-time settled volume from an actual
**~$51.9M to a reported ~$154.8M**, and inflates per-seller counts for every
multi-facilitator seller.

## Where

`apps/scan/src/services/transfers/sellers/list-mv.ts` — the query against
`recipient_stats_aggregated_*` uses:

```sql
FROM ${tableName},
  LATERAL unnest(facilitator_ids) AS unnested_facilitator
...
GROUP BY recipient
```

with `SUM(total_transactions)`, `SUM(total_amount)`, `SUM(unique_buyers)`.
Because the row is cross-joined against `unnest(facilitator_ids)` before the
`SUM`, each base row is counted once per facilitator id in the array. A seller
whose `facilitator_ids = {coinbase, payAI, x402rs}` has every summed metric
tripled. The `ARRAY_AGG(DISTINCT unnested_facilitator)` in the same select is
unaffected (DISTINCT collapses the fan-out), which is why the bug is not visible
from the facilitator list itself.

This surfaces in the public tRPC route `public.sellers.all.list` and anything
downstream of it.

## Reproduction (read-only, public API)

1. Pull `public.sellers.all.list` (all-time) and note a seller with ≥2
   `facilitator_ids`, e.g. recipient `0xf7b1356cfed0eebe01d76da7ba9e9f8bf12d9d57`
   reported with 5 facilitators.
2. Pull that seller's actual transfers via `public.transfers.list`
   (`recipients.include = [that address]`, timeframe 0) and count them.
3. The reported `tx_count` is ~5× the actual transfer count. We validated the
   pattern across 3,113 sellers with complete transfer histories: the ratio of
   reported-to-actual equals the facilitator count almost exactly
   (2/3/4 facilitators → 2.0/3.0/4.0), with the aggregate distribution
   `{1 facilitator: ratio 1.0, 2: 2.0, 3: 3.0, 4: 4.0}`.

Our reproduction script and validation output:
`pipeline/correct_census.py` → `data/processed/census_inflation_validation.json`.

## Proposed fix

Aggregate the per-recipient metrics **before** unnesting facilitators, or
deduplicate the base rows. Two equivalent shapes:

- Compute the metric sums in a subquery grouped by `recipient` (no `unnest`),
  and join the `ARRAY_AGG(DISTINCT facilitator)` separately; or
- Replace the lateral `unnest` + `SUM` with `SUM(total_transactions)` over
  `GROUP BY recipient` and derive `facilitator_ids` via a correlated
  `ARRAY_AGG(DISTINCT ...)` that does not participate in the numeric sums.

The transfer-level data itself is accurate — we independently verified 153
claimed transfers across 40 random sellers against Base on-chain state with a
100% match — so only the aggregation step needs changing, not the underlying
index.

## Note

We are preparing a public report on x402 endpoint quality that will reference
this finding. We would like to give you a **7-day window** from the date this is
sent to review and respond before publication, and we are happy to include your
fix or comment. Our numbers throughout the report use the corrected values.
