"""Attributable audit records for every ESCALATE / DENY.

Each record is human-readable AND structured, and carries a content hash that
stands in for a signature: who/what/why/when, hashed so any later tampering is
detectable. Records are appended to a JSONL log.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Verdict


def build_record(
    verdict: Verdict,
    mandate_id: str,
    actor: str = "procurement_firewall",
) -> dict[str, Any]:
    """Construct a signable record for a single verdict."""
    body = {
        "when": datetime.now(timezone.utc).isoformat(),
        "who": actor,  # the system component accountable for emitting this
        "mandate_id": mandate_id,
        "what": {
            "transaction_id": verdict.transaction_id,
            "decision": verdict.decision,
            "deciding_layer": verdict.deciding_layer,
        },
        "why": verdict.reasons,
        "detail": verdict.to_dict(),
    }
    signature = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    body["signature_sha256"] = signature
    return body


def human_summary(record: dict[str, Any]) -> str:
    what = record["what"]
    why = "; ".join(record["why"]) if record["why"] else "(no reason)"
    return (
        f"[{record['when']}] {what['decision']} {what['transaction_id']} "
        f"by {what['deciding_layer']} :: {why}  (sig {record['signature_sha256'][:12]})"
    )


def append_record(record: dict[str, Any], log_path: str | Path) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
