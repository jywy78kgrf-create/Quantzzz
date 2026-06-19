"""ProcurementFirewall — composes the deterministic gate and the advisory judge.

Decision rule (the invariants the whole design rests on):
  - gate DENY                -> DENIED      (final; judge is never consulted)
  - gate ESCALATE (no rule)  -> ESCALATED   (deny-by-default)
  - gate ALLOW + judge flag  -> ESCALATED   (off-objective intent suspected)
  - gate ALLOW + judge pass  -> ALLOWED     (the only path to allow)

The judge can therefore only ever turn an allow into an escalate. It can never
allow what the gate denied, and never overturn a DENY.
"""

from __future__ import annotations

from typing import Optional

from .audit import append_record, build_record
from .gate import DeterministicGate
from .judge.base import SemanticJudge
from .models import (
    ALLOWED,
    DENIED,
    ESCALATED,
    GATE_DENY,
    GATE_ESCALATE,
    LAYER_BOTH,
    LAYER_GATE,
    LAYER_GATE_DEFAULT,
    LAYER_JUDGE,
    Mandate,
    Transaction,
    Verdict,
)


class ProcurementFirewall:
    def __init__(
        self,
        mandate: Mandate,
        judge: SemanticJudge,
        audit_log: Optional[str] = None,
    ):
        self.mandate = mandate
        self.gate = DeterministicGate(mandate)
        self.judge = judge
        self.audit_log = audit_log

    def decide(self, txn: Transaction) -> Verdict:
        gate_result = self.gate.evaluate(txn)

        if gate_result.status == GATE_DENY:
            verdict = Verdict(
                transaction_id=txn.id,
                decision=DENIED,
                deciding_layer=LAYER_GATE,
                reasons=gate_result.reasons,
                gate=gate_result,
                judge=None,
            )
        elif gate_result.status == GATE_ESCALATE:
            verdict = Verdict(
                transaction_id=txn.id,
                decision=ESCALATED,
                deciding_layer=LAYER_GATE_DEFAULT,
                reasons=gate_result.reasons,
                gate=gate_result,
                judge=None,
            )
        else:  # GATE_ALLOW -> consult the advisory judge
            judge_result = self.judge.judge(self.mandate.objective, txn)
            if judge_result.flag:
                verdict = Verdict(
                    transaction_id=txn.id,
                    decision=ESCALATED,
                    deciding_layer=LAYER_JUDGE,
                    reasons=[judge_result.reason],
                    gate=gate_result,
                    judge=judge_result,
                )
            else:
                verdict = Verdict(
                    transaction_id=txn.id,
                    decision=ALLOWED,
                    deciding_layer=LAYER_BOTH,
                    reasons=gate_result.reasons + [judge_result.reason],
                    gate=gate_result,
                    judge=judge_result,
                )

        # Every ESCALATE/DENY emits an attributable, signable record.
        if verdict.decision in (DENIED, ESCALATED) and self.audit_log:
            record = build_record(verdict, self.mandate.mandate_id)
            append_record(record, self.audit_log)

        # Defensive assertion of the core invariant.
        assert not (
            gate_result.status == GATE_DENY and verdict.decision == ALLOWED
        ), "invariant violated: judge cannot allow a gate-denied transaction"
        return verdict
