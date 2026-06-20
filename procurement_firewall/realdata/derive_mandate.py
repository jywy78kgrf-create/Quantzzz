#!/usr/bin/env python3
"""Derive a plausible Mandate from the real data's actual distributions.

Everything here is computed from the cached USAspending slice, not guessed:
  - amount cap  = p99.5 of positive award amounts (=> ~0.5% over by construction)
  - vendor allowlist = top-100 vendors by spend (covers ~79.5% of rows)
  - category allowlist = the slice's single NAICS description
Primitives the data cannot support are deliberately LEFT OUT and the reason is
recorded, so the validation doesn't fabricate flags:
  - approval_tiers      : no approver data in federal award records
  - three_way_match     : no receipt/invoice amounts
  - rate_limit          : a per-program cadence control; this slice aggregates
                          49 agencies, so a global rate limit is not meaningful
  - structuring         : same reason (per-program assumption)
Duplicate detection IS enabled (award IDs act as invoice ids), to test whether
the invoice-id requirement prevents false duplicate flags on the 692 real rows
that share vendor+amount.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
CACHE = HERE / "datasets" / "real" / "usaspending_541512_fy2024.jsonl"
OUT = HERE / "mandates" / "usaspending_541512_fy2024.json"

TOP_VENDORS = 100
CAP_PCTILE = 99.5


def pct(p: float, arr: list[float]) -> float:
    i = min(len(arr) - 1, int(p / 100 * len(arr)))
    return arr[i]


def main() -> int:
    rows = [json.loads(line) for line in CACHE.open()]
    pos = sorted(r["amount"] for r in rows if r["amount"] > 0)
    cap_raw = pct(CAP_PCTILE, pos)
    # round up to a clean figure
    cap = float(math.ceil(cap_raw / 1_000_000) * 1_000_000)

    spend: dict[str, float] = {}
    for r in rows:
        spend[r["vendor"]] = spend.get(r["vendor"], 0.0) + max(0.0, r["amount"])
    top = [v for v, _ in sorted(spend.items(), key=lambda kv: kv[1], reverse=True)[:TOP_VENDORS]]
    coverage_rows = sum(1 for r in rows if r["vendor"] in set(top)) / len(rows)

    category = "Computer Systems Design Services"

    mandate = {
        "mandate_id": "MND-USASPENDING-541512-FY2024",
        "owner": "Derived from USAspending NAICS 541512 FY2024 slice",
        "effective_date": "2023-10-01",
        "currency": "USD",
        "objective": (
            "Fund FY2024 computer-systems-design (NAICS 541512) information-technology "
            "services contracts for U.S. federal agencies: software and systems "
            "engineering, design, integration, modernization, cybersecurity, and "
            "operations-and-maintenance of government IT systems, delivered under "
            "contract by approved IT services vendors. Covered spend is IT "
            "systems-design and related professional services for government systems. "
            "NOT covered: non-IT goods or services, construction or facilities, "
            "vehicles or hardware procurement unrelated to systems design, relocation "
            "or travel, marketing/outreach, or any purchase whose described purpose is "
            "not the design/engineering/operation of a federal IT system."
        ),
        "rules": {
            "amount_cap_per_po": cap,
            "vendor_allowlist": top,
            "category_allowlist": [category],
            "duplicate_window_days": 365,
            "duplicate_amount_tolerance": 0.0,
            "enforce_currency": True,
            # Intentionally omitted (see module docstring): approval_tiers,
            # three_way_match, rate_limit, structuring.
        },
        "_derivation": {
            "source_rows": len(rows),
            "amount_cap_percentile": CAP_PCTILE,
            "amount_cap_raw": cap_raw,
            "amount_cap_rounded": cap,
            "expected_cap_fp_pct_by_construction": round(100 - CAP_PCTILE, 3),
            "vendor_allowlist_size": TOP_VENDORS,
            "vendor_allowlist_row_coverage": round(coverage_rows, 4),
            "expected_allowlist_fp_pct_by_construction": round(100 * (1 - coverage_rows), 2),
            "category": category,
        },
    }
    OUT.write_text(json.dumps(mandate, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  amount cap (p{CAP_PCTILE}): ${cap:,.0f}  -> ~{100-CAP_PCTILE}% over by construction")
    print(f"  vendor allowlist: top {TOP_VENDORS} vendors, covers {coverage_rows:.1%} of rows")
    print(f"  -> ~{100*(1-coverage_rows):.1f}% of real rows are off-allowlist (built-in FP)")
    print(f"  category allowlist: ['{category}'] (single-NAICS slice -> ~0% FP)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
