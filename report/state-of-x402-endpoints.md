# The State of x402 Endpoints: How Much of the Seller Ecosystem Is Real?

**DRAFT — pending final review.**

Data snapshot: 2026-07-03. Population: 163,417 sellers (receiving wallets) with
at least one facilitator-settled x402 transfer on Base or Solana, per the
x402scan index, verified against chain (§ Verification). Every number in this
document regenerates from `pipeline/run_all.sh` in this repository; every
threshold is a named value in `pipeline/config.yaml`.

## Findings

### 1. 0.58% of x402 sellers are active, legitimate services — but they carry 21.6% of volume

Of 163,417 sellers ever observed, **948 (0.58%)** survive all filters:
≥20 lifetime transactions, ≥5 distinct paying wallets (recomputed from
transfer-level data, not the indexer's aggregate field), and activity within
the last 30 days. Everything else is ghosts (69.0%), test rigs (25.3%),
dormant (2.9%), thin-recent (2.1%), URL-duplicates (0.13%), or memecoin
artifacts (0.04%).

![Bucket distribution](figs/bucket_distribution.png)

| Bucket | Definition (config key) | Sellers | % sellers | % volume |
|---|---|---:|---:|---:|
| GHOST | <5 lifetime tx (`ghost`) | 112,694 | 68.96% | 1.4% |
| TEST_RIG | self-dealing ≥10% vol, or ≤2 payers, or top-2 payers ≥90% vol (`test_rig`) | 41,371 | 25.32% | 53.1% |
| DORMANT | real history, silent >60d (`dormant`) | 4,707 | 2.88% | 9.9% |
| LOW_ACTIVITY | recent, multi-payer, below sustained bar | 3,416 | 2.09% | 0.6% |
| ACTIVE_LEGITIMATE | sustained + diverse + recent (`active_legitimate`) | 948 | 0.58% | 21.6% |
| DUPLICATE | shares endpoint URL with a higher-volume wallet (`duplicate`) | 219 | 0.13% | 0.5% |
| MEMECOIN | mass identical small payments then silence (`memecoin`) | 62 | 0.04% | 12.8% |

Dormancy at all three windows (sellers with ≥5 lifetime tx, n=54,473):
**75.3% silent at 30 days, 49.6% at 60, 42.8% at 90.**

### 2. Only 26.9% of listed endpoints return a machine-payable x402 response

The catalogs overstate the network more than the chain does. Probing 6,551
listed URLs (unpaid GET, POST fallback for declared-POST routes, capped 10 per
origin, honest User-Agent):

![Liveness funnel](figs/liveness_funnel.png)

- 87% of Bazaar-listed resources return HTTP 402 — but only **39.7% return a
  valid x402 body** (parseable `accepts` with scheme, network, payTo). The
  rest answer 402 with `{}` or ad-hoc error JSON that no buyer agent can pay
  against. Across all probed URLs (including registered origin roots) the
  valid-response rate is **26.9%**.
- 960 URLs (15%) return 200 — no payment gate at all; 857 return 404; 442
  fail at the network level.

### 3. The Bazaar's 22,954 listings collapse to 1,062 wallets — and to ~222 payable operators

The x402 Bazaar (Coinbase's discovery catalog) lists 22,954 resources. Those
listings resolve to **1,062 unique receiving wallets**; 5,683 resource URLs
appear under more than one wallet. **271 of the 1,062 wallets (25.5%) have
zero transfers in the activity index** — listed, never paid once. After
deduplicating to one payable endpoint per operator (per wallet/origin, Base
mainnet, ≤$1), the entire payable catalog is ~222 distinct operators.

### 4. Volume is extremely concentrated — and most of it is self-dealing

![Volume concentration](figs/volume_concentration.png)

The top 10 sellers carry **75.1%** of all-time corrected volume; the top 100
carry **94.8%**. Within ACTIVE_LEGITIMATE, the top 10 carry 93.8% of that
bucket's volume. Concentration and wash-patterns overlap: the single largest
seller by volume shows **87% of its volume paid from its own wallet**, and 4
of the top 8 are TEST_RIG (self-pay 52–95%).

### 5. New-seller survival is near zero

![Cohort survival](figs/cohort_survival.png)

Of sellers first seen in Oct 2025 (the memecoin/registration wave; n=329 in
the control sample), **0.6% had any activity 60 days later**. Post-wave
cohorts run 0–5%. (Control-sample estimate; per-cohort n on the chart.)

### 6. The index itself is accurate — but its seller aggregates were inflated ~3×, which we corrected

Two verification results that cut in opposite directions:

- **The transfer-level index is accurate.** For 40 seeded-random sellers, all
  153 index-claimed transfers exist on Base with matching recipients (100%
  match; 4 apparent misses were Blockscout listing gaps, recovered by direct
  RPC receipt checks). Solana: 120/126 signatures found via public RPC.
- **The seller-level aggregates were inflated.** x402scan's seller list view
  multiplies each seller's tx_count, volume, and buyer count by the number of
  facilitators that ever settled for them (a `LATERAL unnest` before `SUM` in
  the view query). Validated against complete transfer histories: sellers
  with 2/3/4 facilitators show ratios of exactly 2.0/3.0/4.0. Corrected,
  the ecosystem's all-time volume is **$51.9M, not the $154.8M** the raw
  view reports. All numbers in this report use corrected values
  (`data/processed/census_inflation_validation.json`).

### 7. Paid delivery pilot: of endpoints that took payment, 76% delivered — but paying is hazardous

Everything above measures payment activity, which is a ceiling on "legitimate,"
not proof that paying returns a service. To test delivery directly we ran a
**mystery-shopper pilot: a stratified sample of 75 listed endpoints
(25 top-volume / 25 mid-activity / 25 low/new), price ceiling ≤ $1.00 per call,
one payment per endpoint, from a dedicated burner wallet.** This is a pilot
measurement, not a population estimate; n is small and the price ceiling
excludes every service costing more than a dollar.

Of the 75, **25 endpoints actually settled a payment on-chain** (the rest never
charged — they rejected the payment, returned a free 200, errored, or could not
be paid; see §7.1). Scoring the 25 that did take money, from committed raw
responses:

| Outcome | n | Share of settled |
|---|---:|---:|
| PAID-DELIVERED (valid response matching the advertised resource) | 19 | **76%** |
| PAID-NOTHING (settled, then no usable response) | 5 | 20% |
| PAID-GARBAGE (2xx, but empty/unrelated content) | 1 | 4% |

By stratum (settled n): top-volume 4/8 delivered, mid-activity 6/7, low/new 9/10.
Full per-endpoint verdicts with rationales and tx hashes:
`analysis/paid_probe_scoring.md`.

#### 7.1 Hazard: 20% of settled endpoints took payment while signaling failure ("headerless settlement")

The most dangerous pattern we found: **5 of the 25 settled endpoints (20%)
moved USDC on-chain but returned no `X-PAYMENT-RESPONSE` header** — the header
the x402 protocol uses to confirm settlement to the payer. Two returned HTTP 200
with a success body (one even echoed the payment tx hash in JSON); the other
three returned **HTTP 400 or 500 *after* taking the money** (e.g. "Missing 'url'
parameter", "Mint failed"). **Consequence: a buyer agent cannot tell from the
response that it paid.** The payment looks unconfirmed or failed while the funds
are already gone, and standard retry-on-failure logic pays again.

**We demonstrated this failure live, on ourselves.** Our run-1 skip-list
("never pay the same endpoint twice") keyed on the `X-PAYMENT-RESPONSE` header.
Because these 5 endpoints returned no header, our own executor recorded them as
unpaid — and on run 2 it **paid 4 of them a second time (~$0.031 in excess
charges)**. We disclose this as a control failure of our own audit: it is the
cleanest possible evidence that the hazard is real and that header-based
settlement detection is unsafe. The fix was to rebuild the skip-list from
**chain truth** — the set of wallets our burner had actually paid, derived by
reconciling on-chain USDC transfers (`pipeline/paid/reconcile_chain.mjs` →
`chain_settled_paytos.json`). After the fix, a re-run correctly skips all 25
settled endpoints.

#### 7.2 Hazard: charge-before-validate (4 endpoints)

Four endpoints settled payment and *then* rejected the request as malformed
(HTTP 400 "prompt is required", "mode must be 'gif' or 'image'") or failed
internally (HTTP 500). Payment gating runs before input validation and before
the service can fulfill, so any client-side schema mistake — or a seller-side
bug — costs the buyer money with nothing returned. One of the 500s exposed an
internal database-authentication error in its paid response body (internal error
detail leaked to a paying client; no literal secret value was present).

#### 7.3 Hazard: the live price can exceed the listed price without limit

The price a buyer sees in the discovery catalog is not binding. Two of 25
settled endpoints charged more than their listing: **`agents.dyoeway.org/approve`
settled $15.00 against a $0.01 listing — 1500×** — and `x402pixels.com/api/pixels`
settled $2.00 against $1.00. The live 402 quote overrides the catalog and
nothing in the protocol binds the two, so a buyer agent that trusts the listing
has no protection; only a hard client-side cap does. (Our run-1 executor had a
cap bug that let the $15.00 charge through; see §7.4.)

#### 7.4 The core methodological finding: trust chain truth, not seller signals

Every control in this audit that trusted a **seller-supplied signal** failed,
and every control anchored to **chain truth** held:

| Control | Trusted | Outcome |
|---|---|---|
| Price safety | listed catalog price | **failed** — 1500× overcharge got through |
| No-double-pay | `X-PAYMENT-RESPONSE` header | **failed** — 4 headerless settlers re-paid |
| Spend cap | (our bug: malformed arg) | **failed** in run 1 — disabled silently |
| Spend ceiling | wallet balance on-chain | **held** — bounded total loss throughout |
| Settlement ledger | on-chain tx receipts | **held** — caught the double-pays |
| Skip-list (fixed) | chain-derived paid set | **held** — re-run pays nothing twice |

This is the audit's central lesson for anyone building on x402: **a buyer agent
must anchor every spend decision to on-chain state, never to a price, a header,
or a status code the seller controls.** The failures were not exotic — they were
the default, trusting implementation, and they cost real money in a $20 pilot.

Total pilot spend: **$20.59** on-chain across two runs (funded $32; $11.41
unspent). Every payment is traceable to an on-chain tx hash in
`data/raw/paid_probes/`.

## Methodology

**Sources.** (1) x402scan public tRPC API — seller census (163,417 wallets,
drift-free recipient-keyed pagination), per-seller transfer histories, origin→
wallet map; (2) Coinbase CDP Bazaar discovery API — 22,954 listings; (3) Base
via Blockscout REST + public RPC, Solana public RPC — verification. All pulls
raw-archived (`data/raw/`, gzip, never overwritten) with an append-only
request log (~12k requests: timestamp, URL, params, status, response hash).

**Classification.** Two passes. Census pass: every seller bucketed on
corrected aggregates. Deep pass: transfer-level features for 3,523 sellers —
top-1,000 by corrected volume (exhaustive), all 1,173 ACTIVE_LEGITIMATE
candidates, and a 1,500-seller seeded random control (seed 402402). Features:
recomputed unique payers, self-pay share, top-2 payer concentration, modal
amount share, burst/span/silence. Bucket priority: GHOST > TEST_RIG >
DUPLICATE > MEMECOIN > DORMANT > ACTIVE_LEGITIMATE.

**Classifier error, measured.** On the control sample the census-level
classifier agrees with the deep-signal classifier for **98.9%** of sellers.
Errors are one-directional: 19% of census-DORMANT controls reclassify to
TEST_RIG/MEMECOIN under transfer-level signals; census-TEST_RIG was confirmed
333/333. Corrected population shares (transition rates applied to non-deep-
pulled sellers only) change no headline by more than 0.3 points.

**Hand inspection.** 5 seeded-random sellers per bucket eyeballed against
their definitions: 33/35 outright matches; the 2 exceptions are census-only
sellers whose patterns look rig-like — the exact direction the control
quantifies (`analysis/hand_inspection.md`).

**Buyer counts recomputed.** All diversity claims use payer wallets deduped
across chains from raw transfers. The indexer's aggregate buyer field, after
facilitator correction, matches recomputed counts for 93.9% of complete-
history sellers (median ratio 1.00).

**Liveness.** 6,551 URLs, unpaid probes only, ≤4 req/s global, ≥5s per host,
identifying User-Agent, 15s timeout. Valid-402 = parseable accepts with
scheme + network + payTo.

**Paid delivery pilot.** 75 endpoints, stratified 25/25/25 by seller activity,
price ceiling ≤ $1.00, one payment per endpoint from a dedicated burner wallet
funded with $32 (spent $20.59). Delivery scored from committed inert response
bodies; settlement truth reconciled from on-chain USDC transfers, not response
headers. Two executor control failures occurred and are disclosed in full in
§7.1 and §7.4 (a silently-disabled spend cap in run 1, and 4 double-payments
caused by header-based settlement detection); both were bounded by the wallet
balance, neither approached the halt, and both are fixed with chain-anchored
controls (`pipeline/paid/`, `test_cap.mjs`, `reconcile_chain.mjs`).

## Limitations

1. **On-chain activity proves payments, not service quality.** A seller with
   real, diverse, recent payments could still return garbage — payment
   activity is our ceiling on "legitimate," not proof of delivery. The paid
   pilot (§7) tests delivery directly but only on n=25 settled endpoints at
   ≤ $1.00; it is a pilot signal, not a population delivery rate.
2. **Facilitator-scoped visibility.** All sources observe facilitator-settled
   transfers for ~30 known facilitators on Base + Solana. x402 payments
   settled directly (seller as its own facilitator) are invisible here. The
   25.5% of listed wallets with zero indexed activity is partly this, partly
   truly-never-used; we cannot split the two from the data.
3. **Thresholds are judgment calls.** Every one is a named value in
   `pipeline/config.yaml`; disagree, edit, re-run `pipeline/run_all.sh`. The
   headline is threshold-robust in the directions we tested (top-8 TEST_RIG
   sellers sit 5–9× above the self-pay line).
4. **Deep signals cover 3,523 of 163,417 sellers** (all candidates + top
   volume + control); the rest carry census-level buckets with the measured
   1.1% error rate and known under-detection of rigs inside DORMANT.
5. **Sample-based cohort survival.** Cohort estimates come from the 1,500-
   seller control; small post-wave cohorts have wide intervals (n on chart).
6. **Index dependence.** The transfer index passed a 40-seller/153-tx
   on-chain audit and we corrected its seller-aggregate inflation, but any
   unknown index-level gap propagates. Solana verification is weaker (public
   RPC history retention).
7. **Timing.** All numbers are as of 2026-07-03; the census is all-time, so
   the wave-then-silence dynamics of late 2025 dominate lifetime aggregates.

---

*Repository layout: `pipeline/` (collection + classification, config),
`analysis/` (every figure's script + JSON output), `data/raw/` (immutable
pulls + request log), `data/processed/` (derived tables), `report/figs/`
(chart PNGs + `analysis/make_charts.py`).*
