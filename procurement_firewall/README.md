# Off-Objective Procurement Firewall

A control layer that sits in front of an autonomous/agentic procurement system
and decides whether a proposed purchase order or invoice payment is **ALLOWED**,
**DENIED**, or **ESCALATED** to a human — judged against a hand-authored
**spending mandate**.

It exists because agents that move money fail in a specific way: they take an
action that passes every quantifiable limit but runs against the mandate's
*purpose* — a duplicate payment, a PO split to slip under an approval cap, an
approved vendor billed for an off-contract item, an instruction injected into a
memo. Static approval rules miss these; a pure-LLM check is unreliable and can be
argued out of its own judgment. This firewall combines a frozen deterministic
floor with an advisory semantic judge, and — crucially — **measures** what the
combination buys on an independently-authored adversarial benchmark.

## Architecture: two layers, deliberately different materials

```
                 transaction ──▶ DeterministicGate ──┬── DENY ───────────▶ DENIED   (final)
                                  (frozen, no LLM)    │
                                                      ├── ESCALATE ──────▶ ESCALATED (deny-by-default:
                                                      │                              no rule covers it)
                                                      └── ALLOW ──▶ SemanticJudge ──┬── flag ─▶ ESCALATED
                                                                    (advisory)      └── pass ─▶ ALLOWED
```

**1. `DeterministicGate`** (`firewall/gate.py`) — pure evaluation of quantifiable
fields. No LLM, no reasoning, cannot be argued with. A **DENY is final**. It is a
frozen set of *generic* primitives; per-mandate behaviour comes **only** from the
config, never from new gate code. Primitives:

