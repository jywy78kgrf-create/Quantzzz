# Roadmap Tasks — agentic-commerce-index

Trackable checklist. Rationale/sources live in `COVERAGE_ROADMAP.md`.
Order is priority order. Check items off as they land.

---

## P0 — deploy staged fixes (do first, in a session connected to this repo)
- [ ] Apply **keyed Base RPC** change (`daily_snapshot.py` reads `X402_BASE_RPC`;
      workflow passes it). Reference commit in old repo: `a9a9adc12`.
- [ ] Apply **Node-24 action bumps** in `.github/workflows/daily-index.yml`
      (`checkout@v5`, `setup-python@v6`; keep `cache@v4`). Deadline: before
      Node 20 removal **Sept 16, 2026**.
- [ ] Add repo secret **`X402_BASE_RPC`** = free Base RPC URL (Alchemy/QuickNode).
- [ ] Manual-run the workflow; confirm green + a snapshot commit lands.

## P1 — x402-Polygon (highest-yield new coverage)
- [ ] Gather Polygon facilitator **relayer addresses** (Polygon Mainnet/Amoy
      facilitators + ThirdWeb, x402.rs, Pay.AI, Corbits, Questflow).
- [ ] Add them to `data/indexer/relayer_registry.json` under a `polygon` key.
- [ ] Stand up an EVM indexer instance for Polygon (USDC contract on Polygon,
      chain id 137; reuse `index_base.py` logic — it's chain-parameterizable).
- [ ] Empirically probe first (as we did for Base/Solana): confirm the
      AuthorizationUsed/Transfer signal + a keyed Polygon RPC's getLogs limits.
- [ ] Reconcile Polygon output vs x402scan (mirror `reconcile.py`); require the
      same PASS bar (no false negatives; validate surplus on-chain).
- [ ] Fold Polygon into `daily_snapshot.py` + the daily workflow.

## P2 — x402-Avalanche + x402-Sei (complete the EVM footprint)
- [ ] Relayer sets for Avalanche + Sei → `relayer_registry.json`.
- [ ] Indexer instances (USDC contract + chain id per chain).
- [ ] Probe → reconcile → fold into daily snapshot, same pattern.

## P3 — AP2 coverage verification (no build, just prove it)
- [ ] Take a known `a2a-x402` settlement; confirm it appears in our x402
      settlement table (Base/Polygon) with **no special handling**.
- [ ] Document the result in `COVERAGE_ROADMAP.md` (AP2 = captured).
- [ ] Set a periodic re-check: has AP2 added any **non-x402** crypto rail?

## Ongoing — keep coverage current
- [ ] New x402 chains as they launch → add relayer set + indexer instance.
- [ ] Add a public-facing **"coverage & blind spots"** line to any output:
      what's indexed (x402 all chains, incl. AP2-via-x402) vs. structurally
      invisible (ACP/card rails, Lightning/L402 off-chain).

---

## Investigate-before-building (open questions — don't assume zero)
- [ ] **L402/Lightning** — real agentic volume? Observable only at channel
      open/close, or effectively invisible?
- [ ] **Direct (non-x402) stablecoin agent transfers** — volume, and can they be
      attributed to agents at all without the x402 marker?
- [ ] **Skyfire, Nevermined, Payman, Catena, Halliday** — do any settle
      observably on-chain with real volume worth indexing?

## Explicitly OUT of scope (structurally unobservable — track journalistically)
- Stripe/OpenAI **ACP** (Shared Payment Tokens → Visa/card rails, off-ledger).
- **Card-settled AP2** (non-crypto path).
- **L402/Lightning** payments in private channels (pending P-investigation).

---

## Product horizon (post-coverage, not now)
- [ ] Migrate running job + DB off GitHub Actions to a small VPS + Postgres
      (see `DEPLOY.md` Option B) when data grows / you want to query it.
- [ ] Query/serving layer (API or dashboard) on top — the "index as a product."
- [ ] Pre-launch: fresh Base (and maybe Solana) **paid-delivery** round — run
      it right before publishing the report, since delivery data is perishable.
