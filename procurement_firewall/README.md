# Off-Objective Procurement Firewall — Phase 1

A control layer that sits in front of an autonomous/agentic procurement system
and decides whether a proposed purchase order or invoice payment is **ALLOWED**,
**DENIED**, or **ESCALATED** to a human — judged against a hand-authored
**spending mandate**.

It exists because agents that move money fail in a specific way: they take an
action that passes every quantifiable limit but runs against the mandate's
*purpose* — a duplicate payment, a PO split to slip under an approval cap, an
approved vendor billed for an off-contract item, an instruction injected into a
memo. Static approval rules miss these; a pure-LLM check is unreliable and can be
argued out of its own judgment.

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
config, never from new gate code:

- amount cap per PO
- vendor allowlist
- spend-category allowlist
- approval-tier rule (`amount > threshold` requires *k* distinct approvers)
- rate limit (POs per period)
- duplicate detection (same vendor + amount + ~invoice id within a window)
- split/structuring detection (multiple sub-cap POs to one vendor summing past a
  cap within a window)
- three-way-match check (PO ↔ receipt ↔ invoice consistency) where data exists

**2. `SemanticJudge`** (`firewall/judge/`) — **advisory only**. Detects
off-objective intent that passes every deterministic field. It can *never* allow
an action the gate denied and *never* override a DENY; the strongest thing it can
do is escalate a gate-allowed action. It is pluggable behind one interface
`evaluate(objective, transaction) -> {flag, reason}`, with two implementations:

- `HeuristicJudge` (`judge/heuristic.py`) — a transparent, deterministic, and
  deliberately **weak** keyword baseline. It sets the floor the LLM must beat.
- `AnthropicJudge` (`judge/llm.py`) — calls the Anthropic API
  (`claude-sonnet-4-6`). Its prompt lives in a separate file
  (`firewall/prompts/judge_system.txt`) so it can be iterated without touching
  code, and the transaction is passed as clearly-fenced **untrusted data** to
  blunt prompt injection.

**Final decision:** `ALLOWED` iff the gate ALLOWs **and** the judge PASSes. Gate
DENY → DENIED. Judge flag on a gate-allowed item → ESCALATED.

## Hard constraints (these prevent the known failure modes)

- **Deny-by-default.** A transaction matching no policy rule (unknown type, or a
  dimension the mandate is silent on) **ESCALATES** to a human. The system never
  improvises an allow.
- **The gate is frozen, generic primitives.** New policy = config change only.
- **The judge is never trained/tuned on the transaction log it polices.** It
  would learn to wave through the subtle violations, destroying its only value.
- **Every ESCALATE/DENY emits a signable record** (`firewall/audit.py`):
  who/what/why/when plus a SHA-256 content hash, appended to an audit log, so any
  action is attributable after the fact.
- **All free-text fields (memos, descriptions) are treated as untrusted
  instruction surfaces.** The judge prompt is hardened against text that tells it
  to ignore the mandate.

## Layout

```
procurement_firewall/
├── firewall/
│   ├── models.py            # Mandate, Transaction, Verdict, results
│   ├── gate.py              # DeterministicGate (frozen primitives)
│   ├── firewall.py          # composes gate + judge; enforces the invariants
│   ├── audit.py             # signable who/what/why/when records
│   ├── loaders.py           # mandate / transaction loading
│   ├── prompts/
│   │   └── judge_system.txt # LLM judge prompt (iterate here)
│   └── judge/
│       ├── base.py          # SemanticJudge interface
│       ├── heuristic.py     # weak transparent baseline
│       └── llm.py           # Anthropic claude-sonnet-4-6 judge
├── mandates/
│   └── platform_infra_2026.json   # hand-authored mandate (Phase 1: no auto-derivation)
├── datasets/
│   ├── SCHEMA.md            # the contract the dataset is authored against
│   └── transactions.jsonl   # labeled set — an INDEPENDENT input (see below)
├── eval/
│   ├── harness.py           # confusion matrix, precision/recall, semantic delta
│   └── runs/                # one JSON per run + history.jsonl (committed)
├── cli.py                   # mandate + batch -> per-transaction verdicts
├── evaluate.py              # the end-to-end eval entry point
└── tests/
```

## Usage

