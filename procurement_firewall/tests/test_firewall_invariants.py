"""The non-negotiable invariants: the judge can never overturn the gate."""

from firewall.firewall import ProcurementFirewall
from firewall.judge.base import SemanticJudge
from firewall.models import (
    ALLOWED,
    DENIED,
    ESCALATED,
    JudgeResult,
    Mandate,
    Transaction,
)

MANDATE = Mandate.from_dict(
    {
        "mandate_id": "TEST",
        "objective": "keep the existing platform running",
        "rules": {
            "amount_cap_per_po": 50000,
            "vendor_allowlist": ["AWS"],
            "category_allowlist": ["cloud_infrastructure"],
            "approval_tiers": [{"threshold": 10000, "required_approvers": 1}],
        },
    }
)


class AlwaysPassJudge(SemanticJudge):
    name = "always_pass"

    def evaluate(self, objective, transaction):
        return JudgeResult(flag=False, reason="rubber stamp", judge_name=self.name)


class AlwaysFlagJudge(SemanticJudge):
    name = "always_flag"

    def evaluate(self, objective, transaction):
        return JudgeResult(flag=True, reason="flag everything", judge_name=self.name)


def _txn(**kw):
    base = dict(id="T1", vendor="AWS", amount=5000.0, category="cloud_infrastructure")
    base.update(kw)
    return Transaction.from_dict(base)


def test_gate_deny_is_final_even_if_judge_passes():
    fw = ProcurementFirewall(MANDATE, AlwaysPassJudge())
    v = fw.decide(_txn(vendor="Oracle"))  # off-allowlist => gate DENY
    assert v.decision == DENIED
    assert v.judge is None  # judge never consulted on a denial


def test_gate_allow_plus_judge_flag_escalates():
    fw = ProcurementFirewall(MANDATE, AlwaysFlagJudge())
    v = fw.decide(_txn())
    assert v.decision == ESCALATED
    assert v.deciding_layer == "semantic_judge"


def test_gate_allow_plus_judge_pass_allows():
    fw = ProcurementFirewall(MANDATE, AlwaysPassJudge())
    v = fw.decide(_txn())
    assert v.decision == ALLOWED


def test_only_path_to_allowed_is_both_layers():
    # An always-flag judge can never produce an ALLOWED verdict.
    fw = ProcurementFirewall(MANDATE, AlwaysFlagJudge())
    for vendor in ("AWS",):
        v = fw.decide(_txn(vendor=vendor))
        assert v.decision != ALLOWED


def test_deny_by_default_escalates_unmatched():
    fw = ProcurementFirewall(MANDATE, AlwaysPassJudge())
    v = fw.decide(_txn(type="wire_transfer"))
    assert v.decision == ESCALATED
    assert v.deciding_layer == "deterministic_gate:deny_by_default"
