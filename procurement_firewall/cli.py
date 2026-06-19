#!/usr/bin/env python3
"""CLI: feed a mandate + a batch of transactions, get per-transaction verdicts.

    python cli.py --mandate mandates/platform_infra_2026.json \
                  --transactions datasets/transactions.jsonl \
                  --judge heuristic

Each verdict prints the decision, the deciding layer, and the reason(s). Every
ESCALATE/DENY is also written as a signable record to the audit log.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from firewall.firewall import ProcurementFirewall
from firewall.judge import AnthropicJudge, HeuristicJudge
from firewall.loaders import load_mandate, load_transactions
from firewall.models import ALLOWED, DENIED, ESCALATED

_COLORS = {ALLOWED: "\033[32m", DENIED: "\033[31m", ESCALATED: "\033[33m"}
_RESET = "\033[0m"


def _build_judge(name: str):
    if name == "heuristic":
        return HeuristicJudge()
    if name == "llm":
        return AnthropicJudge()
    raise SystemExit(f"unknown judge '{name}' (choose: heuristic, llm)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Off-Objective Procurement Firewall CLI")
    ap.add_argument("--mandate", required=True, help="path to mandate JSON")
    ap.add_argument("--transactions", required=True, help="path to transactions JSON/JSONL")
    ap.add_argument(
        "--judge", default="heuristic", choices=["heuristic", "llm"],
        help="which semantic judge to use (default: heuristic)",
    )
    ap.add_argument(
        "--audit-log", default="audit_log.jsonl",
        help="path to append signable ESCALATE/DENY records",
    )
    ap.add_argument("--json", action="store_true", help="emit verdicts as JSON")
    ap.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    args = ap.parse_args(argv)

    mandate = load_mandate(args.mandate)
    txns = load_transactions(args.transactions)
    judge = _build_judge(args.judge)

    if args.judge == "llm":
        ok, why = judge.available()
        if not ok:
            print(f"error: LLM judge unavailable: {why}", file=sys.stderr)
            return 2

    firewall = ProcurementFirewall(mandate, judge, audit_log=args.audit_log)

    results = []
    counts = {ALLOWED: 0, DENIED: 0, ESCALATED: 0}
    for txn in txns:
        verdict = firewall.decide(txn)
        counts[verdict.decision] += 1
        results.append(verdict)

    if args.json:
        print(json.dumps([v.to_dict() for v in results], indent=2))
    else:
        use_color = not args.no_color and sys.stdout.isatty()
        for v in results:
            c = _COLORS.get(v.decision, "") if use_color else ""
            r = _RESET if use_color else ""
            reason = "; ".join(v.reasons)
            print(f"{c}{v.decision:<10}{r} {v.transaction_id:<12} "
                  f"[{v.deciding_layer}]  {reason}")
        print(
            f"\nmandate: {mandate.mandate_id}  |  judge: {judge.name}  |  "
            f"n={len(txns)}  ALLOWED={counts[ALLOWED]}  "
            f"DENIED={counts[DENIED]}  ESCALATED={counts[ESCALATED]}"
        )
        print(f"audit records appended to: {Path(args.audit_log).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
