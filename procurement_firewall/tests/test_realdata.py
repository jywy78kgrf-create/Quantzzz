"""Real-data harness sanity checks.

These use only committed files (the derived mandate + the small seeded cases).
The BULK real cache is not committed (it's large public data, regenerable with
`realdata/fetch_usaspending.py`); tests that need it skip gracefully when absent.
"""

import json
from pathlib import Path

import pytest

from firewall.gate import DeterministicGate
from firewall.loaders import load_mandate
from firewall.models import GATE_ALLOW, Transaction

ROOT = Path(__file__).resolve().parent.parent
MANDATE = ROOT / "mandates" / "usaspending_541512_fy2024.json"
SEEDS = ROOT / "datasets" / "real" / "seed_honest_errors.jsonl"
REAL = ROOT / "datasets" / "real" / "usaspending_541512_fy2024.jsonl"

# The mandate + seeds are committed; skip only if this slice was never added.
pytestmark = pytest.mark.skipif(
    not MANDATE.exists() or not SEEDS.exists(),
    reason="real-data mandate/seeds not present in this checkout",
)


def _seeds():
    return [json.loads(line) for line in SEEDS.open(encoding="utf-8") if line.strip()]


def test_seed_cases_trip_their_intended_layer():
    """Each committed honest-error seed behaves as intended against the derived
    mandate — using only committed files (no bulk cache needed).

    E4 duplicates are excluded here: tripping the duplicate rule requires the
    real-data row in the transaction's history, which lives in the bulk cache;
    that path is covered by `test_real_cache_loads_and_runs` when present.
    """
    gate = DeterministicGate(load_mandate(MANDATE))
    for s in _seeds():
        et = s.get("error_type")
        if et == "E4":
            continue
        status = gate.evaluate(Transaction.from_dict(s)).status
        if et == "E5":
            # off-objective but quantitatively flawless -> only the judge can catch
            assert status == GATE_ALLOW, f"{s['id']} (E5) should pass the gate, got {status}"
        else:
            # E1/E2/E3/E6 are quantitative errors the gate must stop
            assert status != GATE_ALLOW, f"{s['id']} ({et}) should be gate-stopped, got {status}"


@pytest.mark.skipif(
    not REAL.exists(),
    reason="bulk real cache absent (regenerate with realdata/fetch_usaspending.py)",
)
def test_real_cache_loads_and_runs():
    """When the bulk cache is present, it loads and the gate runs without error."""
    gate = DeterministicGate(load_mandate(MANDATE))
    rows = [json.loads(line) for line in REAL.open(encoding="utf-8") if line.strip()]
    assert rows, "real cache is empty"
    for r in rows[:200]:
        gate.evaluate(Transaction.from_dict(r))  # must not raise
