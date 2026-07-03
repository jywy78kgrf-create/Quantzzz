# Phase 0 — Source Assessment: x402 Endpoint Quality Audit

Date: 2026-07-03
Status: awaiting go/no-go before Phase 1 (data collection)

All findings below were verified with live requests on 2026-07-03. No payments were made;
all access was read-only GET requests with an identifying User-Agent.

---

## Source 1: x402scan — RECOMMENDED PRIMARY

**What it is.** Ecosystem indexer/explorer run by Merit Systems, open source under
Apache-2.0 (github.com/Merit-Systems/x402scan). It ingests USDC transfer events settled
through a maintained list of known x402 facilitators on **Base and Solana**, stores them in
TimescaleDB, and serves aggregates through a **public, unauthenticated tRPC API** at
`https://www.x402scan.com/api/trpc/*`. The API is not formally documented, but the router
code is public in the repo, and `robots.txt` is `Allow: /` for all agents.

**Verified endpoints (live-tested):**

| Procedure | What it returns | Verified |
|---|---|---|
| `public.sellers.all.list` | Full seller census. Per seller: wallet, tx_count, total volume, unique_buyers, latest_block_timestamp, chains, facilitator_ids | **163,417 sellers** (all-time); `page_size=1000` accepted, ~2s/page → full census in ~164 requests |
| `public.transfers.list` | Individual transfers filterable by recipient/sender, sortable by `block_timestamp` asc/desc. Per transfer: sender, recipient, amount, timestamp, tx_hash, facilitator_id, chain | Yes — 0.6s/query. Ascending sort + recipient filter gives exact **first-seen** per seller |
| `public.sellers.bazaar.list` | Origins (endpoint URLs) mapped to recipient wallets, with per-origin activity stats | **2,387 origins** with URL + wallet mapping |
| `public.sellers.all.stats.{overall,bucketed}` | Aggregate + time-bucketed seller stats incl. new-seller counts (backed by `recipient_first_seen` MV) | Router code confirmed; same schema family |

**Coverage assessment.** x402scan indexes facilitator-settled transfers for ~10+
facilitators (coinbase, payAI, x402rs, thirdweb, daydreams, heurist, treasure, dexter,
relai, openx402, …) across Base + Solana. This is the broadest x402 activity index publicly
available and the one the community itself cites. Known gaps: (a) x402 payments settled
without a known facilitator (direct seller-settled) are not captured; (b) `unique_buyers`
in the census view is summed across materialized-view rows per recipient and may overcount;
(c) the census list lacks per-seller first-seen (obtainable per seller via transfers query).

**Scale note.** KPMG's Feb 2026 figure was ~83k sellers; the index now shows 163,417
(all-time, all facilitators, both chains) — consistent with ~4 months of growth. The report
will cite the measured number.

**Rate limits.** None documented. Plan: self-imposed throttle (≤4 req/s, exponential
backoff on 429/5xx), honest User-Agent identifying the audit, request logging per the
project spec.

## Source 2: Coinbase CDP x402 Bazaar — SECONDARY (catalog + liveness universe)

**Verified:** `GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources`
— public, **no API key**, documented read-only catalog API.

- **22,952 listed resources** (total from pagination metadata); `limit` up to 1000 → full
  catalog in ~23 requests.
- Per resource: endpoint URL, `payTo` wallet, network, asset, price, scheme, timeout,
  lastUpdated, optional description/schemas.
- **No activity data** — it is a registry, not an index.

**Role in the audit:**
1. "Listed" universe for GHOST classification (listed in catalog, zero/near-zero on-chain activity).
2. DUPLICATE detection (same URL or same `payTo` under multiple listings).
3. Liveness-probe target list (does the URL answer with a valid 402).
4. Independent cross-check of x402scan's origin→wallet mapping.

## Source 3: Direct on-chain (Base RPC / Etherscan V2 free tier) — FALLBACK / SPOT-AUDIT ONLY

