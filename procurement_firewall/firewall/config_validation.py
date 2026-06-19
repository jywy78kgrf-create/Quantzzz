"""Validate a hand-authored mandate config before it is trusted.

Phase 1 mandates are hand-authored, so a typo silently disabling a control is a
real risk. This returns (errors, warnings): errors are structural problems that
should block use; warnings are likely-mistakes worth a human glance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_KNOWN_RULES = {
    "amount_cap_per_po",
    "vendor_allowlist",
    "category_allowlist",
    "approval_tiers",
    "rate_limit",
    "duplicate_window_days",
    "duplicate_amount_tolerance",
    "structuring",
    "require_three_way_match",
    "three_way_match_tolerance",
    "blocked_vendors",
    "vendor_period_spend_cap",
    "required_fields",
    "enforce_currency",
}

_TXN_FIELDS = {
    "id", "vendor", "amount", "category", "currency", "type", "timestamp",
    "invoice_id", "approvers", "memo", "description", "three_way_match",
}


def validate_mandate_dict(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for key in ("mandate_id", "objective"):
        if not data.get(key):
            errors.append(f"missing required top-level field '{key}'")

    obj = data.get("objective", "")
    if isinstance(obj, str) and len(obj.strip()) < 40:
        warnings.append(
            "objective is very short; the semantic judge needs a specific, "
            "scoped purpose to reason about"
        )

    rules = data.get("rules")
    if not isinstance(rules, dict):
        errors.append("'rules' must be an object")
        return errors, warnings

    for key in rules:
        if key not in _KNOWN_RULES:
            warnings.append(f"unknown rule key '{key}' (typo? it will be ignored)")

    # Deny-by-default coverage: without these, most transactions escalate.
    for key in ("amount_cap_per_po", "vendor_allowlist", "category_allowlist"):
        if rules.get(key) is None:
            warnings.append(
                f"'{key}' is not set; transactions cannot be affirmatively covered "
                "on this dimension and will escalate (deny-by-default)"
            )

    cap = rules.get("amount_cap_per_po")
    if cap is not None and (not isinstance(cap, (int, float)) or cap <= 0):
        errors.append("amount_cap_per_po must be a positive number")

    for listkey in ("vendor_allowlist", "category_allowlist", "blocked_vendors",
                    "required_fields"):
        val = rules.get(listkey)
        if val is not None and not isinstance(val, list):
            errors.append(f"{listkey} must be a list")

    # blocked vs allow overlap
    allow = set(rules.get("vendor_allowlist") or [])
    block = set(rules.get("blocked_vendors") or [])
    overlap = allow & block
    if overlap:
        errors.append(f"vendors in both allowlist and blocklist: {sorted(overlap)}")

    tiers = rules.get("approval_tiers") or []
    if not isinstance(tiers, list):
        errors.append("approval_tiers must be a list")
    else:
        for i, t in enumerate(tiers):
            if not isinstance(t, dict) or "threshold" not in t or "required_approvers" not in t:
                errors.append(f"approval_tiers[{i}] needs 'threshold' and 'required_approvers'")

    for objkey in ("rate_limit", "structuring", "vendor_period_spend_cap"):
        v = rules.get(objkey)
        if v is not None and not isinstance(v, dict):
            errors.append(f"{objkey} must be an object")

    rf = rules.get("required_fields") or []
    if isinstance(rf, list):
        for f in rf:
            if f not in _TXN_FIELDS:
                warnings.append(f"required_fields entry '{f}' is not a known transaction field")

    if cap is not None:
        struct = rules.get("structuring") or {}
        agg = struct.get("aggregate_cap")
        if isinstance(agg, (int, float)) and agg < cap:
            warnings.append(
                f"structuring.aggregate_cap ({agg}) is below amount_cap_per_po ({cap}); "
                "single in-cap POs could exceed the structuring aggregate"
            )

    return errors, warnings


def validate_mandate_file(path: str | Path) -> tuple[list[str], list[str]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read/parse mandate file: {exc}"], []
    return validate_mandate_dict(data)
