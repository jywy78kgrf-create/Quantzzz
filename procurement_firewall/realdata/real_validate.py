#!/usr/bin/env python3
"""Real-data validation harness for the procurement firewall.

Two separate tests, run against a real USAspending slice (see PROVENANCE.json):

  TEST A — false-positive behavior on real, legitimate spend (HEADLINE).
    Every real row is legitimate, so every flag is effectively a false positive.
    Reports the gate FP rate and the judge FP rate, DECOMPOSED by which rule /
    which judge reason fired, so miscalibration is diagnosable.

  TEST B — catch-rate on seeded honest-mistake cases injected into the real
    haystack. Reports recall by error type, the confusion matrix (seed = should
    catch, real = should pass), and the semantic delta (seeds caught ONLY by the
    judge, which the gate let through).

The semantic judge defaults to the transparent heuristic (free, deterministic).
Pass --judge llm (or both) to also run the Anthropic judge; the real-spend FP for
the LLM is estimated on a random sample (--llm-sample, default 250) to bound cost,
while every gate-allowed seed is judged. Results persist to eval/runs/real/ and a
report is written to eval/REPORT_REAL.md.

    python realdata/real_validate.py                 # gate + heuristic
    python realdata/real_validate.py --judge both    # also the LLM (uses your key)
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import sys

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from firewall.gate import DeterministicGate  # noqa: E402
from firewall.judge import AnthropicJudge, HeuristicJudge  # noqa: E402
from firewall.loaders import load_mandate  # noqa: E402
from firewall.models import GATE_ALLOW, Transaction, _parse_ts  # noqa: E402

REAL = HERE / "datasets" / "real" / "usaspending_541512_fy2024.jsonl"
SEEDS = HERE / "datasets" / "real" / "seed_honest_errors.jsonl"
MANDATE = HERE / "mandates" / "usaspending_541512_fy2024.json"
RUNS = HERE / "eval" / "runs" / "real"
REPORT = HERE / "eval" / "REPORT_REAL.md"
CACHE = HERE / "eval" / ".judge_cache.json"


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def build_history(records: list[dict], window_days: int, cap: int = 60) -> None:
    """Attach per-vendor prior-in-window history to each record (for duplicate
    detection). Mutates records in place. Sorted by timestamp within vendor."""
    by_vendor: dict[str, list[dict]] = {}
    for r in records:
        by_vendor.setdefault(r["vendor"], []).append(r)
    for vendor, rows in by_vendor.items():
        rows.sort(key=lambda r: r.get("timestamp") or "")
        for i, r in enumerate(rows):
            ts = _parse_ts(r.get("timestamp"))
            hist = []
            for j in range(i - 1, -1, -1):
                if len(hist) >= cap:
                    break
                pr = rows[j]
                pts = _parse_ts(pr.get("timestamp"))
                if ts and pts and abs((ts - pts).days) > window_days:
                    continue
                hist.append({
                    "id": pr["id"], "vendor": pr["vendor"], "amount": pr["amount"],
                    "invoice_id": pr.get("invoice_id"), "timestamp": pr.get("timestamp"),
                    "type": pr.get("type", "purchase_order"),
                })
            r["history"] = hist


@dataclass
class GatePass:
    n: int
    stopped: int
    denied: int
    escalated: int
    rule_counts: dict
    examples: dict = field(default_factory=dict)


def run_gate(gate: DeterministicGate, txns: list[Transaction]) -> tuple[GatePass, list[bool]]:
    rule_counts: Counter = Counter()
    examples: dict[str, list] = {}
    denied = escalated = 0
    allowed_mask: list[bool] = []
    for t in txns:
        res = gate.evaluate(t)
        if res.status == GATE_ALLOW:
            allowed_mask.append(True)
            continue
        allowed_mask.append(False)
        if res.status == "GATE_DENY":
            denied += 1
            for rule in res.fired_rules:
                rule_counts[rule] += 1
                examples.setdefault(rule, [])
                if len(examples[rule]) < 3:
                    examples[rule].append({"id": t.id, "vendor": t.vendor,
                                           "amount": t.amount, "reason": res.reasons[:1]})
        else:  # GATE_ESCALATE (deny-by-default)
            escalated += 1
            rule_counts["deny_by_default"] += 1
    gp = GatePass(
        n=len(txns), stopped=denied + escalated, denied=denied, escalated=escalated,
        rule_counts=dict(rule_counts), examples=examples,
    )
    return gp, allowed_mask


def run_judge_flags(judge, objective: str, txns: list[Transaction]) -> tuple[int, Counter, list, int]:
    """Return (flagged, reason_counts, examples, errors) over the given txns."""
    flagged = 0
    errors = 0
    reasons: Counter = Counter()
    examples: list = []
    for t in txns:
        try:
            r = judge.judge(objective, t)
        except Exception:
            errors += 1
            continue
        if r.flag:
            flagged += 1
            # coarse reason bucket: first 60 chars
            reasons[r.reason[:70]] += 1
            if len(examples) < 8:
                examples.append({"id": t.id, "vendor": t.vendor, "amount": t.amount,
                                 "memo": (t.memo or "")[:120], "reason": r.reason[:200]})
    return flagged, reasons, examples, errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", choices=["heuristic", "llm", "both"], default="heuristic")
    ap.add_argument("--llm-sample", type=int, default=250,
                    help="random sample of gate-allowed REAL rows to judge with the LLM")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    random.seed(args.seed)

    mandate = load_mandate(MANDATE)
    gate = DeterministicGate(mandate)
    real = _load(REAL)
    seeds = _load(SEEDS) if SEEDS.exists() else []

    judges = []
    if args.judge in ("heuristic", "both"):
        judges.append(("heuristic_v1", HeuristicJudge(), False))
    if args.judge in ("llm", "both"):
        judges.append(("anthropic_claude-sonnet-4-6", AnthropicJudge(cache_path=CACHE), True))

    # ---------------- TEST A: false positives on real spend ----------------
    build_history(real, mandate.duplicate_window_days or 365)
    real_txns = [Transaction.from_dict(r) for r in real]
    gate_a, allowed_mask = run_gate(gate, real_txns)
    allowed_real = [t for t, ok in zip(real_txns, allowed_mask) if ok]

    test_a_judges = {}
    for name, judge, is_llm in judges:
        ok, why = judge.available()
        if not ok:
            test_a_judges[name] = {"available": False, "reason": why}
            continue
        if is_llm:
            sample = allowed_real if len(allowed_real) <= args.llm_sample \
                else random.sample(allowed_real, args.llm_sample)
            flagged, reasons, examples, errors = run_judge_flags(judge, mandate.objective, sample)
            test_a_judges[name] = {
                "available": True, "sampled": True, "sample_n": len(sample),
                "flagged": flagged, "fp_rate_on_sample": round(flagged / max(1, len(sample)), 4),
                "errors": errors, "top_reasons": reasons.most_common(6), "examples": examples,
            }
        else:
            flagged, reasons, examples, errors = run_judge_flags(judge, mandate.objective, allowed_real)
            test_a_judges[name] = {
                "available": True, "sampled": False, "judged_n": len(allowed_real),
                "flagged": flagged, "fp_rate_on_allowed": round(flagged / max(1, len(allowed_real)), 4),
                "fp_rate_on_all": round(flagged / max(1, len(real_txns)), 4),
                "errors": errors, "top_reasons": reasons.most_common(6), "examples": examples,
            }

    test_a = {
        "n_real": len(real_txns),
        "gate": {
            "stopped": gate_a.stopped,
            "fp_rate": round(gate_a.stopped / gate_a.n, 4),
            "denied": gate_a.denied,
            "escalated_deny_by_default": gate_a.escalated,
            "by_rule": gate_a.rule_counts,
            "by_rule_fp_rate": {k: round(v / gate_a.n, 4) for k, v in gate_a.rule_counts.items()},
            "examples": gate_a.examples,
        },
        "judges": test_a_judges,
    }

    # ---------------- TEST B: recall on seeded honest errors ----------------
    test_b = {"available": bool(seeds)}
    if seeds:
        combined = real + seeds
        build_history(combined, mandate.duplicate_window_days or 365)
        seed_by_id = {r["id"]: r for r in combined if r.get("label") == "seed"}
        seed_txns = [Transaction.from_dict(seed_by_id[s["id"]]) for s in seeds]

        # gate verdicts for seeds (judge-independent)
        per_type_total: Counter = Counter()
        per_type_gate_caught: Counter = Counter()
        gate_allowed_seeds = []
        gate_caught_ids = set()
        for s, t in zip(seeds, seed_txns):
            et = s.get("error_type", "?")
            per_type_total[et] += 1
            res = gate.evaluate(t)
            if res.status != GATE_ALLOW:
                per_type_gate_caught[et] += 1
                gate_caught_ids.add(t.id)
            else:
                gate_allowed_seeds.append((s, t))

        n_seed = len(seeds)
        fp = test_a["gate"]["stopped"]   # gate FPs on real
        tn = test_a["n_real"] - fp

        # per-judge recall (gate ∪ judge), so each judge's catch-rate is visible
        judges_b = {}
        for name, judge, _is_llm in judges:
            ok, why = judge.available()
            if not ok:
                judges_b[name] = {"available": False, "reason": why}
                continue
            judge_caught_ids = set()
            for s, t in gate_allowed_seeds:
                try:
                    r = judge.judge(mandate.objective, t)
                except Exception:
                    continue
                if r.flag:
                    judge_caught_ids.add(t.id)
            caught_ids = gate_caught_ids | judge_caught_ids
            per_type_caught = Counter()
            for s, t in zip(seeds, seed_txns):
                if t.id in caught_ids:
                    per_type_caught[s.get("error_type", "?")] += 1
            tp = len(caught_ids)
            judges_b[name] = {
                "available": True,
                "recall_overall": round(tp / n_seed, 4),
                "semantic_delta": len(judge_caught_ids - gate_caught_ids),
                "by_error_type": {
                    et: {"total": per_type_total[et], "caught": per_type_caught[et],
                         "gate_caught": per_type_gate_caught[et],
                         "recall": round(per_type_caught[et] / per_type_total[et], 3)}
                    for et in sorted(per_type_total)
                },
                "confusion": {"tp": tp, "fn": n_seed - tp, "fp": fp, "tn": tn},
            }

        test_b = {
            "available": True,
            "n_seed": n_seed,
            "gate_only": {
                "by_error_type": {
                    et: {"total": per_type_total[et], "gate_caught": per_type_gate_caught[et]}
                    for et in sorted(per_type_total)
                },
                "recall_overall": round(len(gate_caught_ids) / n_seed, 4),
            },
            "judges": judges_b,
            "fp_tn_note": "fp/tn are the gate's flags on real spend (Test A); judge real-spend FP is in Test A",
        }

    report = {
        "when": datetime.now(timezone.utc).isoformat(),
        "mandate_id": mandate.mandate_id,
        "judge_mode": args.judge,
        "test_a": test_a,
        "test_b": test_b,
    }

    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = report["when"].replace(":", "").replace("-", "").replace(".", "_")
    out = RUNS / f"real_run_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    REPORT.write_text(render_markdown(report), encoding="utf-8")
    print(f"run persisted: {out}")
    print(f"report:        {REPORT}")
    _print_summary(report)
    return 0


def _print_summary(rep: dict) -> None:
    a = rep["test_a"]
    print("\n=== TEST A — false positives on REAL spend ===")
    print(f"  real rows: {a['n_real']}")
    print(f"  GATE false-positive rate: {a['gate']['fp_rate']:.1%}  "
          f"(denied {a['gate']['denied']}, deny-by-default {a['gate']['escalated_deny_by_default']})")
    for rule, fp in sorted(a['gate']['by_rule_fp_rate'].items(), key=lambda kv: -kv[1]):
        print(f"      {rule:22} {fp:.1%}")
    for name, j in a["judges"].items():
        if not j.get("available"):
            print(f"  JUDGE {name}: unavailable ({j.get('reason')})")
        elif j.get("sampled"):
            print(f"  JUDGE {name} (sampled {j['sample_n']}): FP {j['fp_rate_on_sample']:.1%}")
        else:
            print(f"  JUDGE {name}: FP {j['fp_rate_on_all']:.1%} of all "
                  f"({j['flagged']}/{j['judged_n']} of gate-allowed)")
    b = rep["test_b"]
    if b.get("available"):
        print("\n=== TEST B — recall on SEEDED honest errors ===")
        print(f"  seeds: {b['n_seed']}  gate-only recall: {b['gate_only']['recall_overall']:.1%}")
        for name, jb in b["judges"].items():
            if not jb.get("available"):
                print(f"  + {name}: unavailable ({jb.get('reason')})")
                continue
            print(f"  + {name}: overall recall {jb['recall_overall']:.1%}  "
                  f"semantic delta {jb['semantic_delta']}  (E5 off-objective: "
                  f"{jb['by_error_type'].get('E5',{}).get('caught',0)}/9)")


def render_markdown(rep: dict) -> str:
    a, b = rep["test_a"], rep["test_b"]
    L = []
    w = L.append
    w("# Real-Data Validation — Procurement Firewall")
    w("")
    w(f"_Generated {rep['when']} · mandate `{rep['mandate_id']}` · judge mode `{rep['judge_mode']}`_")
    w("")
    w("**Scope:** honest-mistake / off-policy detection and false-positive realism on "
      "real public procurement data. This does **NOT** test deliberate adversaries and "
      "uses **no ground-truth-labeled real fraud** (none is public). See limitations.")
    w("")
    w("## Data provenance")
    prov = json.loads((HERE / "datasets" / "real" / "PROVENANCE.json").read_text())
    w(f"- Source: {prov['source']}")
    w(f"- Filters: NAICS {prov['filters']['naics']} "
      f"({prov['filters']['naics_description']}), award types "
      f"{prov['filters']['award_type_codes']}, action window "
      f"{prov['filters']['time_period']['start']}…{prov['filters']['time_period']['end']}, "
      f"sort {prov['filters']['sort']}")
    w(f"- Rows: {prov['rows']} (all real, legitimate federal awards)")
    w(f"- Fetched: {prov['fetched_at']}")
    w("")
    w("## TEST A — false positives on real legitimate spend (headline)")
    w("")
    w(f"Every one of the **{a['n_real']:,}** rows is a real, legitimate award, so every "
      "flag is effectively a false positive.")
    w("")
    w(f"- **Deterministic gate false-positive rate: {a['gate']['fp_rate']:.1%}** "
      f"({a['gate']['stopped']:,}/{a['n_real']:,}) — denied {a['gate']['denied']:,}, "
      f"deny-by-default {a['gate']['escalated_deny_by_default']:,}.")
    w("")
    w("Decomposed by which rule fired (a row can trip more than one):")
    w("")
    w("| rule | rows flagged | FP rate |")
    w("|---|---|---|")
    for rule, cnt in sorted(a["gate"]["by_rule"].items(), key=lambda kv: -kv[1]):
        w(f"| {rule} | {cnt:,} | {a['gate']['by_rule_fp_rate'][rule]:.1%} |")
    w("")
    for name, j in a["judges"].items():
        w(f"### Semantic judge — `{name}`")
        if not j.get("available"):
            w(f"- Not run: {j.get('reason')}")
            w("")
            continue
        if j.get("sampled"):
            w(f"- Estimated on a random sample of **{j['sample_n']}** gate-allowed real rows "
              f"(to bound API cost): **{j['fp_rate_on_sample']:.1%}** flagged "
              f"({j['flagged']}/{j['sample_n']}). Errors: {j['errors']}.")
        else:
            w(f"- Run on all **{j['judged_n']:,}** gate-allowed real rows: "
              f"**{j['fp_rate_on_all']:.1%}** of all rows flagged "
              f"({j['flagged']}/{j['judged_n']} of gate-allowed). Errors: {j['errors']}.")
        if j.get("top_reasons"):
            w("- Top flag reasons:")
            for reason, cnt in j["top_reasons"]:
                w(f"    - ({cnt}×) {reason}")
        w("")
    if b.get("available"):
        labels = {"E1": "amount over cap", "E2": "vendor off allowlist",
                  "E3": "wrong category", "E4": "duplicate", "E5": "off-objective purpose",
                  "E6": "wrong currency"}
        w("## TEST B — recall on seeded honest-mistake cases")
        w("")
        w(f"{b['n_seed']} honest-error cases (authored independently of the judge — see "
          "independence note) injected into the real haystack.")
        w("")
        w(f"- **Deterministic gate alone — recall: {b['gate_only']['recall_overall']:.1%}** "
          "(catches the quantitative errors E1–E4, E6; by design catches no E5).")
        go = b["gate_only"]["by_error_type"]
        w("")
        w("| error type | caught by gate / total |")
        w("|---|---|")
        for et, d in go.items():
            w(f"| {et} {labels.get(et,'')} | {d['gate_caught']}/{d['total']} |")
        w("")
        for name, jb in b["judges"].items():
            w(f"### + semantic judge `{name}`")
            if not jb.get("available"):
                w(f"- Not run: {jb.get('reason')}")
                w("")
                continue
            w(f"- **Overall recall (gate ∪ judge): {jb['recall_overall']:.1%}**")
            w(f"- **Semantic delta** (seeds the gate let through but this judge caught): "
              f"**{jb['semantic_delta']}** — almost entirely the E5 off-objective cases.")
            c = jb["confusion"]
            w(f"- Confusion (seed=should-catch, real=should-pass; FP/TN = the gate's flags "
              f"on real): TP={c['tp']}, FN={c['fn']}, FP={c['fp']:,}, TN={c['tn']:,}.")
            w("")
            w("| error type | caught / total | recall |")
            w("|---|---|---|")
            for et, d in jb["by_error_type"].items():
                w(f"| {et} {labels.get(et,'')} | {d['caught']}/{d['total']} | {d['recall']:.0%} |")
            w("")
        w("> The contrast that matters: pair each judge's seeded **recall here** with its "
          "**real-spend false-positive rate in Test A**. Higher recall on E5 comes with a "
          "higher false-positive rate on legitimate spend — the precision/recall tradeoff, "
          "on real data.")
        w("")
    w("## Honest limitations")
    w("")
    w("- **This validates honest-mistake detection and false-positive realism — not "
      "fraud.** It does not test deliberate adversaries who adapt to evade the firewall.")
    w("- **No ground-truth-labeled real fraud is used** (none is public); the real rows "
      "are assumed-legitimate, which is why their flags are read as false positives.")
    w("- **Allowlist FP reflects slice breadth.** The vendor allowlist is the top-100 "
      "vendors of a multi-agency slice; real spend has a long vendor tail, so off-allowlist "
      "FP is large here. A genuinely narrow single-program mandate would cover ~all its "
      "vendors. This is a property of the test scope, not only of the primitive.")
    w("- **The amount-cap FP is whatever percentile we picked** (p99.5 ⇒ ~0.5% over by "
      "construction); the real lesson is that any fixed cap false-positives on the heavy "
      "right tail of government spend.")
    w("- **Disabled primitives:** approval tiers and three-way match (no approver / "
      "receipt data in award records) and rate-limit / structuring (per-program cadence "
      "controls, not meaningful across a 49-agency aggregate). Their real-world FP is "
      "untested here.")
    w("- **Author-correlation is reduced, not eliminated.** The seed cases were written "
      "from a plain-English taxonomy without seeing the judge prompt, by a separate agent "
      "— but both the seeds and the judge are LLM-reasoned, so their notions of "
      "'off-objective' still partly correlate.")
    w("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