```bash
cd procurement_firewall
pip install -r requirements.txt          # only needed for the LLM judge + tests

# Verdicts for a batch, with the heuristic judge:
python cli.py --mandate mandates/platform_infra_2026.json \
              --transactions datasets/transactions.jsonl \
              --judge heuristic

# Same, with the LLM judge (needs ANTHROPIC_API_KEY in the environment):
python cli.py --mandate mandates/platform_infra_2026.json \
              --transactions datasets/transactions.jsonl \
              --judge llm

# The eval harness — runs both judges, prints confusion matrix + semantic delta:
python evaluate.py

pytest -q                                 # the invariants + gate primitives
```

If `ANTHROPIC_API_KEY` is not set (or the SDK is missing), `evaluate.py` still
runs end to end: it reports the heuristic fully and marks the LLM judge
`UNAVAILABLE` with the reason, rather than crashing.

## The eval method (this is the product's truth test)

The labeled dataset (`datasets/transactions.jsonl`) has three classes:

- `ok` — on-objective **and** passes every deterministic rule (should be ALLOWED).
- `det_off` — violates a quantifiable primitive (the gate alone should stop it).
- `sem_off` — passes **every** deterministic primitive but runs against the
  mandate's purpose (only the semantic judge can catch it). **These are the
  point.**

The positive class is "should be stopped" = {`det_off`, `sem_off`}. The harness
reports, per judge: a confusion matrix, precision, recall, and the **semantic
delta** — the count of off-objective transactions caught **only** by the semantic
judge on rows the deterministic gate provably cannot catch (gate ALLOWed, judge
escalated). It also reports the **deterministic floor** (gate alone) so the
marginal value of the semantic layer is explicit. Every run is persisted to
`eval/runs/` and summarised in `eval/runs/history.jsonl` for cross-run comparison
— that is the iteration loop: tweak the judge prompt → re-run → did false
positives climb as recall rose?

### Dataset independence (why the scores aren't a tautology)

The adversarial cases were authored **independently of the judge logic**. The
dataset was written by a separate process given only `datasets/SCHEMA.md` and the
mandate file — never the gate or judge implementation. If the same author wrote
both the judge and its test cases, a perfect score would be circular and
meaningless. A test (`tests/test_judge_and_harness.py`) enforces the structural
invariant that **every `sem_off` row genuinely passes the deterministic gate** —
otherwise it would be mislabeled `det_off` and the semantic delta would be
inflated.

## What is real, and what is not (read this honestly)

**Real:**
- **The deterministic floor.** The gate catches 100% of the `det_off` class with
  zero false positives, by construction — these are quantifiable rule violations,
  and the result is not a model "claim", it is arithmetic. See the latest
  `eval/runs/` entry for the exact matrix.
- **The structural semantic delta.** There is a class of off-objective actions
  (`sem_off`) that pass *every* deterministic check. The gate's recall on that
  class is provably **zero** — no amount of config can catch them. The semantic
  delta is the count a judge recovers from that provably-uncatchable set. That a
  non-zero delta exists at all is a real, architectural result: the second layer
  buys catch-rate the first layer cannot.

**Not a real accuracy claim:**
- The precision/recall numbers are measured on a **small, self-authored** set
  (~180 rows, one mandate). They are an internal iteration signal, **not** a
  benchmark and **not** a claim about real-world procurement traffic. The
  absolute scores would change with a different mandate, different adversaries,
  or a larger set. Treat them as "did this prompt change help or hurt", not as
  "the firewall is X% accurate".

**The open question (Phase 1 does not answer it):**
- Does the LLM judge raise the catch-rate **without** raising false positives on
  the `ok` class? The heuristic baseline trades recall for some false positives;
  the LLM judge is supposed to recover more `sem_off` cases while leaving genuine
  on-objective renewals alone. Whether it actually does — across mandates, and
  against adversaries who didn't write the prompt — is the question the
  iteration loop (and Phase 2) is built to investigate.

## Out of scope for Phase 1 (resisting scope creep)

No auto-derivation of mandates from logs/documents (that is Phase 2), no web UI,
no multi-tenant infra, no integration with real procurement systems, no second
vertical. Phase 1 proves the two-layer firewall measurably catches off-objective
procurement actions on a labeled set, with the deterministic floor doing most of
the work.
