# Real-Data Validation — Procurement Firewall

_Generated 2026-06-20T19:49:04.986856+00:00 · mandate `MND-USASPENDING-541512-FY2024` · judge mode `both`_

**Scope:** honest-mistake / off-policy detection and false-positive realism on real public procurement data. This does **NOT** test deliberate adversaries and uses **no ground-truth-labeled real fraud** (none is public). See limitations.

## Data provenance
- Source: USAspending.gov API v2 /api/v2/search/spending_by_award/
- Filters: NAICS 541512 (Computer Systems Design Services), award types ['A', 'B', 'C', 'D'], action window 2023-10-01…2024-09-30, sort Start Date desc
- Rows: 10000 (all real, legitimate federal awards)
- Fetched: 2026-06-20T19:24:35.994634+00:00

## TEST A — false positives on real legitimate spend (headline)

Every one of the **10,000** rows is a real, legitimate award, so every flag is effectively a false positive.

- **Deterministic gate false-positive rate: 22.8%** (2,280/10,000) — denied 2,280, deny-by-default 0.

Decomposed by which rule fired (a row can trip more than one):

| rule | rows flagged | FP rate |
|---|---|---|
| vendor_allowlist | 2,051 | 20.5% |
| duplicate | 196 | 2.0% |
| amount_cap | 49 | 0.5% |

### Semantic judge — `heuristic_v1`
- Run on all **7,720** gate-allowed real rows: **14.1%** of all rows flagged (1413/7720 of gate-allowed). Errors: 0.
- Top flag reasons:
    - (1412×) memo/description suggests spend that may run against the mandate's run
    - (1×) free-text field contains instruction-injection / reviewer-steering lan

### Semantic judge — `anthropic_claude-sonnet-4-6`
- Estimated on a random sample of **250** gate-allowed real rows (to bound API cost): **30.0%** flagged (75/250). Errors: 0.
- Top flag reasons:
    - (21×) The transaction's described purpose is 'End User Hardware (EUHW) Devic
    - (12×) The transaction describes 'End User Hardware (EUHW) Devices as a Servi
    - (9×) The transaction's described purpose is 'End User Hardware (EUHW Device
    - (4×) The memo and description are too vague to confirm the purpose is clear
    - (2×) The memo and description provide no specific information about the act
    - (2×) The memo and description provide insufficient detail to confirm the pu

## TEST B — recall on seeded honest-mistake cases

54 honest-error cases (authored independently of the judge — see independence note) injected into the real haystack.

- **Deterministic gate alone — recall: 70.4%** (catches the quantitative errors E1–E4, E6; by design catches no E5).

| error type | caught by gate / total |
|---|---|
| E1 amount over cap | 9/9 |
| E2 vendor off allowlist | 9/9 |
| E3 wrong category | 9/9 |
| E4 duplicate | 2/9 |
| E5 off-objective purpose | 0/9 |
| E6 wrong currency | 9/9 |

### + semantic judge `heuristic_v1`
- **Overall recall (gate ∪ judge): 77.8%**
- **Semantic delta** (seeds the gate let through but this judge caught): **4** — almost entirely the E5 off-objective cases.
- Confusion (seed=should-catch, real=should-pass; FP/TN = the gate's flags on real): TP=42, FN=12, FP=2,280, TN=7,720.

| error type | caught / total | recall |
|---|---|---|
| E1 amount over cap | 9/9 | 100% |
| E2 vendor off allowlist | 9/9 | 100% |
| E3 wrong category | 9/9 | 100% |
| E4 duplicate | 2/9 | 22% |
| E5 off-objective purpose | 4/9 | 44% |
| E6 wrong currency | 9/9 | 100% |

### + semantic judge `anthropic_claude-sonnet-4-6`
- **Overall recall (gate ∪ judge): 88.9%**
- **Semantic delta** (seeds the gate let through but this judge caught): **10** — almost entirely the E5 off-objective cases.
- Confusion (seed=should-catch, real=should-pass; FP/TN = the gate's flags on real): TP=48, FN=6, FP=2,280, TN=7,720.

| error type | caught / total | recall |
|---|---|---|
| E1 amount over cap | 9/9 | 100% |
| E2 vendor off allowlist | 9/9 | 100% |
| E3 wrong category | 9/9 | 100% |
| E4 duplicate | 3/9 | 33% |
| E5 off-objective purpose | 9/9 | 100% |
| E6 wrong currency | 9/9 | 100% |

> The contrast that matters: pair each judge's seeded **recall here** with its **real-spend false-positive rate in Test A**. Higher recall on E5 comes with a higher false-positive rate on legitimate spend — the precision/recall tradeoff, on real data.

## Honest limitations

- **This validates honest-mistake detection and false-positive realism — not fraud.** It does not test deliberate adversaries who adapt to evade the firewall.
- **No ground-truth-labeled real fraud is used** (none is public); the real rows are assumed-legitimate, which is why their flags are read as false positives.
- **Allowlist FP reflects slice breadth.** The vendor allowlist is the top-100 vendors of a multi-agency slice; real spend has a long vendor tail, so off-allowlist FP is large here. A genuinely narrow single-program mandate would cover ~all its vendors. This is a property of the test scope, not only of the primitive.
- **The amount-cap FP is whatever percentile we picked** (p99.5 ⇒ ~0.5% over by construction); the real lesson is that any fixed cap false-positives on the heavy right tail of government spend.
- **Disabled primitives:** approval tiers and three-way match (no approver / receipt data in award records) and rate-limit / structuring (per-program cadence controls, not meaningful across a 49-agency aggregate). Their real-world FP is untested here.
- **Author-correlation is reduced, not eliminated.** The seed cases were written from a plain-English taxonomy without seeing the judge prompt, by a separate agent — but both the seeds and the judge are LLM-reasoned, so their notions of 'off-objective' still partly correlate.

