"""Eval harness — the product's truth test.

Given a labeled dataset (an INDEPENDENT input) and a mandate, this runs the full
two-layer firewall for each judge implementation and reports, per judge:

  - a confusion matrix where the POSITIVE class is "should be stopped"
    (label in {det_off, sem_off});
  - precision and recall;
  - the SEMANTIC DELTA: how many off-objective transactions were caught ONLY by
    the semantic judge on rows the deterministic gate provably cannot catch
    (gate ALLOWed the row, judge escalated it).

It also computes the deterministic GATE-ONLY floor, so the marginal value of the
semantic layer is explicit. Every run is persisted so prompt changes can be
compared across runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from firewall.firewall import ProcurementFirewall
from firewall.gate import DeterministicGate
from firewall.judge.base import SemanticJudge
from firewall.models import (
    ALLOWED,
    GATE_ALLOW,
    Mandate,
    Transaction,
)

# Ground-truth labels.
LABEL_OK = "ok"
LABEL_DET = "det_off"
LABEL_SEM = "sem_off"
_OFF_LABELS = {LABEL_DET, LABEL_SEM}


@dataclass
class ConfusionMatrix:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    def add(self, predicted_stop: bool, actual_stop: bool) -> None:
        if predicted_stop and actual_stop:
            self.tp += 1
        elif predicted_stop and not actual_stop:
            self.fp += 1
        elif not predicted_stop and not actual_stop:
            self.tn += 1
        else:
            self.fn += 1

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class JudgeReport:
    judge_name: str
    available: bool
    unavailable_reason: Optional[str]
    confusion: dict
    precision: float
    recall: float
    f1: float
    semantic_delta: int  # off-objective rows caught ONLY by the judge (gate allowed)
    sem_off_total: int
    sem_off_caught: int
    det_off_total: int
    det_off_caught: int
    ok_total: int
    ok_false_positives: int
    errors: int = 0
    prompt_sha256: Optional[str] = None


@dataclass
class RunReport:
    when: str
    dataset_path: str
    dataset_sha256: str
    n_rows: int
    mandate_id: str
    label_counts: dict
    gate_only: dict  # deterministic floor confusion + metrics
    judges: list = field(default_factory=list)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label_counts(txns: list[Transaction]) -> dict:
    counts: dict[str, int] = {}
    for t in txns:
        counts[t.label or "UNLABELED"] = counts.get(t.label or "UNLABELED", 0) + 1
    return counts


def evaluate_gate_only(mandate: Mandate, txns: list[Transaction]) -> dict:
    """The deterministic floor: gate verdict with no judge involved."""
    gate = DeterministicGate(mandate)
    cm = ConfusionMatrix()
    for t in txns:
        res = gate.evaluate(t)
        predicted_stop = res.status != GATE_ALLOW  # DENY or ESCALATE both stop
        cm.add(predicted_stop, (t.label in _OFF_LABELS))
    return {
        "confusion": asdict(cm),
        "precision": round(cm.precision, 4),
        "recall": round(cm.recall, 4),
        "f1": round(cm.f1, 4),
    }


def evaluate_judge(
    mandate: Mandate,
    txns: list[Transaction],
    judge: SemanticJudge,
) -> JudgeReport:
    available, why = judge.available()
    prompt_sha = None
    if hasattr(judge, "prompt_text"):
        prompt_sha = hashlib.sha256(judge.prompt_text.encode("utf-8")).hexdigest()

    if not available:
        return JudgeReport(
            judge_name=judge.name,
            available=False,
            unavailable_reason=why,
            confusion=asdict(ConfusionMatrix()),
            precision=0.0,
            recall=0.0,
            f1=0.0,
            semantic_delta=0,
            sem_off_total=sum(1 for t in txns if t.label == LABEL_SEM),
            sem_off_caught=0,
            det_off_total=sum(1 for t in txns if t.label == LABEL_DET),
            det_off_caught=0,
            ok_total=sum(1 for t in txns if t.label == LABEL_OK),
            ok_false_positives=0,
            prompt_sha256=prompt_sha,
        )

    firewall = ProcurementFirewall(mandate, judge, audit_log=None)
    gate = DeterministicGate(mandate)
    cm = ConfusionMatrix()
    semantic_delta = 0
    sem_off_total = sem_off_caught = 0
    det_off_total = det_off_caught = 0
    ok_total = ok_fp = 0
    errors = 0

    for t in txns:
        actual_stop = t.label in _OFF_LABELS
        try:
            verdict = firewall.decide(t)
        except Exception as exc:  # pragma: no cover - judge/runtime dependent
            errors += 1
            # Fail safe: count an errored row as "not stopped" so we never
            # flatter the system by treating a crash as a catch.
            cm.add(False, actual_stop)
            _ = exc
            continue

        predicted_stop = verdict.decision != ALLOWED
        cm.add(predicted_stop, actual_stop)

        gate_res = gate.evaluate(t)
        gate_would_catch = gate_res.status != GATE_ALLOW

        if t.label == LABEL_SEM:
            sem_off_total += 1
            if predicted_stop:
                sem_off_caught += 1
        elif t.label == LABEL_DET:
            det_off_total += 1
            if predicted_stop:
                det_off_caught += 1
        elif t.label == LABEL_OK:
            ok_total += 1
            if predicted_stop:
                ok_fp += 1

        # Semantic delta: off-objective, gate cannot catch (it allowed), and the
        # judge escalated. This is value the deterministic floor provably lacks.
        if actual_stop and not gate_would_catch and predicted_stop:
            semantic_delta += 1

    return JudgeReport(
        judge_name=judge.name,
        available=True,
        unavailable_reason=None,
        confusion=asdict(cm),
        precision=round(cm.precision, 4),
        recall=round(cm.recall, 4),
        f1=round(cm.f1, 4),
        semantic_delta=semantic_delta,
        sem_off_total=sem_off_total,
        sem_off_caught=sem_off_caught,
        det_off_total=det_off_total,
        det_off_caught=det_off_caught,
        ok_total=ok_total,
        ok_false_positives=ok_fp,
        errors=errors,
        prompt_sha256=prompt_sha,
    )


def run_eval(
    mandate: Mandate,
    dataset_path: Path,
    txns: list[Transaction],
    judges: list[SemanticJudge],
) -> RunReport:
    report = RunReport(
        when=datetime.now(timezone.utc).isoformat(),
        dataset_path=str(dataset_path),
        dataset_sha256=_sha256_file(dataset_path),
        n_rows=len(txns),
        mandate_id=mandate.mandate_id,
        label_counts=_label_counts(txns),
        gate_only=evaluate_gate_only(mandate, txns),
        judges=[asdict(evaluate_judge(mandate, txns, j)) for j in judges],
    )
    return report


def persist_run(report: RunReport, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.when.replace(":", "").replace("-", "").replace(".", "_")
    out = runs_dir / f"run_{stamp}.json"
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    # Append a compact line to the cross-run history for easy diffing.
    history = runs_dir / "history.jsonl"
    compact = {
        "when": report.when,
        "dataset_sha256": report.dataset_sha256[:12],
        "n_rows": report.n_rows,
        "gate_recall": report.gate_only["recall"],
        "gate_precision": report.gate_only["precision"],
        "judges": {
            j["judge_name"]: {
                "available": j["available"],
                "precision": j["precision"],
                "recall": j["recall"],
                "semantic_delta": j["semantic_delta"],
                "ok_false_positives": j["ok_false_positives"],
                "prompt_sha256": (j["prompt_sha256"] or "")[:12],
            }
            for j in report.judges
        },
    }
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(compact) + "\n")
    return out


def load_previous_run(runs_dir: Path, exclude: Path) -> Optional[dict]:
    runs = sorted(runs_dir.glob("run_*.json"))
    runs = [r for r in runs if r != exclude]
    if not runs:
        return None
    return json.loads(runs[-1].read_text(encoding="utf-8"))