- amount cap per PO
- vendor allowlist / spend-category allowlist
- approval-tier rule (`amount > threshold` requires *k* distinct approvers)
- rate limit (POs per period)
- duplicate detection (same vendor + amount + ~invoice id within a window)
- split/structuring detection (multiple sub-cap POs to one vendor summing past a cap)
- three-way-match check (PO ↔ receipt ↔ invoice) where data exists
- **opt-in** (inert unless configured): vendor blocklist, per-vendor cumulative
  spend cap over a window, required-field completeness, and currency discipline
  (a foreign-currency transaction can't be compared to the caps, so it escalates)

**2. `SemanticJudge`** (`firewall/judge/`) — **advisory only**. Detects
off-objective intent that passes every deterministic field. It can *never* allow
an action the gate denied and *never* override a DENY; the strongest thing it can
do is escalate a gate-allowed action. Pluggable behind one interface
`evaluate(objective, transaction) -> {flag, reason}`, with two implementations:

- `HeuristicJudge` (`judge/heuristic.py`) — a transparent, deterministic, and
  deliberately **weak** keyword baseline. It sets the floor the LLM must beat.
- `AnthropicJudge` (`judge/llm.py`) — calls the Anthropic API
  (`claude-sonnet-4-6`) at temperature 0, with bounded retries and an on-disk
  response cache (so re-runs are cheap and reproducible). Its prompt lives in a
  separate file (`firewall/prompts/judge_system.txt`) and the transaction is
  passed as clearly-fenced **untrusted data** to blunt prompt injection.

**Final decision:** `ALLOWED` iff the gate ALLOWs **and** the judge PASSes. Gate
DENY → DENIED. Judge flag on a gate-allowed item → ESCALATED.

## Hard constraints (these prevent the known failure modes)

- **Deny-by-default.** A transaction matching no policy rule (unknown type, a
  dimension the mandate is silent on, a foreign currency, a missing required
  field) **ESCALATES** to a human. The system never improvises an allow.
- **The gate is frozen, generic primitives.** New policy = config change only.
- **The judge is never trained/tuned on the transaction log it polices.**
- **Every ESCALATE/DENY emits a signable record** (`firewall/audit.py`):
  who/what/why/when plus a SHA-256 content hash, appended to an audit log.
- **All free-text fields are treated as untrusted instruction surfaces.** The
  judge prompt is hardened against text that tells it to ignore the mandate.

## The benchmark (this is the product's truth test)

Four suites, each an **independent input** authored against the schema and a
mandate, *never* against the judge code (see "independence" below). Labels:
`ok` (on-objective, passes every primitive → ALLOW), `det_off` (breaks a
quantifiable primitive → the gate stops it), `sem_off` (passes **every**
primitive but violates the mandate's purpose → only the judge can catch it).
Positive class = "should be stopped". The **semantic delta** counts off-objective
rows the gate provably cannot catch (it ALLOWed them) that the judge escalated.

| Suite | rows | gate recall | heuristic P / R / FP | LLM P / R / FP | sem-delta (LLM) |
|---|---|---|---|---|---|
| `platform_infra_v1` (easy anchor) | 180 | 0.495 | .980 / .883 / 2 | 1.00 / 1.00 / 0 | 56 |
| `platform_infra_hard` | 140 | 0.353 | .935 / .682 / 4 | .934 / 1.00 / 6 | 55 |
| `field_marketing` (held-out 2nd mandate) | 120 | 0.361 | **.596 / .819 / 40** | .923 / 1.00 / 6 | 46 |
| `injection_battery` | 50 | 0.000 | injection 46/50 | **injection 50/50** | 50 |

_Numbers from the committed run in `eval/runs/`; full breakdown in `eval/REPORT.md`.
Reproducible at temperature 0._

### What the benchmark actually shows

- **The deterministic floor is exact and free.** It catches 100% of `det_off`
  with zero false positives, by construction — arithmetic, not a model claim.
  But its recall on the off-objective class is only ~0.35–0.50, because it
  provably cannot see `sem_off`. That gap is the judge's job.
- **The semantic layer recovers a large, provable delta** (up to 55–56 rows the
  gate cannot catch).
- **The hard suite discriminates.** The easy suite saturates (LLM 1.00/1.00),
  which means it isn't informative. On the hard suite the LLM keeps full recall
  but pays a real precision cost (6 false positives) — you can finally *see* the
  tradeoff. Those 6 are not random: they cluster on genuinely ambiguous boundary
  cases (a 1-year Savings Plan as "prepayment", staging-vs-production, seat
  backfill as "expansion"). Under deny-by-default, escalating those to a human is
  the intended behaviour, not a bug.
- **Generalization is the headline.** On a held-out *second* mandate (field
  marketing, a different domain where travel/ads are now *allowed*), the keyword
  heuristic **collapses to 40/48 false positives** — its infra-baked keywords are
  exactly backwards here — while the LLM, which reads the actual objective,
  holds recall 1.00 at 6 FP. This is the cleanest evidence that the deterministic
  gate is generic config (not code) and that the semantic layer generalizes.
- **Injection resistance:** the LLM escalated **50/50** injected off-objective
  rows across 11 attack tactics; the heuristic missed 4 of the subtler ones.

### Dataset independence (why the scores aren't a tautology)

Every dataset was authored by a **separate process given only the schema
(`datasets/SCHEMA.md`, `datasets/SCHEMA_HARD.md`) and the mandate file** — never
the gate or judge implementation. If the same author wrote both the judge and its
test cases, a high score would be circular. Two guards enforce the boundary:
`eval/validate_dataset.py` and `tests/test_datasets.py` assert that **every
`sem_off` row genuinely passes the gate** (else it is mislabeled `det_off` and
would inflate the delta) and every `det_off` row is genuinely caught.

## Layout

```
procurement_firewall/
├── firewall/
│   ├── models.py            # Mandate, Transaction, Verdict, results
│   ├── gate.py              # DeterministicGate (frozen primitives)
│   ├── firewall.py          # composes gate + judge; enforces the invariants
│   ├── audit.py             # signable who/what/why/when records
│   ├── config_validation.py # mandate config linting
│   ├── loaders.py
│   ├── prompts/judge_system.txt   # LLM judge prompt (iterate here)
│   └── judge/{base,heuristic,llm}.py
├── mandates/                # hand-authored mandates (2 domains)
├── datasets/                # 4 independently-authored labeled sets + schemas
├── eval/
│   ├── harness.py           # confusion matrix, semantic delta, breakdowns, failures
│   ├── report.py            # markdown report generator
│   ├── validate_dataset.py  # gate-consistency guard
│   ├── suites.json          # the benchmark definition
│   ├── REPORT.md            # generated report (committed)
│   └── runs/                # persisted runs + history.jsonl (committed)
├── cli.py                   # mandate + batch -> per-transaction verdicts
├── evaluate.py              # the end-to-end multi-suite eval
├── smoke_test.sh            # no-API-key end-to-end check
└── tests/
```

## Usage

```bash
cd procurement_firewall
pip install -r requirements.txt          # only needed for the LLM judge + tests

# Verdicts for a batch (heuristic judge — no API key needed):
python cli.py --mandate mandates/platform_infra_2026.json \
              --transactions datasets/transactions.jsonl --judge heuristic

# The full benchmark, both judges (LLM needs ANTHROPIC_API_KEY in the env):
python evaluate.py                       # writes eval/REPORT.md + eval/runs/

pytest -q                                # 53 tests: invariants, primitives, mock LLM, datasets
bash smoke_test.sh                       # end-to-end, no API key
```

If `ANTHROPIC_API_KEY` is unset (or the SDK is missing), `evaluate.py` still runs
end to end: it reports the heuristic fully and marks the LLM judge `UNAVAILABLE`.

## What is real, and what is not (read this honestly)

**Real:**
- **The deterministic floor.** 100% of `det_off` caught, 0 false positives, by
  construction. Arithmetic, not a claim.
- **The structural semantic delta.** There is a class of off-objective actions
  the gate's recall on is provably zero; the judge recovers most of them. That a
  non-zero delta exists is an architectural result, not a benchmark number.
- **Generalization across mandates** and **injection resistance** are
  demonstrated on independent sets the judge author did not write.

**Not a real accuracy claim:**
- The precision/recall numbers are measured on **small, self-authored** sets
  (~490 rows total, two mandates). They are an iteration signal — "did this
  prompt change help or hurt" — **not** a benchmark of real-world procurement
  traffic. Absolute scores would change with different mandates, larger sets, and
  adversaries who didn't write to this schema.
- The datasets are independent of the *judge*, but both the dataset authors and
  the judge are LLMs reasoning about the same explicit objective, so their notions
  of "off-objective" correlate; that correlation flatters the score.

**The open question (partially answered):**
- *Does the LLM judge raise catch-rate without raising false positives?* On these
  sets: it raises recall to 1.00 across suites and beats the heuristic decisively
  on generalization, but it does carry residual false positives on genuinely
  ambiguous boundary cases — which deny-by-default deliberately routes to a human.
  Whether that holds against human-written, deliberately ambiguous adversaries,
  and across many mandates, is the next thing to test.

## Out of scope (resisting scope creep)

No auto-derivation of mandates from logs/documents (that is Phase 2), no web app /
dashboard, no multi-tenant infra, no integration with live procurement systems.
This is the firewall + its measurement, proving the two-layer design measurably
catches off-objective procurement actions with the deterministic floor doing most
of the work.
