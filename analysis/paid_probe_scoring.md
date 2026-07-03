# Phase 2.5 Scoring — Paid Delivery Verification (Runs 1 + 2, 2026-07-03)

Evidence: `analysis/out/paid_probe_evidence.json` (bodies decoded in isolation
from the committed inert ledger). Settlement truth is **on-chain**
(`reconcile_chain.mjs`), not the response header — see the headerless-settle
finding below. Rubric: PAID-DELIVERED / PAID-GARBAGE / PAID-NOTHING;
PAYMENT-FAILED (settlement itself failed) tracked separately. Overcharging and
double-charging recorded per row, scored as separate findings.

## Spend accounting (authoritative, from chain)
- Wallet funded: $20.00 (run 1) + $12.00 (run 2) = **$32.00**
- On-chain outbound total: **$20.592** across 31 transfers → balance $11.41
- Run 1: $19.42 · Run 2: $1.17 (halt $10 never approached)
- **25 unique endpoints settled on chain** (18 detected by header in run 1;
  7 more in run 2, of which 5 were "headerless" — settled on chain but the
  server returned no `X-PAYMENT-RESPONSE`)

## Verdicts — 25 settled endpoints

| Endpoint | Stratum | Settled | Verdict | Rationale |
|---|---|---:|---|---|
| 15.204.116.192.nip.io/nav | low | $0.05 | DELIVERED | Fund-NAV snapshot as advertised |
| …/cortex402-mortgage-rates | low | $0.02 | DELIVERED | FRED mortgage/macro rates with as-of dates |
| mint.snowfro.com/…/x402-mint | low | $1.00 | DELIVERED | Generative-mint receipt + settlement hash |
| pitchiq…/quote-action | low | $0.02 | DELIVERED | Firm price quote + payment reqs |
| basehelper.fun/api/x402-xp | low | $0.05 | DELIVERED | Valid confirmation (empty listing desc) |
| x402.d-bis.org/…/paid-base-cdp | low | $0.01 | DELIVERED | Demo payload as self-described |
| x402pixels.com/api/pixels | low | $2.00 | DELIVERED | Pixel claim record — **settled 2× listed** |
| agents.dyoeway.org/approve | mid | $15.00 | DELIVERED | Decision object; **settled 1500× listed**; "human signs off" claim contradicted by `reviewer: automated-policy` |
| api.the402.ai/v1/discover | mid | $0.001 | DELIVERED | 66KB service catalog |
| bounty.btnomb.com/…/idea_007/full | mid | $0.10 | DELIVERED | Full bounty description unlocked |
| nittarab.dev/secret | mid | $0.05 | DELIVERED | Content page (HTML) |
| datadon.xyz/datadon/hello | mid | $1.00 | DELIVERED | Greeting (novelty, as described) |
| ainalyst-api.xyz/click | top | $0.01 | DELIVERED | "You clicked!" — trivial but as advertised |
| basetomcat.com/api/mint-experience | top | $0.01 | NOTHING | Settled then HTTP 500 leaking DB-credential error |
| gifu-server…/search/random | top | $0.03 | NOTHING | Settled then 400 "mode must be gif/image" (charge-before-validate) |
| market.lnpay.ai/x402/agent | top | $0.01 | DELIVERED | Placeholder "protected content" as advertised |
| genbase.fun/api/image/create | top | $0.02 | NOTHING | Settled then 400 "prompt is required" (charge-before-validate) |
| x721.dev/roadmap | top | $0.01 | DELIVERED | Roadmap items |
| **useatelier.ai/…/x402/pay** | low | $0.055 | DELIVERED | Async order accepted (status paid + poll URL) |
| **bald.x420.dev/api/puff** | low | $1.00 | DELIVERED | Bought BALD tokens; returned swap+send tx hashes |
| **paygent.obsmetrics.com/…/run** | mid | $0.08 | DELIVERED | Real tool-call-guard risk analysis (riskScore, recommendation) |
| **qrbase.xyz/api/x402/ping** ⚠ | low | $0.001×2 | DELIVERED | 200 "access granted" — but **headerless + double-charged** |
| **x402.agoragentic.com/…/text-summarizer** ⚠ | mid | $0.01×2 | GARBAGE | 200 returned the service's *listing metadata*, not a summary; **headerless + double-charged** |
| **t54.ai/…/get_api_health** ⚠ | low | $0.01×2 | NOTHING | 400 "Missing 'url' parameter"; **headerless + double-charged** (charge-before-validate) |
| **nut402.codenut.xyz/api/mint/xs** ⚠ | low | $0.01×2 | NOTHING | 500 "Mint failed" (RPC error); **headerless + double-charged** |

(⚠ = settled on-chain with no `X-PAYMENT-RESPONSE` header; bold = added in run 2.)

## Tallies (25 settled endpoints)

| Verdict | n | Share |
|---|---:|---:|
| PAID-DELIVERED | 19 | 76% |
| PAID-NOTHING | 5 | 20% |
| PAID-GARBAGE | 1 | 4% |

By stratum (settled n): top 4/8 delivered · mid 6/7 · low 9/10.

## Findings beyond the rubric

1. **Headerless settlement (5 of 25 = 20%).** These endpoints move USDC
   on-chain but return no `X-PAYMENT-RESPONSE` header. Two return HTTP 200
   "payment successful" (qrbase even echoes the tx hash in its body); the
   others return 400/500 *after* taking the money. To a buyer agent the
   payment looks unconfirmed or failed while the funds are gone — the single
   most hazardous pattern observed.
2. **Charge-before-validate / charge-then-error (4 of 25).** t54 (400), nut402
   (500), basetomcat (500), gifu/genbase (400) all settled payment and then
   errored. Payment gating runs before request validation and before the
   service can actually fulfill.
3. **Price-integrity failure (2 of 25).** dyoeway $15 vs $0.01 listed (1500×);
   x402pixels $2 vs $1. The live 402 quote is unbound to the catalog listing.
4. **All PAID-NOTHING skew to top/low, GARBAGE to mid.** Small n; directional.

## Control failures in this pilot (disclosed)

- **Run 1 cap bug** (fixed, verified): `maxValue` passed as an object instead
  of positionally disabled the per-endpoint cap; dyoeway's $15 settled. Now
  enforced (`test_cap.mjs`).
- **Double-charge, 4 endpoints (~$0.031 excess)** (fixed): the skip-set keyed
  on the response header, so the 5 headerless settlers were recorded unpaid
  and 4 were re-charged in run 2. Skip-set is now chain-truth
  (`reconcile_chain.mjs` → `chain_settled_paytos.json`); a re-run skips all 25.
- Neither failure approached the $10/$45 halt; the wallet balance bounded loss.

n=25 settled from a two-run pilot with disclosed executor bugs; directional
observations, not population estimates.
