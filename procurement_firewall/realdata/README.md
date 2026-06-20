# Real-data validation harness

Tests the firewall against a **real** public-procurement slice, scoped to
**honest-mistake / off-policy detection** — explicitly NOT deliberate-adversary
fraud, and with **no ground-truth-labeled real fraud** (none is public).

## Run

```bash
cd procurement_firewall
python realdata/fetch_usaspending.py     # cache ~10k real awards (skips if cached)
python realdata/derive_mandate.py        # derive a mandate from the data's distributions
python realdata/real_validate.py --judge both   # Test A + Test B; writes eval/REPORT_REAL.md
```

`--judge heuristic` (default) is free; `--judge both` also runs the Anthropic
judge (uses your `ANTHROPIC_API_KEY`; real-spend FP is estimated on a
`--llm-sample` of gate-allowed rows to bound cost, responses cached).

## What the pieces are

- `fetch_usaspending.py` — pulls a cached slice from USAspending.gov: contract
  awards, NAICS 541512 (Computer Systems Design Services), FY2024, ~10,000 rows.
  Provenance written to `datasets/real/PROVENANCE.json`.
- `derive_mandate.py` — derives `mandates/usaspending_541512_fy2024.json` from the
  data's own distributions (amount cap = p99.5; vendor allowlist = top-100;
  category = the slice's NAICS). Primitives with no supporting data (approval
  tiers, three-way match) and per-program-cadence primitives (rate limit,
  structuring) are deliberately omitted — see the script docstring.
- `datasets/real/SEED_TAXONOMY.md` — the plain-English honest-error taxonomy the
  seed cases were authored from.
- `datasets/real/seed_honest_errors.jsonl` — 54 seeded honest-error cases (9 each
  of E1–E6), authored by a **separate process that did not see the judge prompt**
  (independence reduced, not eliminated — both are LLM-reasoned).
- `real_validate.py` — Test A (false positives on real spend, decomposed by rule)
  and Test B (recall on seeded errors, per judge, with the semantic delta).

## Headline (see `eval/REPORT_REAL.md` for the full, current numbers)

The number that matters is the **false-positive rate against real legitimate
spend**. It is **not** small: the deterministic gate flags ~1-in-5 real awards
(dominated by the vendor-allowlist long tail), and the LLM judge's "escalate when
unsure" posture over-fires on terse real descriptions. The seeded test shows the
judge does recover the off-objective honest mistakes the gate cannot — at a real
false-positive cost. Read both numbers together; that's the tradeoff.

## Limitations

Stated in full at the bottom of `eval/REPORT_REAL.md`. In short: honest-mistake +
false-positive realism only; not adversaries; no real fraud labels; allowlist FP
reflects slice breadth; disabled primitives untested; seed/judge correlation
reduced but not eliminated.
