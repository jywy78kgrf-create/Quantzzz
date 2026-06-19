#!/usr/bin/env python3
"""End-to-end eval across all suites, for both judge implementations.

    python evaluate.py                 # all suites in eval/suites.json, both judges
    python evaluate.py --only heuristic
    python evaluate.py --suite platform_infra_hard

Prints a per-suite summary, persists the full run to eval/runs/, and writes a
markdown report to eval/REPORT.md.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from eval.harness import RunReport, evaluate_suite, persist_run
from eval.report import generate_markdown
from firewall.judge import AnthropicJudge, HeuristicJudge
from firewall.loaders import load_mandate, load_transactions

HERE = Path(__file__).resolve().parent
RUNS_DIR = HERE / "eval" / "runs"
SUITES_FILE = HERE / "eval" / "suites.json"
REPORT_FILE = HERE / "eval" / "REPORT.md"


def _load_suites(only_suite: str | None) -> list[dict]:
    suites = json.loads(SUITES_FILE.read_text(encoding="utf-8"))["suites"]
    if only_suite:
        suites = [s for s in suites if s["name"] == only_suite]
        if not suites:
            raise SystemExit(f"no suite named {only_suite!r} in {SUITES_FILE}")
    # Skip suites whose dataset isn't present yet (independently authored).
    present = []
    for s in suites:
        if (HERE / s["dataset"]).exists():
            present.append(s)
        else:
            print(f"  (skipping suite {s['name']}: dataset {s['dataset']} not found)")
    return present


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Procurement firewall eval harness")
    ap.add_argument("--only", choices=["heuristic", "llm"], help="run only one judge")
    ap.add_argument("--suite", help="run only the named suite")
    ap.add_argument("--no-persist", action="store_true",
                    help="do not write run files or REPORT.md (for smoke runs)")
    args = ap.parse_args(argv)

    suites_cfg = _load_suites(args.suite)
    if not suites_cfg:
        raise SystemExit("no suites with datasets present to evaluate")

    cache_path = HERE / "eval" / ".judge_cache.json"
    judges_for = lambda: (  # noqa: E731 - fresh judges per suite
        ([HeuristicJudge()] if args.only in (None, "heuristic") else [])
        + ([AnthropicJudge(cache_path=cache_path)] if args.only in (None, "llm") else [])
    )

    run = RunReport(when=datetime.now(timezone.utc).isoformat(), suites=[])

    print("=" * 72)
    print("OFF-OBJECTIVE PROCUREMENT FIREWALL — MULTI-SUITE EVAL")
    print("=" * 72)

    for cfg in suites_cfg:
        mandate = load_mandate(HERE / cfg["mandate"])
        dataset_path = HERE / cfg["dataset"]
        txns = load_transactions(dataset_path)
        report = evaluate_suite(cfg["name"], mandate, dataset_path, txns, judges_for())
        run.suites.append(asdict(report))

        g = report.gate_only
        print(f"\n## {cfg['name']}  ({report.n_rows} rows, {report.mandate_id})")
        print(f"   labels: {report.label_counts}")
        print(f"   gate floor:  precision {g['precision']:.3f}  recall {g['recall']:.3f}")
        for j in asdict(report)["judges"]:
            if not j["available"]:
                print(f"   {j['judge_name']:<32} UNAVAILABLE ({j['unavailable_reason']})")
                continue
            inj = (
                f"  injection {j['injection_caught']}/{j['injection_total']}"
                if j["injection_total"]
                else ""
            )
            print(
                f"   {j['judge_name']:<32} P {j['precision']:.3f}  R {j['recall']:.3f}  "
                f"FP {j['ok_false_positives']}/{j['ok_total']}  "
                f"sem-delta {j['semantic_delta']}{inj}"
            )

    if args.no_persist:
        print("\n" + "-" * 72)
        print("(--no-persist: run files and REPORT.md not written)")
        return 0
    out = persist_run(run, RUNS_DIR)
    REPORT_FILE.write_text(generate_markdown(asdict(run)), encoding="utf-8")
    print("\n" + "-" * 72)
    print(f"run persisted: {out}")
    print(f"markdown report: {REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
