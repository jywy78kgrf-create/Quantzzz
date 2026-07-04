# Agentic-Payment Coverage Roadmap

*Source: adversarially-verified deep-research pass, July 2026 (105 verification
agents, 23 sources, 25 claims verified / 1 killed). Figures are point-in-time
snapshots Dec 2025–Apr 2026 and diverge 10×+ across providers — treat volumes as
directional with wide error bars; the structural/indexability conclusions are
solid. Once this index accrues its own history, **we become the primary source**
that resolves the measurement chaos.*

## Thesis: the observable agentic-payment economy ≈ x402 across chains

x402 is the **only** rail with material, publicly observable on-chain settlement
(USDC EIP-3009 `transferWithAuthorization` → `Transfer` events). Everything else
is either already captured by x402, structurally invisible to *any* indexer, or
has no verified volume yet. So "comprehensive coverage of the observable economy"
is achievable primarily by **adding x402 chains** — a short path.

## Ranked build sequence (what to add next; we already have Base + Solana)

| # | Add | Why | Effort |
|---|---|---|---|
| 1 | **x402-Polygon** | Live on Mainnet (PoS) + Amoy, multiple facilitators; 3rd-largest x402 chain (~15.2K tx/day Jan snapshot) | Low — same indexer, new relayer set |
| 2 | **x402-Avalanche, x402-Sei** | Confirmed x402 chains; complete the EVM footprint (volumes unmeasured) | Low each |
| 3 | **Newer x402 chains as they launch** | Keep the relayer registry current | Ongoing, trivial |
| 4 | **Verify AP2/x402 coverage** (not a build) | Confirm AP2 crypto settlements already appear in our x402 data | Verification task |

## Free win: AP2 requires no separate integration

Verified against Google's official `a2a-x402` spec (v0.1): **AP2 crypto payments
settle through the x402 extension** as ordinary on-chain USDC EIP-3009 transfers
(the settle response even echoes the tx hash). **x402 is AP2's only production
stablecoin facilitator as of mid-2026** → our existing x402 indexing already
captures AP2's crypto footprint. Caveat: AP2 is payment-agnostic; if it ever adds
a non-x402 crypto rail, that wouldn't auto-appear — re-check periodically.

## Structural blind spots (invisible to every on-chain indexer)

- **Stripe/OpenAI ACP** — settles via Shared Payment Tokens that clone the
  customer's card and run on Visa/card rails inside Stripe. Never touches a
  public ledger. Permanently unindexable.
- **L402 / Lightning** — settles **off-chain in private payment channels**; only
  channel open/close is on-chain, not the payments. Likely closer to "blind spot"
  than to a clean indexing target. *(Correction to an earlier informal take that
  called L402 the "biggest observable gap" — the research indicates it's largely
  off-chain.)*
- **Card-settled AP2** — the non-crypto AP2 path is card rails, same as ACP.

Cover these **journalistically** (their own published aggregates / announcements),
label them clearly as a structural blind spot. "Here's everything observable, and
here's exactly what's invisible and why" is itself a credibility feature.

## Open-question rails (no verified data — investigate before building)

No verified volume/indexability found for: **L402, Skyfire, Nevermined, Payman,
Catena, Halliday, and direct (non-x402) stablecoin agent transfers.** This is
*absence of evidence, not evidence of absence.* Before committing build effort to
any, answer: (a) does it settle observably on-chain? (b) is there real volume?
Direct stablecoin transfers are the trickiest — without the x402 marker, agent
vs. human attribution may be impossible.

## The spine: wash-filtering IS the product

Independently re-confirmed (Artemis, Chainalysis): **~48% of x402 transactions and
~81% of volume were gamed as of Dec 2025 (95% at the December peak); genuine flow
~$14K/day.** Headline 30-day volume diverges wildly by source (x402.org ~$24M vs
Allium ~$3M vs Artemis-filtered ~$1.6M). Separating real commerce from PING-style
pay-to-mint speculation is the core differentiator — and matches our own audit
(67% test-rig volume, 0.58% active-legitimate sellers).

## Concrete next tasks

- [ ] `relayer_registry.json`: add **Polygon** facilitator relayer addresses
      (Polygon Mainnet/Amoy facilitators + ThirdWeb, x402.rs, Pay.AI, Corbits,
      Questflow). Wire an EVM indexer instance for Polygon (USDC contract +
      chain id 137).
- [ ] Add **Avalanche** + **Sei** relayer sets and indexer instances.
- [ ] **AP2 coverage check**: pick a known a2a-x402 settlement, confirm it lands
      in our x402 Base/Polygon settlement table with no special handling.
- [ ] Extend `daily_snapshot.py` / reconciliation to the new chains (same
      pattern as Base/Solana; reconcile each new chain against x402scan).
- [ ] Add a short "coverage & blind spots" section to any public-facing output
      stating what's indexed vs. structurally invisible.

## Sources (verified set)
Chainalysis (x402 100M on Base) · tftc.io (Coinbase-reported $50M/165M/69K agents)
· Artemis via Cryptopolitan/MEXC (wash-volume filter) · Polygon agentic docs
(x402 live) · Google `a2a-x402` spec v0.1 · Coinbase CDP (x402 = AP2's first
extension) · Stripe SPT docs (ACP card settlement). Full list in the workflow
transcript.
