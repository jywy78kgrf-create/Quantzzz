#!/usr/bin/env python3
"""End-to-end eval: runs the labeled set through both judge implementations and
prints, per judge, a confusion matrix + precision/recall + the semantic delta.

    python evaluate.py
    python evaluate.py --mandate mandates/platform_infra_2026.json \
                       --dataset datasets/transactions.jsonl

Each run is persisted to eval/runs/ and appended to eval/runs/history.jsonl so
judge-prompt changes can be compared across runs (the iteration loop).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.harness import load_previous_run, persist_run, run_eval
from firewall.judge import AnthropicJudge, HeuristicJudge
from firewall.loaders import load_mandate, load_transactions

HERE = Path(__file__).resolve().parent
DEFAULT_MANDATE = HERE / "mandates" / "platform_infra_2026.json"
DEFAULT_DATASET = HERE / "datasets" / "transactions.jsonl"
RUNS_DIR = HERE / "eval" / "runs"


def _fmt_cm(cm: dict) -> str:
    return (
        f"TP={cm['tp']:>4}  FP={cm['fp']:>4}\n"
        f"            FN={cm['fn']:>4}  TN={cm['tn']:>4}"
    )


def _print_judge(j: dict, gate_recall: float) -> None:
    print(f"\n  Judge: {j['judge_name']}")
    if not j["available"]:
        print(f"    UNAVAILABLE — {j['unavailable_reason']}")
        print("    (skipped; set ANTHROPIC_API_KEY and install `anthropic` to run it)")
        return
    cm = j["confusion"]
    print("    Confusion matrix (positive = should be stopped):")
    print("                 pred STOP   pred ALLOW")
    print(f"      actual STOP   TP={cm['tp']:<5}     FN={cm['fn']:<5}")
    print(f"      actual OK     FP={cm['fp']:<5}     TN={cm['tn']:<5}")
    print(f"    precision = {j['precision']:.3f}   recall = {j['recall']:.3f}   "
          f"f1 = {j['f1']:.3f}")
    print(f"    false positives on OK rows: {j['ok_false_positives']} / {j['ok_total']}")
    print(f"    det_off caught: {j['det_off_caught']}/{j['det_off_total']}   "
          f"sem_off caught: {j['sem_off_caught']}/{j['sem_off_total']}")
    print(f"    >>> SEMANTIC DELTA = {j['semantic_delta']}  "
          f"(off-objective rows the gate cannot catch but this judge escalated)")
    if j["errors"]:
        print(f"    errors during run: {j['errors']}")


def _compare(prev: dict, judge_name: str, cur: dict) -> None:
    for pj in prev.get("judges", []):
        if pj["judge_name"] == judge_name and pj["available"] and cur["available"]:
            dr = cur["recall"] - pj["recall"]
            dfp = cur["ok_false_positives"] - pj["ok_false_positives"]
            dd = cur["semantic_delta"] - pj["semantic_delta"]
            print(f"    vs previous run: Δrecall={dr:+.3f}  "
                  f"Δfalse_positives={dfp:+d}  Δsemantic_delta={dd:+d}")
            return


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Procurement firewall eval harness")
    ap.add_argument("--mandate", default=str(DEFAULT_MANDATE))
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--only", choices=["heuristic", "llm"],
                    help="run only one judge (default: both)")
    args = ap.parse_args(argv)

    mandate = load_mandate(args.mandate)
    dataset_path = Path(args.dataset)
    txns = load_transactions(dataset_path)

    judges = []
    if args.only in (None, "heuristic"):
        judges.append(HeuristicJudge())
    if args.only in (None, "llm"):
        judges.append(AnthropicJudge())

    report = run_eval(mandate, dataset_path, txns, judges)

    print("=" * 70)
    print("OFF-OBJECTIVE PROCUREMENT FIREWALL — EVAL")
    print("=" * 70)
    print(f"mandate:  {report.mandate_id}")
    print(f"dataset:  {report.dataset_path}")
    print(f"          sha256 {report.dataset_sha256[:16]}  |  {report.n_rows} rows")
    print(f"labels:   {report.label_counts}")

    print("\n" + "-" * 70)
    print("DETERMINISTIC FLOOR (gate only, no judge):")
    g = report.gate_only
    cm = g["confusion"]
    print("                 pred STOP   pred ALLOW")
    print(f"      actual STOP   TP={cm['tp']:<5}     FN={cm['fn']:<5}")
    print(f"      actual OK     FP={cm['fp']:<5}     TN={cm['tn']:<5}")
    print(f"    precision = {g['precision']:.3f}   recall = {g['recall']:.3f}   "
          f"f1 = {g['f1']:.3f}")
    print("    (the gate cannot catch sem_off by construction; its misses are the"
          " job the judge exists to do)")

    prev = load_previous_run(RUNS_DIR, exclude=Path("/nonexistent"))

    print("\n" + "-" * 70)
    print("PER-JUDGE (full two-layer firewall):")
    for j in report.judges:
        _print_judge(j, g["recall"])
        if prev:
            _compare(prev, j["judge_name"], j)

    out = persist_run(report, RUNS_DIR)
    print("\n" + "-" * 70)
    print(f"run persisted: {out}")
    print(f"history:       {RUNS_DIR / 'history.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
