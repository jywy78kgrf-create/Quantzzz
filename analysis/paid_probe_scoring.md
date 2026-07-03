# Phase 2.5 Scoring — 18 Settled Payments (Run 1, 2026-07-03)

Evidence: `analysis/out/paid_probe_evidence.json` (bodies decoded in isolation
from the committed inert ledger). Every settlement has an on-chain tx hash in
the ledger. Scoring rubric per project spec: PAID-DELIVERED / PAID-GARBAGE /
PAID-NOTHING; PAYMENT-FAILED tracked separately (no settlements in that class
by construction). Overcharging is recorded per row but scored as a separate
finding — delivery and honest pricing are different failures.

**Run-1 caveat (disclosed at checkpoint):** the per-endpoint cap was inert due
to an executor bug; two endpoints settled above their listed price. Amounts
below are on-chain settled values.

## Stratum coverage of the 18 settlements
| Stratum | Settled payments |
|---|---:|
| top_volume | 6 |
| mid_activity | 5 |
| low_new | 7 |

## Verdicts

| # | Endpoint | Stratum | Settled | Verdict | Rationale (one line) |
|---|---|---|---:|---|---|
| 1 | 15.204.116.192.nip.io/nav | low | $0.05 | PAID-DELIVERED | Advertised fund-NAV snapshot; returned exactly that (AUM, per-strategy P&L, timestamps) |
| 2 | …supabase…/cortex402-mortgage-rates | low | $0.02 | PAID-DELIVERED | Advertised Fed mortgage/macro rates; returned FRED-series rates with as-of dates |
| 3 | mint.snowfro.com/…/x402-mint | low | $1.00 | PAID-DELIVERED | Advertised generative-art mint; returned queued-mint receipt with settlement hash |
| 4 | pitchiq…/x402/quote-action | low | $0.02 | PAID-DELIVERED | Advertised firm price quote; returned tool price + full payment requirements |
| 5 | basehelper.fun/api/x402-xp | low | $0.05 | PAID-DELIVERED | No advertised claim to test (empty listing description); returned valid confirmation consistent with its "XP" purpose |
| 6 | x402.d-bis.org/api/paid-base-cdp | low | $0.01 | PAID-DELIVERED | Self-described facilitator demo; returned its demo payload — placeholder-grade but exactly as advertised |
| 7 | x402pixels.com/api/pixels | low | $2.00 | PAID-DELIVERED | Advertised pixel-paint action; returned claim record (bbox/color) — **settled 2× listed price** |
| 8 | agents.dyoeway.org/approve | mid | $15.00 | PAID-DELIVERED | Returned a well-formed decision object (type matches); **settled 1500× listed price**, and the "real person signs off" claim is contradicted by its own `reviewer: automated-policy` field |
| 9 | api.the402.ai/v1/discover | mid | $0.001 | PAID-DELIVERED | Advertised marketplace catalog; returned 66KB service catalog |
| 10 | bounty.btnomb.com/…/idea_007/full | mid | $0.10 | PAID-DELIVERED | Advertised full bounty description unlock; returned the full description |
| 11 | nittarab.dev/secret | mid | $0.05 | PAID-DELIVERED | Advertised access to a content page; returned the content page (HTML) |
| 12 | datadon.xyz/datadon/hello | mid | $1.00 | PAID-DELIVERED | Advertised a greeting; returned the greeting (novelty service, delivered as described) |
| 13 | ainalyst-api.xyz/click | top | $0.01 | PAID-DELIVERED | Advertised "click the button"; returned "You clicked!" — trivial but exactly as advertised |
| 14 | basetomcat.com/api/mint-experience | top | $0.01 | PAID-NOTHING | Settled, then HTTP 500 leaking a database-credentials error; no product delivered |
| 15 | gifu-server…/x402/search/random | top | $0.03 | PAID-NOTHING | Settled, then HTTP 400 "mode must be gif or image" — charged before validating input (probe sent no params; listing published no example) |
| 16 | market.lnpay.ai/x402/agent | top | $0.01 | PAID-DELIVERED | Advertised "access to protected resource"; returned placeholder "protected content" — as advertised, if content-free |
| 17 | genbase.fun/api/image/create | top | $0.02 | PAID-NOTHING | Settled, then HTTP 400 "prompt is required" — charged before validating input |
| 18 | x721.dev/roadmap | top | $0.01 | PAID-DELIVERED | Advertised roadmap; returned roadmap items |

## Tallies

| Verdict | n | Share of settled |
|---|---:|---:|
| PAID-DELIVERED | 15 | 83% |
| PAID-NOTHING | 3 | 17% |
| PAID-GARBAGE | 0 | 0% |

By stratum: top_volume 4/6 delivered; mid_activity 5/5; low_new 7/7.

## Findings beyond the rubric

1. **Price integrity failure:** 2 of 18 settlements (11%) charged more than
   their catalog listing — one by 1500× ($15.00 vs $0.01 listed). x402's live
   402 quote overrides the discovery listing, and nothing in the protocol
   binds the two. Buyer agents MUST enforce a client-side cap (and note: the
   official x402-fetch default cap is only $0.10 — our own executor bug
   disabled it; see run-1 disclosure).
2. **Charge-before-validate:** 2 of 3 delivery failures took payment and then
   rejected the request as malformed (400). Payment-gating runs before input
   validation in these implementations — a buyer loses money on any
   schema mistake.
3. **All three PAID-NOTHING cases are top_volume sellers.** Small n, but the
   volume-ranked stratum performed worst on actual delivery.

n=18 from a pilot with a disclosed executor bug; these are directional
observations, not population estimates.
