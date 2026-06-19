#!/usr/bin/env python3
"""Validate a labeled dataset against a mandate's deterministic gate.

This enforces the structural invariant that keeps the eval honest:
  - every `ok` and `sem_off` row MUST pass the gate (status ALLOW), otherwise it
    is mislabeled (it should be `det_off`), which would inflate the semantic delta;
  - every `det_off` row MUST be stopped by the gate (DENY or ESCALATE), otherwise
    it is mislabeled or undetectable.

    python eval/validate_dataset.py mandates/<m>.json datasets/<d>.jsonl

Exits non-zero if any mislabel is found.
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firewall.gate import DeterministicGate  # noqa: E402
from firewall.loaders import load_mandate, load_transactions  # noqa: E402
from firewall.models import GATE_ALLOW  # noqa: E402


def validate(mandate_path: str, dataset_path: str) -> int:
    mandate = load_mandate(mandate_path)
    txns = load_transactions(dataset_path)
    gate = DeterministicGate(mandate)

    labels = collections.Counter(t.label for t in txns)
    ids = [t.id for t in txns]
    dup_ids = [i for i, c in collections.Counter(ids).items() if c > 1]

    sem_catchable = []  # sem_off the gate CAN catch -> mislabeled
    det_missed = []     # det_off the gate ALLOWs -> mislabeled
    ok_stopped = []     # ok the gate stops -> mislabeled / over-strict

    for t in txns:
        status = gate.evaluate(t).status
        if t.label == "sem_off" and status != GATE_ALLOW:
            sem_catchable.append((t.id, status))
        elif t.label == "det_off" and status == GATE_ALLOW:
            det_missed.append(t.id)
        elif t.label == "ok" and status != GATE_ALLOW:
            ok_stopped.append((t.id, status, gate.evaluate(t).reasons))

    print(f"dataset: {dataset_path}")
    print(f"mandate: {mandate.mandate_id}")
    print(f"rows: {len(txns)}  labels: {dict(labels)}")
    print(f"duplicate ids: {dup_ids or 'none'}")
    print(f"sem_off the gate CAN catch (mislabeled): {len(sem_catchable)} {sem_catchable[:10]}")
    print(f"det_off the gate MISSES (mislabeled):    {len(det_missed)} {det_missed[:10]}")
    print(f"ok rows the gate STOPS (mislabeled):     {len(ok_stopped)}")
    for x in ok_stopped[:10]:
        print(f"    {x}")

    bad = bool(dup_ids or sem_catchable or det_missed or ok_stopped)
    print("RESULT:", "FAIL" if bad else "OK")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: validate_dataset.py <mandate.json> <dataset.jsonl>")
    raise SystemExit(validate(sys.argv[1], sys.argv[2]))
