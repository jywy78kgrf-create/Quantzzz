# Fix PRs — prepared, NOT opened

Two patches, ready to open as pull requests. **Neither has been pushed or
opened.** Opening a PR against a public repo is itself a public disclosure, so
timing must be coordinated with the disclosure windows in `../` (do not open a
PR while that project's private disclosure window is open).

Each patch was authored against a fresh clone of the upstream default branch on
2026-07-03 and is a committed branch + exported `.patch`. **Neither was run
against the upstream test suite or (for the SQL) a live database** — see the
per-PR verification notes. Treat them as review-ready proposals, not
merge-ready-verified.

| Patch | Upstream | Branch | Warranted? |
|---|---|---|---|
| `x402scan-seller-inflation.patch` | Merit-Systems/x402scan | `fix/seller-aggregate-facilitator-inflation` | **Yes** — bug live on `main` |
| `x402-fetch-legacy-maxvalue-guard.patch` | coinbase/x402 | `fix/legacy-fetch-maxvalue-guard` | Optional — hardens the *deprecated* v1 package |

## What changed vs. the original disclosure plan

While preparing these I checked the current upstream state, and two of the
findings turned out to be **already fixed or not a code bug**. This is recorded
honestly here and reflected in the corrected disclosure `../02-x402-fetch-sdk.md`:

- **x402-fetch "cannot parse v2 402 bodies" (CAIP-2 + field names)** — NOT a bug
  to fix. Current `x402` core already accepts CAIP-2:
  `NetworkSchema = z.union([NetworkSchemaV1, NetworkSchemaV2])` and
  `PaymentRequirementsSchema = z.union([V1, V2])`. The package we used,
  `x402-fetch@1.2.0`, is the **explicitly deprecated v1 package** ("security
  patches only", migrate to `@x402/fetch`). It speaks v1 by design. So the "40%
  of attempts blocked" we measured is a consequence of using the deprecated
  package, not a defect in maintained code. No PR filed for this; the report
  frames it as an ecosystem/tooling-maturity observation, not an SDK bug.
- **maxValue footgun** — real, but only in that deprecated v1 package (the v2
  `@x402/fetch` `wrapFetchWithPayment(fetch, client)` has no positional
  `maxValue` at all). Because the deprecated package still receives *security
  patches* and a silently-disabled spend cap is a security issue, the guard
  patch is defensible. Optional — the maintainers may simply prefer to point
  users at v2.

---

## PR 1 — x402scan: seller-aggregate facilitator inflation

**Repo:** github.com/Merit-Systems/x402scan · **Base:** `main`
**File:** `apps/scan/src/services/transfers/sellers/list-mv.ts`

### Problem
`listTopSellersMVUncached` sums `total_transactions`, `total_amount`, and
`unique_buyers` across a `LATERAL unnest(facilitator_ids)`. Each base row is
duplicated once per facilitator id, so every numeric metric is multiplied by the
seller's facilitator count. A seller with 3 facilitators reports 3× its real
tx_count / volume / buyers. This surfaces on the public `public.sellers.all.list`
route and inflates the site's headline volume (~3× in aggregate on the
2026-07-03 snapshot).

### Fix
Compute the numeric aggregates in a `nums` CTE (grouped by recipient, **no**
unnest) and build the DISTINCT facilitator array in a separate `facs` CTE (where
the unnest fan-out is harmless), then join on recipient. The `ARRAY_AGG(DISTINCT
chain)` and the `COUNT(DISTINCT recipient)` count query were already correct and
are unchanged.

### Validation
- Root cause validated empirically against x402scan's own transfer-level data:
  for 3,113 sellers with complete pulled histories, reported/actual tx ratio
  equals facilitator count almost exactly (2/3/4 facilitators → 2.0/3.0/4.0).
- **Not run** against a live TimescaleDB or the repo's test suite (no DB
  access). The maintainers should run their MV tests; the two-CTE shape is
  standard SQL but the double scan of the MV is a perf consideration they may
  want to optimize into a single grouped scan.

### Scope note
Only the seller-list view was validated against chain. Other aggregation paths
(the `stats` overall/bucketed endpoints) do not use this unnest pattern, but a
maintainer audit for the same class of bug is worth doing.

---

## PR 2 — x402-fetch (legacy v1): reject non-bigint maxValue

**Repo:** github.com/coinbase/x402 · **Base:** `main`
**File:** `typescript/packages/legacy/x402-fetch/src/index.ts`

### Problem
`maxValue` is a positional `bigint` (base units). An untyped JS caller passing
an options object — `wrapFetchWithPayment(fetch, wallet, { maxValue: 1_000_000n })`
— is accepted at runtime; the later `amount > maxValue` becomes `bigint > object`,
always false, disabling both the intended cap and the 0.10 USDC default and
allowing an unbounded charge. (Observed live: a $0.01-listed endpoint settled
$15.00.)

### Fix
Throw at wrap time if `typeof maxValue !== "bigint"`.

### Validation
- Behavior verified independently with our own regression harness against the
  published `x402-fetch@1.2.0` (`pipeline/paid/test_cap.mjs`): with a correct
  `bigint` cap, $15.00 and $1.01 throw with zero payment attempts and $0.99
  proceeds to exactly one attempt.
- The one-line guard was **not** run through the upstream package's own test
  suite. It is additive and should not affect correctly-typed callers.

### Note
This package is deprecated (v1, security-patches-only). The maintainers may
prefer to close with "use `@x402/fetch` v2" rather than patch; the guard is
offered because a silent spend-cap bypass is a security-class issue and the
package still ships to `npm i x402-fetch`.
