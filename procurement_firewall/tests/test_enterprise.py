"""Tests for the opt-in enterprise primitives, currency discipline, config
validation, and the LLM judge cache. New primitives must be inert unless the
mandate enables them (so existing mandates/datasets are unaffected)."""

import json

from firewall.config_validation import validate_mandate_dict
from firewall.gate import DeterministicGate
from firewall.models import (
    GATE_ALLOW,
    GATE_DENY,
    GATE_ESCALATE,
    Mandate,
    Transaction,
)

BASE_RULES = {
    "amount_cap_per_po": 50000,
    "vendor_allowlist": ["AWS"],
    "category_allowlist": ["cloud_infrastructure"],
}


def _mandate(**extra_rules):
    rules = dict(BASE_RULES)
    rules.update(extra_rules)
    return Mandate.from_dict({"mandate_id": "T", "objective": "o" * 50, "rules": rules})


def _txn(**kw):
    base = dict(id="T1", vendor="AWS", amount=5000.0, category="cloud_infrastructure")
    base.update(kw)
    return Transaction.from_dict(base)


# --- inertness: a base mandate (no new keys) is unaffected ------------------

def test_base_mandate_allows_clean():
    assert DeterministicGate(_mandate()).evaluate(_txn()).status == GATE_ALLOW


# --- blocked vendors -------------------------------------------------------

def test_blocked_vendor_denies():
    g = DeterministicGate(_mandate(blocked_vendors=["AWS"]))
    res = g.evaluate(_txn())
    assert res.status == GATE_DENY and "blocked_vendor" in res.fired_rules


def test_blocked_vendor_inert_when_unset():
    assert DeterministicGate(_mandate()).evaluate(_txn()).status == GATE_ALLOW


# --- currency discipline ---------------------------------------------------

def test_foreign_currency_escalates():
    res = DeterministicGate(_mandate()).evaluate(_txn(currency="EUR"))
    assert res.status == GATE_ESCALATE


def test_currency_check_can_be_disabled():
    res = DeterministicGate(_mandate(enforce_currency=False)).evaluate(_txn(currency="EUR"))
    assert res.status == GATE_ALLOW


# --- required fields -------------------------------------------------------

def test_required_field_missing_escalates():
    g = DeterministicGate(_mandate(required_fields=["invoice_id"]))
    res = g.evaluate(_txn())  # no invoice_id
    assert res.status == GATE_ESCALATE


def test_required_field_present_allows():
    g = DeterministicGate(_mandate(required_fields=["invoice_id"]))
    res = g.evaluate(_txn(invoice_id="INV-1"))
    assert res.status == GATE_ALLOW


# --- vendor period spend cap ----------------------------------------------

def test_vendor_period_cap_denies():
    g = DeterministicGate(
        _mandate(vendor_period_spend_cap={"cap": 10000, "period_days": 30})
    )
    res = g.evaluate(
        _txn(
            amount=6000,
            timestamp="2026-03-10T00:00:00Z",
            history=[
                {"vendor": "AWS", "amount": 6000, "timestamp": "2026-03-01T00:00:00Z"}
            ],
        )
    )
    assert res.status == GATE_DENY and "vendor_period_spend_cap" in res.fired_rules


def test_vendor_period_cap_respects_window():
    g = DeterministicGate(
        _mandate(vendor_period_spend_cap={"cap": 10000, "period_days": 7})
    )
    res = g.evaluate(
        _txn(
            amount=6000,
            timestamp="2026-03-30T00:00:00Z",
            history=[
                {"vendor": "AWS", "amount": 6000, "timestamp": "2026-03-01T00:00:00Z"}
            ],
        )
    )
    assert res.status == GATE_ALLOW  # prior spend is outside the 7-day window


# --- config validation -----------------------------------------------------

def test_config_validation_flags_overlap_and_missing():
    errors, warnings = validate_mandate_dict(
        {
            "mandate_id": "M",
            "objective": "short",
            "rules": {
                "vendor_allowlist": ["AWS"],
                "blocked_vendors": ["AWS"],
                "amount_cap_per_po": -5,
                "typo_rule": 1,
            },
        }
    )
    assert any("both allowlist and blocklist" in e for e in errors)
    assert any("amount_cap_per_po must be a positive" in e for e in errors)
    assert any("typo_rule" in w for w in warnings)
    assert any("short" in w or "objective" in w for w in warnings)


def test_config_validation_clean_mandate():
    errors, _ = validate_mandate_dict(
        {
            "mandate_id": "M",
            "objective": "x" * 60,
            "rules": dict(BASE_RULES),
        }
    )
    assert errors == []


# --- LLM judge cache (no network) ------------------------------------------

def test_llm_cache_hits_without_calling_api(tmp_path, monkeypatch):
    from firewall.judge.llm import AnthropicJudge

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-dummy")
    cache = tmp_path / "cache.json"
    j = AnthropicJudge(cache_path=cache)
    j._import_error = None
    key = j._cache_key("obj", _txn())
    j._cache.put(key, {"flag": True, "reason": "cached escalate"})

    # No client injected; if the cache is used, evaluate must not need one.
    r = j.evaluate("obj", _txn())
    assert r.flag is True and r.reason == "cached escalate"
    # cache persisted to disk
    assert json.loads(cache.read_text())[key]["flag"] is True
