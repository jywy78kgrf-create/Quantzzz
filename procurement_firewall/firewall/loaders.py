"""Loading mandates and transaction batches from disk."""

from __future__ import annotations

import json
from pathlib import Path

from .models import Mandate, Transaction


def load_mandate(path: str | Path) -> Mandate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Mandate.from_dict(data)


def load_transactions(path: str | Path) -> list[Transaction]:
    """Load a transaction batch from .jsonl (one object per line) or a .json array."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[dict] = []
    if text[0] == "[":
        rows = json.loads(text)
    else:
        for ln, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {ln}: {exc}") from exc
    return [Transaction.from_dict(r) for r in rows]
