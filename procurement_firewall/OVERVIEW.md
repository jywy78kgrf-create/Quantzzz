# Tollgate — Off-Objective Firewall for Autonomous Procurement (one-page brief)

## What it is
A control layer that sits in front of an autonomous / agentic procurement system
and decides, per proposed action (purchase order or invoice payment), whether to
**ALLOW**, **DENY**, or **ESCALATE** it to a human — judged against a hand-authored
**spending mandate**. It exists because agents that move money fail in a specific
way: they take an action that passes every quantifiable limit but violates the
mandate's *purpose* (duplicate payment, a PO split to slip under an approval cap,
an approved vendor billed for an off-contract item, an instruction injected into a
memo). Static approval rules miss these; a pure-LLM check is unreliable and can be
argued out of its own judgment. (Codename for the productized version: "Tollgate".)

## Architecture — two layers, deliberately different materials
1. **DeterministicGate** — pure evaluation of quantifiable fields. No LLM, no
   reasoning, cannot be argued with. A **DENY is final**. Frozen, *generic*
   primitives; all per-mandate behavior comes from config, never new gate code.
   Primitives: amount cap; vendor allowlist; category allowlist; approval tiers
   (amount > threshold needs k distinct approvers); rate limit; duplicate
   detection (vendor + amount + ~invoice id within window); split/structuring
   detection (sub-cap POs to one vendor summing past a cap); three-way match
   (PO↔receipt↔invoice). Opt-in (inert unless configured): vendor blocklist,
   per-vendor period spend cap, required-field completeness, currency discipline.
2. **SemanticJudge** — ADVISORY only. Detects off-objective intent that passes
   every deterministic field. It can never allow what the gate denied and never
   overturn a DENY; the strongest thing it can do is escalate a gate-allowed
   action. Pluggable interface `evaluate(objective, transaction) -> {flag, reason}`
   with two implementations: a transparent **heuristic** baseline (weak, keyword)
   and an **Anthropic claude-sonnet-4-6** judge (temperature 0, retries, response
   cache; hardened prompt in a separate file; transaction passed as fenced
   untrusted data to blunt prompt injection).

**Decision rule:** ALLOWED iff gate ALLOWs AND judge PASSes. Gate DENY → DENIED.
Gate "no rule covers this" → ESCALATED (deny-by-default). Judge flag on a
gate-allowed item → ESCALATED.

**Hard constraints (prevent known failure modes):** deny-by-default; the gate is
frozen generic primitives (policy = config); the judge is never trained/tuned on
the log it polices; every ESCALATE/DENY emits a signed who/what/why/when record
(SHA-256); all free text is treated as an untrusted instruction surface.

## The eval is the product's truth test
Four **independently-authored** suites (datasets written only from a schema +
mandate, never the judge code; a test enforces that every `sem_off` row genuinely
passes the gate so the "semantic delta" can't be faked). Labels: `ok`
(on-objective, passes everything), `det_off` (breaks a quantifiable rule → gate
stops it), `sem_off` (passes every rule but violates purpose → only the judge can
catch it). Positive class = "should be stopped". **Semantic delta** = off-objective
rows the gate provably cannot catch that the judge escalated.

Reproducible run (temperature 0), `gate recall | heuristic P/R/FP | LLM P/R/FP`:
- platform_infra (easy anchor, 180): 0.50 | .98/.88/2 | 1.00/1.00/0 — delta 56
- platform_infra_HARD (140): 0.35 | .94/.68/4 | .93/1.00/6 — delta 55
- field_marketing (held-out 2nd mandate, 120): 0.36 | **.60/.82/40** | .92/1.00/6 — delta 46
- injection_battery (50): — | 46/50 resisted | **50/50 resisted**

Read: the deterministic floor catches 100% of `det_off` at zero FP by construction
but is provably blind to `sem_off`; the judge recovers a large delta. On a *held-out
second mandate* the keyword heuristic collapses (40/48 false positives — its
infra-baked keywords are wrong for marketing) while the LLM generalizes because it
reads the actual objective. The LLM's residual false positives cluster on genuinely
ambiguous boundary cases (prepay-vs-commitment, staging-vs-production), which
deny-by-default intends to route to a human.

## What's real vs. not (stated honestly)
**Real:** the deterministic floor (arithmetic, not a model claim); the structural
semantic delta (a class of violations the gate cannot catch, recovered by the
judge); cross-mandate generalization and injection resistance, shown on sets the
judge author did not write. **Not a real accuracy claim:** the P/R numbers are on
small (~490 rows, 2 mandates) self-authored sets — an iteration signal, not a
benchmark; and because both the dataset authors and the judge are LLMs reasoning
about the same objective, their notions of "off-objective" correlate and flatter
the score.

## Nature of the thing (important framing)
It is a **guardrail / action-approval layer**, not an agent (no loop, tools, or
memory) and not an agent harness. The mechanism is **bounds-checking a proposed
action** — intent-agnostic, so it catches honest agent *mistakes* and deliberate
*misuse* identically (both manifest as out-of-bounds actions). It gates *actions*,
not the agent's reasoning; it has no opinion on in-bounds-but-strategically-bad
decisions. The two-layer pattern is domain-general: swap procurement primitives
for recipient allowlists / blast-radius caps / resource scopes and it becomes an
"inappropriate agent action" firewall for email, data deletion, access grants,
publishing, trades. Procurement is the first vertical because money is the most
legible, highest-stakes instance.

## Deployment & packaging
Best shape for a financial control is **hybrid**: enforcement runs in the
customer's environment (embedded SDK / data plane — sensitive data and the payment
critical path stay local, no dependency on our uptime), while a hosted **control
plane** holds the subscription, mandate authoring, dashboards, audit, and pushed
judge/prompt updates. Availability argument: the deterministic gate runs locally
and fails closed; the judge is advisory, so if its endpoint is down we degrade to
ESCALATE without taking down the floor. Go-to-market wedge: an **offline audit**
(replay a redacted PO-log export, show the off-objective spend that slipped through
current controls), which converts into the embedded subscription. Open-core option:
open-source the gate, monetize the judge + control plane. Buyer: Controller / VP
Finance / Head of AP / internal audit.

## Repo
`procurement_firewall/` — `firewall/` (models, gate, firewall, judge/{heuristic,llm},
prompts/judge_system.txt, audit, config_validation); `mandates/` (2 domains);
`datasets/` (4 independent labeled sets + schemas + validator); `eval/`
(harness, report, suites.json, REPORT.md, runs/); `cli.py`; `evaluate.py`;
`smoke_test.sh`; `tests/` (53 passing). CI runs ruff + smoke test (no API key
needed; LLM covered by mock tests). `python evaluate.py` runs the full benchmark;
`python cli.py …` returns per-transaction verdicts. A separate `tollgate-site/`
holds a static marketing landing page (React/Vite/Tailwind).

## Open questions / next steps
1. Does the LLM judge hold up against **human-written, deliberately ambiguous**
   adversaries (not LLM-authored) and across many mandates? (the real accuracy
   question, unanswered).
2. Phase-2 idea (out of scope so far): **auto-derive mandates** from existing
   policy/logs instead of hand-authoring.
3. ERP/AP/payment **connectors** for inline Mode-2 enforcement (the unglamorous
   integration work between here and revenue).
4. Strategic: **deep on procurement vs. horizontal "action firewall for agents"** —
   the most important product decision.
