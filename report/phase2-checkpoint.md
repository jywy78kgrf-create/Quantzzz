# Phase 2 Checkpoint — Classification Distribution Sanity Check

Date: 2026-07-03. Status: awaiting user review before Phase 3 analysis.
Every number below regenerates from `pipeline/run_all.sh`; thresholds live in
`pipeline/config.yaml` (seed 402402 committed).

## Headline distribution (all 163,417 sellers, all-time)

Final classification = census aggregates for everyone + transfer-level deep
signals for 3,465 deep-pulled sellers (top-1,000 by volume exhaustive, all
1,173 ACTIVE-LEGITIMATE candidates, 1,500-seller random control).

| Bucket | Sellers | % sellers | % all-time volume |
|---|---:|---:|---:|
| GHOST (<5 lifetime tx) | 108,944 | 66.7% | 0.5% |
| TEST_RIG (self-deal / payer-concentration) | 42,297 | 25.9% | **67.1%** |
| DORMANT (>60d silent, real history) | 7,415 | 4.5% | 12.3% |
| LOW_ACTIVITY (recent, multi-buyer, thin) | 3,515 | 2.2% | 0.2% |
| ACTIVE_LEGITIMATE | **952** | **0.58%** | **17.9%** |
| DUPLICATE (shared endpoint URL) | 237 | 0.15% | 0.2% |
| MEMECOIN (burst-then-silence mint) | 57 | 0.03% | 1.9% |

Control-corrected population shares (control-sample transition rates applied
to non-deep-pulled sellers only): GHOST 66.7%, TEST_RIG 27.7%, DORMANT 2.9%,
LOW_ACTIVITY 1.8%, ACTIVE_LEGITIMATE 0.58%, DUPLICATE 0.15%, MEMECOIN 0.14%.

Dormancy at all three windows (sellers with ≥5 lifetime tx, n=54,473):
30d: 75.3% · 60d: 49.6% · 90d: 42.8%.

### Reading the volume column
The single largest seller by volume ($57.6M, 61.9M tx) shows **87.2%
self-dealing volume** (payer wallet == seller wallet) and is TEST_RIG. Of the
top-8 volume sellers, 4 are TEST_RIG (self-pay 52–95%), 2 ACTIVE_LEGITIMATE,
2 DORMANT mass-mint-shaped (see judgment call 1). "67% of volume is test-rig"
is the defensible statement; it is dominated by a handful of wash-pattern
whales, which Phase 3's concentration analysis will make explicit.

## Verification results

- **DELTA 2a (coverage):** 22,954 Bazaar resources collapse to **1,062 unique
  payTo wallets**; 271 (25.5%) have zero transfers in the x402scan index.
  5,683 resource URLs are listed with >1 payTo; 190 payTos span >1 origin.
- **DELTA 2b (index accuracy):** 40 seeded Base sellers, 153 claimed
  transfers — **100% found on-chain** (4 apparent misses were Blockscout
  listing gaps, recovered via direct RPC receipt checks; 0 true phantoms).
  Solana: 120/126 claimed signatures found via public RPC (misses consistent
  with public-RPC history retention, not index error).
- **DELTA 3 (buyer counts):** among 3,113 complete-history sellers, census
  unique_buyers / recomputed = **median 1.00** (82.8% exact match), p95 2.0.
  The census field is accurate at the median and ~2× inflated in the tail
  (multi-window/multi-chain double-counting). All Phase 3 diversity claims
  use recomputed values.

## Liveness (6,551 URLs probed, no payments)

| Measure | Result |
|---|---|
| Returns HTTP 402 (any body) | 3,873 / 6,551 (59.1%) |
| Returns **valid x402 402** (parseable accepts w/ scheme+network+payTo) | 1,764 / 6,551 (26.9%) |
| Bazaar-listed resources with valid 402 | 1,759 / 4,430 (39.7%) |
| Bazaar origins with ≥1 valid-402 resource | 469 / 1,213 (38.7%) |
| Other statuses | 200: 960 · 404: 857 · network error: 442 · 5xx: 247 |

Invalid-body 402s are real: sampled bodies are `{}` or ad-hoc error JSON — a
buyer agent cannot construct payment from them. Both rates will be reported.

## Judgment calls flagged for review

1. **MEMECOIN span threshold.** Two giants (51.8M and 26.5M transfers at
   $0.05/$0.10 modal share ≈1.00, silent 3–6 months) sit in DORMANT because
   their activity spans 73–163 days, exceeding `max_active_span_days: 21`.
   They are sustained mass-mint operations rather than short bursts. Options:
   (a) keep as-is (MEMECOIN stays burst-only), (b) widen the span cap, or
   (c) add a second rule: tx≥100k AND modal_share≥0.99 AND modal ≤$1 AND
   silent≥30d → MEMECOIN regardless of span. (c) is my recommendation; it
   moves ~7% of DORMANT volume to MEMECOIN and touches no other bucket.
2. **TEST_RIG census rule.** Sellers never deep-pulled are TEST_RIG on the
   census signal alone (≥5 tx, ≤2 unique buyers). The control sample supports
   it: 100% of control TEST_RIG stayed TEST_RIG under deep signals.
3. **Self-pay threshold at 10% of volume** (config `self_pay_share_min`)
   is the aggressive edge of the TEST_RIG rules; the top-8 sellers it caught
   were 52–95% self-pay, far above the line, so the headline is not
   threshold-sensitive here.

## Deep-pull coverage notes
- 3,465 / 3,467 allocated sellers pulled (2 persistent server-side 500s from
  x402scan, one AL candidate + one top-volume seller; both remain census-only
  and are counted in their census buckets).
- 4,894 x402scan API requests total this phase; 442 transient 500s retried.
