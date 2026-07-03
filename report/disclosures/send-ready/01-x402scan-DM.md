# #1 x402scan — private DM (Discord or X @merit_systems)

**Channel:** Discord `discord.gg/JuKt7tPnNc` (DM a maintainer / post in a dev
channel) or X DM to `@merit_systems`. Private, to preserve the 7-day window
before the public issue/PR.

**Paste this:**

---

Hi — I'm an independent researcher doing a data-quality audit of the x402 seller
ecosystem, and I found a metrics bug in x402scan I wanted to flag privately
before I write anything public.

The seller-list query (`apps/scan/src/services/transfers/sellers/list-mv.ts`)
sums `tx_count`, `total_amount`, and `unique_buyers` across a
`LATERAL unnest(facilitator_ids)`, which multiplies every numeric metric by the
seller's facilitator count. A seller settled by 3 facilitators shows 3× its real
tx/volume/buyers. It surfaces on the public `public.sellers.all.list` route and
inflates the site's headline volume — on the 2026-07-03 snapshot, aggregate
all-time volume reads ~$154.8M vs. an actual ~$51.9M once corrected.

I validated it against your own transfer-level data: for 3,113 sellers with
complete histories, reported/actual ratio equals the facilitator count almost
exactly (2/3/4 facilitators → 2.0/3.0/4.0×). The transfer data itself is
accurate — I spot-checked 153 transfers across 40 sellers against Base on-chain
and they matched 100% — so it's purely the aggregation step.

I have a proposed fix (compute the numeric sums without the unnest, build the
facilitator array separately, join on recipient) and can open a PR if useful. I
plan to reference this in a public report in about a week; happy to include your
fix or comment, and glad to send the full write-up + repro. Where's best to send
it?

Thanks!

---

**After sending:** if they want the full write-up, send `../01-x402scan-aggregate-inflation.md`.
Hold the public issue + PR until day 7.
