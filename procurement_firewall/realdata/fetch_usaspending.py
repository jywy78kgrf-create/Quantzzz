#!/usr/bin/env python3
"""Fetch a real slice of US federal procurement and cache it locally.

Source: USAspending.gov API v2, endpoint /api/v2/search/spending_by_award/.
Slice:  contract awards (award_type_codes A,B,C,D), NAICS 541512
        (Computer Systems Design Services), FY2024 activity window
        (action within 2023-10-01 .. 2024-09-30), ordered by Start Date desc,
        first ~10,000 awards.

Why this slice: a single NAICS sector across agencies is a coherent "domain"
that one spending mandate can plausibly cover (an IT systems-design program),
which is what makes the false-positive test meaningful rather than just
"the long tail isn't on the allowlist".

Cache: datasets/real/usaspending_541512_fy2024.jsonl  (skipped if present).
Provenance: datasets/real/PROVENANCE.json.
Run again with --refresh to re-download.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "datasets" / "real" / "usaspending_541512_fy2024.jsonl"
PROV = HERE / "datasets" / "real" / "PROVENANCE.json"
ENDPOINT = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

NAICS = "541512"
START, END = "2023-10-01", "2024-09-30"
TARGET = 10000
PAGE_LIMIT = 100

FIELDS = [
    "Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
    "Awarding Sub Agency", "Start Date", "NAICS", "Description",
    "Contract Award Type",
]


def _post(page: int) -> dict:
    body = {
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "time_period": [{"start_date": START, "end_date": END}],
            "naics_codes": [NAICS],
        },
        "fields": FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "sort": "Start Date",
        "order": "desc",
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize(r: dict) -> dict:
    naics = r.get("NAICS") or {}
    desc = (r.get("Description") or "").strip()
    start = r.get("Start Date")
    ts = f"{start}T00:00:00Z" if start else None
    return {
        "id": f"USA-{r.get('internal_id')}",
        "award_id": r.get("Award ID"),
        "vendor": (r.get("Recipient Name") or "UNKNOWN").strip(),
        "amount": float(r.get("Award Amount") or 0.0),
        "category": (naics.get("description") or "").strip().title() or "Unknown",
        "naics_code": naics.get("code"),
        "agency": r.get("Awarding Agency"),
        "sub_agency": r.get("Awarding Sub Agency"),
        "award_type": r.get("Contract Award Type"),
        "timestamp": ts,
        "invoice_id": r.get("Award ID"),
        "memo": desc,
        "description": desc,
        "type": "purchase_order",
        "currency": "USD",
        "source": "usaspending.gov",
        "label": "real",  # ground truth for the validation harness: legitimate spend
    }


def main(argv: list[str]) -> int:
    if OUT.exists() and "--refresh" not in argv:
        n = sum(1 for _ in OUT.open())
        print(f"cache present: {OUT} ({n} rows) — use --refresh to re-download")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    rows: list[dict] = []
    page = 1
    while len(rows) < TARGET:
        for attempt in range(4):
            try:
                data = _post(page)
                break
            except Exception as exc:  # network hiccup -> backoff
                if attempt == 3:
                    print(f"giving up at page {page}: {exc}", file=sys.stderr)
                    data = {"results": [], "page_metadata": {"hasNext": False}}
                time.sleep(2 ** attempt)
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            rid = str(r.get("internal_id"))
            if rid in seen:
                continue
            seen.add(rid)
            rows.append(_normalize(r))
        print(f"page {page}: +{len(results)} (total {len(rows)})")
        if not data.get("page_metadata", {}).get("hasNext"):
            break
        page += 1
        time.sleep(0.2)

    rows = rows[:TARGET]
    with OUT.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    prov = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "USAspending.gov API v2 /api/v2/search/spending_by_award/",
        "filters": {
            "award_type_codes": ["A", "B", "C", "D"],
            "naics": NAICS,
            "naics_description": "Computer Systems Design Services",
            "time_period": {"start": START, "end": END},
            "sort": "Start Date desc",
        },
        "rows": len(rows),
        "note": (
            "Award-level rows; 'Award Amount' is the award's current total value. "
            "time_period matches awards with action in the window; Start Date may "
            "predate it. All rows are real, legitimate federal awards (label=real)."
        ),
    }
    PROV.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    print(f"wrote {len(rows)} rows -> {OUT}")
    print(f"provenance -> {PROV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
