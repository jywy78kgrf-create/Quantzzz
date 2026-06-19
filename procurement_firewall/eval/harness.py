"""Eval harness — the product's truth test.

Given a labeled dataset (an INDEPENDENT input) and a mandate, this runs the full
two-layer firewall for each judge implementation and reports, per judge:

  - a confusion matrix where the POSITIVE class is "should be stopped"
    (label in {det_off, sem_off});
  - precision and recall;
  - the SEMANTIC DELTA: how many off-objective transactions were caught ONLY by
    the semantic judge on rows the deterministic gate provably cannot catch
    (gate ALLOWed the row, judge escalated it);
  - breakdowns by difficulty and by tag (e.g. subtle sem_off, borderline ok);
  - injection RESISTANCE on rows tagged "injection";
  - a concrete FAILURE LIST (the misclassified rows, with the author's note and
    the judge's reason) so failure modes are visible, not hidden behind a score.

It also computes the deterministic GATE-ONLY floor. Every run is persisted so
prompt changes can be compared across runs.
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
from firewall.models import ALLOWED, GATE_ALLOW, Mandate, Transaction

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
class RowResult:
    id: str
    label: str
    difficulty: Optional[str]
    tags: list[str]
    actual_stop: bool
    gate_would_catch: bool
    decision: str
    predicted_stop: bool
    judge_flag: Optional[bool]
    judge_reason: str
    note: Optional[str]
    errored: bool = False


def _slice_counts(rows: list[RowResult], key_fn) -> dict:
    """Aggregate off/ok totals and catch/fp counts per key (difficulty or tag)."""
    out: dict[str, dict] = {}
    for r in rows:
        for k in key_fn(r):
            d = out.setdefault(
                k, {"off_total": 0, "off_caught": 0, "ok_total": 0, "ok_fp": 0}
            )
            if r.actual_stop:
                d["off_total"] += 1
                if r.predicted_stop:
                    d["off_caught"] += 1
            elif r.label == LABEL_OK:
                d["ok_total"] += 1
                if r.predicted_stop:
                    d["ok_fp"] += 1
    return out


@dataclass
class JudgeReport:
    judge_name: str
    available: bool
    unavailable_reason: Optional[str]
    confusion: dict
    precision: float
    recall: float
    f1: float
    semantic_delta: int
    sem_off_total: int
    sem_off_caught: int
    det_off_total: int
    det_off_caught: int
    ok_total: int
    ok_false_positives: int
    by_difficulty: dict = field(default_factory=dict)
    by_tag: dict = field(default_factory=dict)
    injection_total: int = 0
    injection_caught: int = 0
    failures: list = field(default_factory=list)
    errors: int = 0
    prompt_sha256: Optional[str] = None


@dataclass
class SuiteReport:
    suite: str
    dataset_path: str
    dataset_sha256: str
    n_rows: int
    mandate_id: str
    label_counts: dict
    gate_only: dict
    judges: list = field(default_factory=list)


@dataclass
class RunReport:
    when: str
    suites: list = field(default_factory=list)


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
        predicted_stop = res.status != GATE_ALLOW
        cm.add(predicted_stop, (t.label in _OFF_LABELS))
    return {
        "confusion": asdict(cm),
        "precision": round(cm.precision, 4),
        "recall": round(cm.recall, 4),
        "f1": round(cm.f1, 4),
    }


def _empty_report(judge: SemanticJudge, txns: list[Transaction], why: str,
                  prompt_sha: Optional[str]) -> JudgeReport:
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


def evaluate_judge(
    mandate: Mandate,
    txns: list[Transaction],
    judge: SemanticJudge,
    max_failures: int = 60,
) -> JudgeReport:
    available, why = judge.available()
    prompt_sha = None
    if hasattr(judge, "prompt_text"):
        prompt_sha = hashlib.sha256(judge.prompt_text.encode("utf-8")).hexdigest()
    if not available:
        return _empty_report(judge, txns, why, prompt_sha)

    firewall = ProcurementFirewall(mandate, judge, audit_log=None)
    gate = DeterministicGate(mandate)
    rows: list[RowResult] = []
    errors = 0

    for t in txns:
        actual_stop = t.label in _OFF_LABELS
        gate_would_catch = gate.evaluate(t).status != GATE_ALLOW
        errored = False
        judge_flag: Optional[bool] = None
        judge_reason = ""
        try:
            verdict = firewall.decide(t)
            decision = verdict.decision
            if verdict.judge is not None:
                judge_flag = verdict.judge.flag
                judge_reason = verdict.judge.reason
            else:
                judge_reason = "; ".join(verdict.reasons)
        except Exception as exc:  # pragma: no cover - judge/runtime dependent
            errors += 1
            errored = True
            decision = ALLOWED  # fail safe in accounting: count as not stopped
            judge_reason = f"ERROR: {type(exc).__name__}: {exc}"
        rows.append(
            RowResult(
                id=t.id,
                label=t.label or "UNLABELED",
                difficulty=t.difficulty,
                tags=t.tags,
                actual_stop=actual_stop,
                gate_would_catch=gate_would_catch,
                decision=decision,
                predicted_stop=(decision != ALLOWED),
                judge_flag=judge_flag,
                judge_reason=judge_reason,
                note=t.note,
                errored=errored,
            )
        )

    cm = ConfusionMatrix()
    for r in rows:
        cm.add(r.predicted_stop, r.actual_stop)

    semantic_delta = sum(
        1 for r in rows if r.actual_stop and not r.gate_would_catch and r.predicted_stop
    )
    sem = [r for r in rows if r.label == LABEL_SEM]
    det = [r for r in rows if r.label == LABEL_DET]
    ok = [r for r in rows if r.label == LABEL_OK]
    inj = [r for r in rows if "injection" in r.tags]

    by_difficulty = _slice_counts(rows, lambda r: [r.difficulty or "unspecified"])
    by_tag = _slice_counts(rows, lambda r: r.tags)

    failures = [
        {
            "id": r.id,
            "label": r.label,
            "type": "FALSE_NEGATIVE" if r.actual_stop else "FALSE_POSITIVE",
            "difficulty": r.difficulty,
            "tags": r.tags,
            "decision": r.decision,
            "note": r.note,
            "judge_reason": r.judge_reason,
        }
        for r in rows
        if r.predicted_stop != r.actual_stop
    ][:max_failures]

    return JudgeReport(
        judge_name=judge.name,
        available=True,
        unavailable_reason=None,
        confusion=asdict(cm),
        precision=round(cm.precision, 4),
        recall=round(cm.recall, 4),
        f1=round(cm.f1, 4),
        semantic_delta=semantic_delta,
        sem_off_total=len(sem),
        sem_off_caught=sum(1 for r in sem if r.predicted_stop),
        det_off_total=len(det),
        det_off_caught=sum(1 for r in det if r.predicted_stop),
        ok_total=len(ok),
        ok_false_positives=sum(1 for r in ok if r.predicted_stop),
        by_difficulty=by_difficulty,
        by_tag=by_tag,
        injection_total=len(inj),
        injection_caught=sum(1 for r in inj if r.predicted_stop),
        failures=failures,
        errors=errors,
        prompt_sha256=prompt_sha,
    )


def evaluate_suite(
    suite_name: str,
    mandate: Mandate,
    dataset_path: Path,
    txns: list[Transaction],
    judges: list[SemanticJudge],
) -> SuiteReport:
    return SuiteReport(
        suite=suite_name,
        dataset_path=str(dataset_path),
        dataset_sha256=_sha256_file(dataset_path),
        n_rows=len(txns),
        mandate_id=mandate.mandate_id,
        label_counts=_label_counts(txns),
        gate_only=evaluate_gate_only(mandate, txns),
        judges=[asdict(evaluate_judge(mandate, txns, j)) for j in judges],
    )


def persist_run(report: RunReport, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.when.replace(":", "").replace("-", "").replace(".", "_")
    out = runs_dir / f"run_{stamp}.json"
    out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    history = runs_dir / "history.jsonl"
    compact = {
        "when": report.when,
        "suites": {
            s["suite"]: {
                "n_rows": s["n_rows"],
                "gate_recall": s["gate_only"]["recall"],
                "judges": {
                    j["judge_name"]: {
                        "available": j["available"],
                        "precision": j["precision"],
                        "recall": j["recall"],
                        "semantic_delta": j["semantic_delta"],
                        "ok_false_positives": j["ok_false_positives"],
                        "injection_caught": f"{j['injection_caught']}/{j['injection_total']}",
                        "prompt_sha256": (j["prompt_sha256"] or "")[:12],
                    }
                    for j in s["judges"]
                },
            }
            for s in report.suites
        },
    }
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(compact) + "\n")
    return out
