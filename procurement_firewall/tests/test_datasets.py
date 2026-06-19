"""Dataset-integrity tests: enforce that the labels are gate-consistent.

For every suite in eval/suites.json whose dataset is present, every `ok` and
`sem_off` row must pass the deterministic gate, and every `det_off` row must be
stopped by it. This is what prevents a mislabeled row from secretly inflating
(or deflating) the semantic delta. The datasets are authored independently of
the judge; this test guards the boundary.
"""

import json
from pathlib import Path

import pytest

from firewall.gate import DeterministicGate
from firewall.loaders import load_mandate, load_transactions
from firewall.models import GATE_ALLOW

ROOT = Path(__file__).resolve().parent.parent
SUITES = json.loads((ROOT / "eval" / "suites.json").read_text())["suites"]


def _present_suites():
    return [s for s in SUITES if (ROOT / s["dataset"]).exists()]


@pytest.mark.parametrize("suite", _present_suites(), ids=lambda s: s["name"])
def test_dataset_is_gate_consistent(suite):
    mandate = load_mandate(ROOT / suite["mandate"])
    txns = load_transactions(ROOT / suite["dataset"])
    gate = DeterministicGate(mandate)

    ids = [t.id for t in txns]
    assert len(ids) == len(set(ids)), f"{suite['name']}: duplicate ids"

    sem_catchable, det_missed, ok_stopped = [], [], []
    for t in txns:
        status = gate.evaluate(t).status
        if t.label == "sem_off" and status != GATE_ALLOW:
            sem_catchable.append(t.id)
        elif t.label == "det_off" and status == GATE_ALLOW:
            det_missed.append(t.id)
        elif t.label == "ok" and status != GATE_ALLOW:
            ok_stopped.append(t.id)

    assert not sem_catchable, f"{suite['name']}: sem_off rows the gate can catch: {sem_catchable}"
    assert not det_missed, f"{suite['name']}: det_off rows the gate misses: {det_missed}"
    assert not ok_stopped, f"{suite['name']}: ok rows the gate wrongly stops: {ok_stopped}"


def test_at_least_one_suite_present():
    assert _present_suites(), "no datasets present to validate"
