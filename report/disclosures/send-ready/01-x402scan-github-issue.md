# #1 x402scan — public GitHub issue (file at DAY 7, with the PR)

**Repo:** github.com/Merit-Systems/x402scan/issues/new
**Do not file before day 7** — a public issue is immediate disclosure.

**Title:**
```
Seller-list aggregates inflated by facilitator count (unnest before SUM)
```

**Body:**
```markdown
### Summary
`listTopSellersMVUncached` in
`apps/scan/src/services/transfers/sellers/list-mv.ts` sums `total_transactions`,
`total_amount`, and `unique_buyers` across a `LATERAL unnest(facilitator_ids)`.
Because each base row is duplicated once per facilitator id before the `SUM`,
every numeric metric is multiplied by the seller's facilitator count. A seller
with 3 facilitators reports 3× its real tx_count / volume / buyers. This shows
on the public `public.sellers.all.list` route and inflates the site's aggregate
volume (~$154.8M reported vs ~$51.9M actual on a 2026-07-03 snapshot).

### Evidence
Validated against x402scan's own transfer-level data: for 3,113 sellers with
complete pulled histories, reported/actual tx ratio equals facilitator count
almost exactly (2/3/4 facilitators → 2.0/3.0/4.0). The transfer data itself is
accurate (153 transfers across 40 random sellers matched Base on-chain 100%);
only the aggregation is affected.

### Fix
Compute numeric aggregates in a CTE grouped by `recipient` (no unnest), build the
DISTINCT facilitator array in a separate CTE, and join on recipient. PR: #<PR>.
The `COUNT(DISTINCT recipient)` count query and `ARRAY_AGG(DISTINCT chain)` are
already correct and unchanged.

(Reported privately to the team on <day-0 date> ahead of this issue.)
```

**Note:** replace `#<PR>` with the PR number once opened, and fill the private-
report date.
