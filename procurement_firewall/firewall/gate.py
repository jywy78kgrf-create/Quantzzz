"""DeterministicGate — frozen, generic primitives. No LLM, no reasoning.

This module is the hard floor. It evaluates only quantifiable fields. A DENY is
final and cannot be argued with or overturned by anything downstream. Per-mandate
behaviour comes ONLY from the mandate config passed in — there is intentionally
no mandate-specific code here. Adding a new policy is a config change, never a
gate change.

Outcomes:
  GATE_DENY     -- a quantifiable rule was violated. Final.
  GATE_ESCALATE -- deny-by-default: no rule affirmatively covers this action.
  GATE_ALLOW    -- deterministically clean; hand off to the advisory judge.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .models import (
    GATE_ALLOW,
    GATE_DENY,
    GATE_ESCALATE,
    GateResult,
    Mandate,
    Transaction,
    _parse_ts,
)

_PO_TYPE = "purchase_order"
_INVOICE_TYPE = "invoice_payment"
_KNOWN_TYPES = {_PO_TYPE, _INVOICE_TYPE}


def _norm_invoice(value: str | None) -> str:
    """Canonicalise an invoice id for fuzzy duplicate comparison."""
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _similar_invoice(a: str | None, b: str | None) -> bool:
    """~invoice id: equal after normalisation, substring, or edit distance <= 2."""
    na, nb = _norm_invoice(a), _norm_invoice(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    return _levenshtein(na, nb) <= 2


class DeterministicGate:
    """Evaluates a single transaction against a mandate's quantifiable rules."""

    def __init__(self, mandate: Mandate):
        self.mandate = mandate

    def evaluate(self, txn: Transaction) -> GateResult:
        m = self.mandate
        denies: list[str] = []
        fired: list[str] = []

        # --- deny-by-default coverage: unknown type or unspecified policy ---
        escalate_reasons: list[str] = []
        if txn.type not in _KNOWN_TYPES:
            escalate_reasons.append(
                f"transaction type '{txn.type}' is not covered by any policy rule"
            )
        if m.vendor_allowlist is None:
            escalate_reasons.append("mandate defines no vendor allowlist; cannot affirm vendor")
        if m.category_allowlist is None:
            escalate_reasons.append(
                "mandate defines no category allowlist; cannot affirm spend category"
            )
        if m.amount_cap_per_po is None:
            escalate_reasons.append("mandate defines no per-PO amount cap; cannot affirm amount")

        # --- hard primitives (each independent; collect ALL violations) ---
        if m.amount_cap_per_po is not None and txn.amount > m.amount_cap_per_po:
            denies.append(
                f"amount {txn.amount:.2f} exceeds per-PO cap {m.amount_cap_per_po:.2f}"
            )
            fired.append("amount_cap")

        if m.vendor_allowlist is not None and txn.vendor not in m.vendor_allowlist:
            denies.append(f"vendor '{txn.vendor}' is not on the allowlist")
            fired.append("vendor_allowlist")

        if m.category_allowlist is not None and txn.category not in m.category_allowlist:
            denies.append(f"category '{txn.category}' is not on the allowlist")
            fired.append("category_allowlist")

        required = m.required_approvers_for(txn.amount)
        if required > 0:
            present = len({a for a in txn.approvers if a})
            if present < required:
                denies.append(
                    f"amount {txn.amount:.2f} requires {required} approver(s); "
                    f"{present} present"
                )
                fired.append("approval_tier")

        dup = self._check_duplicate(txn)
        if dup:
            denies.append(dup)
            fired.append("duplicate")

        rate = self._check_rate_limit(txn)
        if rate:
            denies.append(rate)
            fired.append("rate_limit")

        struct = self._check_structuring(txn)
        if struct:
            denies.append(struct)
            fired.append("structuring")

        twm = self._check_three_way_match(txn)
        if twm:
            if twm[0] == "deny":
                denies.append(twm[1])
                fired.append("three_way_match")
            else:  # escalate: required but data absent
                escalate_reasons.append(twm[1])

        if denies:
            return GateResult(status=GATE_DENY, reasons=denies, fired_rules=fired)
        if escalate_reasons:
            return GateResult(
                status=GATE_ESCALATE, reasons=escalate_reasons, fired_rules=["deny_by_default"]
            )
        return GateResult(status=GATE_ALLOW, reasons=["all deterministic checks passed"])

    # ------------------------------------------------------------------ #

    def _check_duplicate(self, txn: Transaction) -> str | None:
        m = self.mandate
        if m.duplicate_window_days is None or not txn.history:
            return None
        ts = txn.parsed_timestamp
        tol = m.duplicate_amount_tolerance
        for prior in txn.history:
            if str(prior.get("vendor")) != txn.vendor:
                continue
            pamt = float(prior.get("amount", 0.0))
            if abs(pamt - txn.amount) > tol * max(abs(txn.amount), 1.0):
                continue
            if not _similar_invoice(prior.get("invoice_id"), txn.invoice_id):
                continue
            if ts is not None:
                pts = _parse_ts(prior.get("timestamp"))
                if pts is not None and abs((ts - pts).days) > m.duplicate_window_days:
                    continue
            return (
                f"duplicate of prior {prior.get('id', '?')}: same vendor '{txn.vendor}', "
                f"amount {txn.amount:.2f}, invoice ~'{prior.get('invoice_id')}' within "
                f"{m.duplicate_window_days}d window"
            )
        return None

    def _check_rate_limit(self, txn: Transaction) -> str | None:
        m = self.mandate
        if not m.rate_limit:
            return None
        max_pos = int(m.rate_limit.get("max_pos", 0))
        period = int(m.rate_limit.get("period_days", 0))
        if max_pos <= 0 or period <= 0:
            return None
        ts = txn.parsed_timestamp
        count = 1  # the current PO
        for prior in txn.history:
            if prior.get("type", _PO_TYPE) != _PO_TYPE:
                continue
            if ts is not None:
                pts = _parse_ts(prior.get("timestamp"))
                if pts is not None and (ts - pts) > timedelta(days=period):
                    continue
            count += 1
        if count > max_pos:
            return (
                f"rate limit exceeded: {count} POs within {period}d window "
                f"(max {max_pos})"
            )
        return None

    def _check_structuring(self, txn: Transaction) -> str | None:
        m = self.mandate
        if not m.structuring or not txn.history:
            return None
        window = int(m.structuring.get("window_days", 0))
        agg_cap = float(m.structuring.get("aggregate_cap", 0.0))
        if window <= 0 or agg_cap <= 0:
            return None
        ts = txn.parsed_timestamp
        total = txn.amount
        n = 1
        for prior in txn.history:
            if str(prior.get("vendor")) != txn.vendor:
                continue
            if ts is not None:
                pts = _parse_ts(prior.get("timestamp"))
                if pts is not None and abs((ts - pts).days) > window:
                    continue
            total += float(prior.get("amount", 0.0))
            n += 1
        if n >= 2 and total > agg_cap:
            return (
                f"structuring suspected: {n} POs to '{txn.vendor}' sum to {total:.2f} "
                f"(> aggregate cap {agg_cap:.2f}) within {window}d, each individually sub-cap"
            )
        return None

    def _check_three_way_match(self, txn: Transaction) -> tuple[str, str] | None:
        m = self.mandate
        if not m.require_three_way_match or txn.type != _INVOICE_TYPE:
            return None
        data = txn.three_way_match
        if not data:
            return ("escalate", "three-way match required for invoice but no match data present")
        try:
            po = float(data["po_amount"])
            receipt = float(data["receipt_amount"])
            invoice = float(data["invoice_amount"])
        except (KeyError, TypeError, ValueError):
            return ("escalate", "three-way match data is incomplete or malformed")
        tol = m.three_way_match_tolerance
        base = max(abs(po), abs(receipt), abs(invoice), 1.0)
        spread = max(po, receipt, invoice) - min(po, receipt, invoice)
        if spread > tol * base:
            return (
                "deny",
                f"three-way match failed: PO {po:.2f}, receipt {receipt:.2f}, "
                f"invoice {invoice:.2f} disagree beyond {tol:.0%} tolerance",
            )
        return None
