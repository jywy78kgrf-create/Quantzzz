"""SemanticJudge interface — ADVISORY only.

A judge inspects an action that has already passed every deterministic field and
decides whether its *intent* runs against the mandate's stated purpose. It is
pluggable: anything implementing `evaluate(objective, transaction) -> JudgeResult`
can be dropped in.

Contract / invariants (enforced by the firewall, not the judge):
  - A judge can NEVER allow an action the gate denied.
  - A judge can NEVER override a DENY.
  - The strongest thing a judge can do is raise `flag=True` => ESCALATE on an
    action the gate already allowed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import JudgeResult, Transaction


class SemanticJudge(ABC):
    name: str = "base"

    @abstractmethod
    def evaluate(self, objective: str, transaction: Transaction) -> JudgeResult:
        """Return JudgeResult(flag, reason). flag=True means ESCALATE."""
        raise NotImplementedError

    # Convenience so the firewall always gets a labelled result.
    def judge(self, objective: str, transaction: Transaction) -> JudgeResult:
        result = self.evaluate(objective, transaction)
        if not result.judge_name or result.judge_name == "unknown":
            result.judge_name = self.name
        return result

    def available(self) -> tuple[bool, str]:
        """Whether this judge can actually run (e.g. has an API key)."""
        return True, "ok"
