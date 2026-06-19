"""Core data models for the Off-Objective Procurement Firewall.

These are plain dataclasses with explicit, validated construction from JSON so
that the two layers (deterministic gate, semantic judge) and the eval harness
all agree on exactly one schema. Nothing here makes a decision; this module is
only the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Decisions and layers
# ---------------------------------------------------------------------------

# Final verdicts surfaced to the caller.
ALLOWED = "ALLOWED"
DENIED = "DENIED"
ESCALATED = "ESCALATED"

# Internal gate outcomes. DENY is final and can never be overturned. ALLOW
# means "deterministically clean, hand off to the advisory judge". ESCALATE
# means "no policy rule affirmatively covers this action" (deny-by-default).
GATE_ALLOW = "GATE_ALLOW"
GATE_DENY = "GATE_DENY"
GATE_ESCALATE = "GATE_ESCALATE"

# Which layer is accountable for the final verdict.
LAYER_GATE = "deterministic_gate"
LAYER_GATE_DEFAULT = "deterministic_gate:deny_by_default"
LAYER_JUDGE = "semantic_judge"
LAYER_BOTH = "gate_allow+judge_pass"


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z'."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Mandate (hand-authored config; Phase 1 does NOT derive these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalTier:
    threshold: float
    required_approvers: int


@dataclass(frozen=True)
class Mandate:
    mandate_id: str
    objective: str
    owner: str = "unspecified"
    effective_date: Optional[str] = None
    currency: str = "USD"

    # Deterministic primitives. `None` means "the mandate does not speak to this
    # dimension" — which, for the allowlists/cap, forces deny-by-default.
    amount_cap_per_po: Optional[float] = None
    vendor_allowlist: Optional[list[str]] = None
    category_allowlist: Optional[list[str]] = None
    approval_tiers: list[ApprovalTier] = field(default_factory=list)
    rate_limit: Optional[dict[str, Any]] = None
    duplicate_window_days: Optional[int] = None
    duplicate_amount_tolerance: float = 0.0
    structuring: Optional[dict[str, Any]] = None
    require_three_way_match: bool = False
    three_way_match_tolerance: float = 0.0

    # Opt-in primitives (active only when configured; absent => no behaviour
    # change, which keeps existing mandates/datasets stable).
    blocked_vendors: Optional[list[str]] = None  # hard denylist (sanctions/blacklist)
    vendor_period_spend_cap: Optional[dict[str, Any]] = None  # {cap, period_days}
    required_fields: Optional[list[str]] = None  # must be present & non-empty, else escalate
    enforce_currency: bool = True  # txn currency must match mandate currency

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Mandate":
        rules = data.get("rules", {})
        tiers = [
            ApprovalTier(float(t["threshold"]), int(t["required_approvers"]))
            for t in rules.get("approval_tiers", []) or []
        ]
        # Normalise allowlists to a canonical lower/stripped form for matching.
        vendors = rules.get("vendor_allowlist")
        cats = rules.get("category_allowlist")
        return Mandate(
            mandate_id=data["mandate_id"],
            objective=data["objective"],
            owner=data.get("owner", "unspecified"),
            effective_date=data.get("effective_date"),
            currency=data.get("currency", "USD"),
            amount_cap_per_po=(
                float(rules["amount_cap_per_po"])
                if rules.get("amount_cap_per_po") is not None
                else None
            ),
            vendor_allowlist=([str(v) for v in vendors] if vendors is not None else None),
            category_allowlist=([str(c) for c in cats] if cats is not None else None),
            approval_tiers=tiers,
            rate_limit=rules.get("rate_limit"),
            duplicate_window_days=rules.get("duplicate_window_days"),
            duplicate_amount_tolerance=float(rules.get("duplicate_amount_tolerance", 0.0)),
            structuring=rules.get("structuring"),
            require_three_way_match=bool(rules.get("require_three_way_match", False)),
            three_way_match_tolerance=float(rules.get("three_way_match_tolerance", 0.0)),
            blocked_vendors=(
                [str(v) for v in rules["blocked_vendors"]]
                if rules.get("blocked_vendors") is not None
                else None
            ),
            vendor_period_spend_cap=rules.get("vendor_period_spend_cap"),
            required_fields=(
                [str(f) for f in rules["required_fields"]]
                if rules.get("required_fields") is not None
                else None
            ),
            enforce_currency=bool(rules.get("enforce_currency", True)),
        )

    def required_approvers_for(self, amount: float) -> int:
        """Highest approver requirement among tiers whose threshold is met."""
        req = 0
        for tier in self.approval_tiers:
            if amount >= tier.threshold:
                req = max(req, tier.required_approvers)
        return req


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Transaction:
    id: str
    vendor: str
    amount: float
    category: str
    currency: str = "USD"
    type: str = "purchase_order"  # or "invoice_payment"
    timestamp: Optional[str] = None
    invoice_id: Optional[str] = None
    approvers: list[str] = field(default_factory=list)
    memo: str = ""
    description: str = ""
    three_way_match: Optional[dict[str, float]] = None
    # Prior transactions in the lookback window, embedded so a single row is
    # self-contained for duplicate / rate-limit / structuring checks.
    history: list[dict[str, Any]] = field(default_factory=list)

    # ---- dataset-only metadata (NEVER read by the firewall decision) ----
    label: Optional[str] = None  # "ok" | "det_off" | "sem_off"
    note: Optional[str] = None  # author's rationale, for humans only
    difficulty: Optional[str] = None  # "easy" | "hard" | "borderline"
    tags: list[str] = field(default_factory=list)  # e.g. ["injection","net_new"]

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Transaction":
        return Transaction(
            id=str(data["id"]),
            vendor=str(data["vendor"]),
            amount=float(data["amount"]),
            category=str(data["category"]),
            currency=data.get("currency", "USD"),
            type=data.get("type", "purchase_order"),
            timestamp=data.get("timestamp"),
            invoice_id=data.get("invoice_id"),
            approvers=list(data.get("approvers", []) or []),
            memo=data.get("memo", "") or "",
            description=data.get("description", "") or "",
            three_way_match=data.get("three_way_match"),
            history=list(data.get("history", []) or []),
            label=data.get("label"),
            note=data.get("note"),
            difficulty=data.get("difficulty"),
            tags=list(data.get("tags", []) or []),
        )

    @property
    def parsed_timestamp(self) -> Optional[datetime]:
        return _parse_ts(self.timestamp)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    status: str  # GATE_ALLOW | GATE_DENY | GATE_ESCALATE
    reasons: list[str] = field(default_factory=list)
    # Names of the primitives that fired (for the semantic-delta accounting:
    # if the gate denied, the judge gets no structural credit for that row).
    fired_rules: list[str] = field(default_factory=list)


@dataclass
class JudgeResult:
    flag: bool  # True => ESCALATE (off-objective intent suspected)
    reason: str
    judge_name: str = "unknown"


@dataclass
class Verdict:
    transaction_id: str
    decision: str  # ALLOWED | DENIED | ESCALATED
    deciding_layer: str
    reasons: list[str]
    gate: GateResult
    judge: Optional[JudgeResult] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "decision": self.decision,
            "deciding_layer": self.deciding_layer,
            "reasons": self.reasons,
            "gate": {
                "status": self.gate.status,
                "reasons": self.gate.reasons,
                "fired_rules": self.gate.fired_rules,
            },
            "judge": (
                {
                    "flag": self.judge.flag,
                    "reason": self.judge.reason,
                    "judge_name": self.judge.judge_name,
                }
                if self.judge is not None
                else None
            ),
        }
