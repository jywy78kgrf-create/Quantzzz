"""Deterministic gate primitive tests. These pin the frozen behaviour."""

from firewall.gate import DeterministicGate
from firewall.models import GATE_ALLOW, GATE_DENY, GATE_ESCALATE, Mandate, Transaction

MANDATE = Mandate.from_dict(
    {
        "mandate_id": "TEST",
        "objective": "test objective",
        "rules": {
            "amount_cap_per_po": 50000,
            "vendor_allowlist": ["AWS", "Datadog"],
            "category_allowlist": ["cloud_infrastructure", "observability"],
            "approval_tiers": [
                {"threshold": 10000, "required_approvers": 1},
                {"threshold": 25000, "required_approvers": 2},
            ],
            "rate_limit": {"max_pos": 3, "period_days": 7},
            "duplicate_window_days": 45,
            "duplicate_amount_tolerance": 0.01,
            "structuring": {"window_days": 7, "aggregate_cap": 50000},
            "require_three_way_match": True,
            "three_way_match_tolerance": 0.02,
        },
    }
)

GATE = DeterministicGate(MANDATE)


def _txn(**kw):
    base = dict(
        id="T1",
        vendor="AWS",
        amount=5000.0,
        category="cloud_infrastructure",
        type="purchase_order",
        timestamp="2026-03-01T10:00:00Z",
        approvers=[],
    )
    base.update(kw)
    return Transaction.from_dict(base)


def test_clean_allows():
    assert GATE.evaluate(_txn()).status == GATE_ALLOW


def test_amount_cap_denies():
    res = GATE.evaluate(_txn(amount=60000, approvers=["a", "b"]))
    assert res.status == GATE_DENY
    assert "amount_cap" in res.fired_rules


def test_vendor_allowlist_denies():
    res = GATE.evaluate(_txn(vendor="Oracle"))
    assert res.status == GATE_DENY
    assert "vendor_allowlist" in res.fired_rules


def test_category_allowlist_denies():
    res = GATE.evaluate(_txn(category="office_equipment"))
    assert res.status == GATE_DENY
    assert "category_allowlist" in res.fired_rules


def test_approval_tier_denies():
    res = GATE.evaluate(_txn(amount=30000, approvers=["only_one"]))
    assert res.status == GATE_DENY
    assert "approval_tier" in res.fired_rules


def test_approval_tier_passes_with_enough_approvers():
    assert GATE.evaluate(_txn(amount=30000, approvers=["a", "b"])).status == GATE_ALLOW


def test_duplicate_detection():
    res = GATE.evaluate(
        _txn(
            invoice_id="INV-AWS-100",
            history=[
                {
                    "id": "P0",
                    "vendor": "AWS",
                    "amount": 5000.0,
                    "invoice_id": "INV-AWS-100",
                    "timestamp": "2026-02-20T10:00:00Z",
                }
            ],
        )
    )
    assert res.status == GATE_DENY
    assert "duplicate" in res.fired_rules


def test_fuzzy_duplicate_detection():
    # near-identical invoice id (edit distance <= 2) still trips duplicate
    res = GATE.evaluate(
        _txn(
            invoice_id="INVAWS100",
            history=[
                {
                    "id": "P0",
                    "vendor": "AWS",
                    "amount": 5000.0,
                    "invoice_id": "INV-AWS-100",
                    "timestamp": "2026-02-25T10:00:00Z",
                }
            ],
        )
    )
    assert res.status == GATE_DENY


def test_structuring_detection():
    hist = [
        {"id": "P1", "vendor": "AWS", "amount": 20000.0, "timestamp": "2026-02-28T10:00:00Z"},
        {"id": "P2", "vendor": "AWS", "amount": 20000.0, "timestamp": "2026-03-01T08:00:00Z"},
    ]
    res = GATE.evaluate(_txn(amount=20000, approvers=["a", "b"], history=hist))
    assert res.status == GATE_DENY
    assert "structuring" in res.fired_rules


def test_rate_limit_detection():
    hist = [
        {"id": f"P{i}", "vendor": "AWS", "amount": 100.0,
         "type": "purchase_order", "timestamp": "2026-02-28T10:00:00Z"}
        for i in range(3)
    ]
    res = GATE.evaluate(_txn(history=hist))
    assert res.status == GATE_DENY
    assert "rate_limit" in res.fired_rules


def test_three_way_match_mismatch_denies():
    res = GATE.evaluate(
        _txn(
            type="invoice_payment",
            three_way_match={"po_amount": 5000, "receipt_amount": 5000, "invoice_amount": 9000},
        )
    )
    assert res.status == GATE_DENY
    assert "three_way_match" in res.fired_rules


def test_three_way_match_consistent_allows():
    res = GATE.evaluate(
        _txn(
            type="invoice_payment",
            three_way_match={"po_amount": 5000, "receipt_amount": 5000, "invoice_amount": 5050},
        )
    )
    assert res.status == GATE_ALLOW


def test_deny_by_default_unknown_type():
    res = GATE.evaluate(_txn(type="wire_transfer"))
    assert res.status == GATE_ESCALATE


def test_deny_by_default_unspecified_allowlist():
    m = Mandate.from_dict(
        {"mandate_id": "T", "objective": "o", "rules": {"amount_cap_per_po": 100}}
    )
    res = DeterministicGate(m).evaluate(_txn(amount=10))
    assert res.status == GATE_ESCALATE


def test_multiple_violations_all_reported():
    res = GATE.evaluate(_txn(vendor="Oracle", category="travel", amount=99999))
    assert res.status == GATE_DENY
    assert {"vendor_allowlist", "category_allowlist", "amount_cap"} <= set(res.fired_rules)