Feasible in principle: facilitator addresses are published in the x402scan repo
(`packages/external/facilitators`), and x402 settlements are identifiable as USDC
`transferWithAuthorization` (EIP-3009) transactions submitted by facilitator addresses.
**Not viable as a primary source at free tier**: total transfer volume is tens of millions
of rows (the single largest seller alone has 207M transactions); Etherscan-family APIs cap
result windows at 10k rows and free-tier rate limits make a full re-index impractical.

**Role in the audit:** spot-verification. For a small random sample of sellers (~20–50),
independently pull their USDC transfer history from Base and confirm x402scan's tx_count /
volume / timestamps are accurate — i.e., audit the index rather than rebuild it. Solana
spot-checks via public RPC if needed.

---

## Recommended design

- **Primary:** x402scan public tRPC API.
  - Full census pull: all 163,417 sellers with aggregates (~164 requests). This alone
    supports GHOST, DORMANT (30/60/90d), coarse TEST-RIG (unique_buyers ≤ 2), volume
    concentration, and bucket volume shares — for the **entire population, no sampling**.
  - Deep transfer-level pull: deterministic seeded random sample of **≥10k sellers**
    (plus all top-1000 by volume, taken exhaustively) at 1–3 requests/seller for
    first-seen dates, payer concentration, self-dealing, amount uniformity, burst timing
    (TEST RIG and MEMECOIN signatures).
- **Secondary:** Bazaar catalog full pull (~23 requests) for listings, duplicates, and the
  liveness universe; merge with x402scan's 2,387 mapped origins.
- **Verification:** on-chain spot-audit of a small seller sample against Base.
- **Liveness probes:** deduped URL set (≈ low thousands), ≤1 req/s, honest User-Agent,
  record status + whether a valid x402 402 payment-requirements response is returned. No
  payment execution.

## Estimated coverage of the target question

| Question | Source | Coverage |
|---|---|---|
| Seller universe + activity aggregates | x402scan census | Full population (163,417) |
| Per-seller behavioral signatures | x402scan transfers | Top-1000 exhaustive + ≥10k seeded sample |
| Listed-but-dead endpoints | Bazaar + x402scan origins | Full catalog (22,952 resources / 2,387 mapped origins) |
| Endpoint liveness | Direct probes | All listed URLs after dedup |
| Index accuracy | On-chain spot-audit | ~20–50 sellers |

## Known limitations to carry into the report

1. Facilitator-scoped index: direct-settled x402 activity (no known facilitator) is invisible to all three sources.
2. `unique_buyers` may overcount for multi-chain/multi-window sellers (summed across MV rows).
3. On-chain activity proves payments, not service delivery quality.
4. The Bazaar registry and x402scan origin map cover only sellers that registered an endpoint; wallet-only sellers can't be liveness-probed.
5. x402scan's transfer index begins 2025-05-09 (per code comments); earlier activity, if any, is out of frame.

---

## Appendix: raw probe evidence

**Bazaar pagination metadata (2026-07-03):**
```json
{"pagination": {"limit": 20, "offset": 0, "total": 22952}, "x402Version": 2}
```

**x402scan seller census, top row by tx_count (2026-07-03):**
```json
{"recipient": "0x0495d60c927b97d67d5018c6aa65c9b2bebaeed9",
 "facilitator_ids": ["coinbase","daydreams","heurist","payAI","thirdweb","treasure","x402rs"],
 "tx_count": 207476003, "total_amount": 190355456900,
 "latest_block_timestamp": "2026-07-01T19:39:33.000Z",
 "unique_buyers": 31311, "chains": ["base"]}
```
(total_count: 163417; amounts are in token base units, USDC 6 decimals.)

**x402scan transfer record example (2026-07-03):**
```json
{"sender": "0x25f6a57b564f34094ccef7a2cebe675f344b1b57",
 "recipient": "0x0495d60c927b97d67d5018c6aa65c9b2bebaeed9",
 "amount": 10000, "block_timestamp": "2026-07-02T09:00:05.000Z",
 "tx_hash": "0x4cd16373aac61362ddefe5e3f74ce47b50000b85bed9ed1269c3d87f441c9c71",
 "chain": "base", "facilitator_id": "treasure", "decimals": 6,
 "token_address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"}
```
