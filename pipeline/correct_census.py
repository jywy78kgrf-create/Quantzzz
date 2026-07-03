"""Correct the facilitator-multiplication inflation in x402scan's census view.

Discovered during hand inspection (2026-07-03): public.sellers.all.list
aggregates the recipient-stats materialized view through
`LATERAL unnest(facilitator_ids)` and then SUMs — so every metric for a
seller settled by N facilitators is multiplied by N. Validation against
complete deep-pulled transfer histories (data-driven, committed in the
output JSON): sellers with 2/3/4 facilitators show census/actual ratios of
exactly 2.0/3.0/4.0; the transfer-level table itself is accurate (100%
on-chain spot-audit match).

Correction: divide tx_count, total_amount, unique_buyers by the seller's
facilitator count. Exact for single-chain sellers (all but 2 of 163,417).

Input : data/processed/census_sellers.csv          (raw, untouched)
Output: data/processed/census_sellers_corrected.csv
        data/processed/census_inflation_validation.json
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter

from lib import PROCESSED_DIR, utcnow

CENSUS = PROCESSED_DIR / "census_sellers.csv"
FEATURES = PROCESSED_DIR / "deep_features.csv"


def main() -> None:
    # validation evidence: census/pulled ratio vs facilitator count among
    # complete-history deep-pulled sellers
    # Validation needs deep features; on a fresh regeneration this script runs
    # once before deep pulls (correction only needs facilitator counts) and
    # again after, when the validation evidence becomes available.
    feats = {}
    if FEATURES.exists():
        feats = {r["recipient"]: r for r in csv.DictReader(open(FEATURES))
                 if r.get("complete") == "1" and r["n_pulled"] not in ("", "0")}
    ratio_by_nf: dict[int, Counter] = {}
    rows = list(csv.DictReader(open(CENSUS)))
    for r in rows:
        k = r["recipient"].lower() if r["recipient"].startswith("0x") \
            else r["recipient"]
        f = feats.get(k)
        if not f:
            continue
        nf = len(r["facilitators"].split("|"))
        ratio = round(int(r["tx_count"]) / int(f["n_pulled"]), 2)
        ratio_by_nf.setdefault(nf, Counter())[ratio] += 1

    out = PROCESSED_DIR / "census_sellers_corrected.csv"
    with open(out, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["recipient", "chains", "facilitators", "n_facilitators",
                    "tx_count", "total_amount_base_units",
                    "unique_buyers_census", "latest_block_timestamp",
                    "tx_count_raw", "total_amount_raw", "unique_buyers_raw"])
        for r in rows:
            nf = len(r["facilitators"].split("|"))
            w.writerow([
                r["recipient"], r["chains"], r["facilitators"], nf,
                max(1, round(int(r["tx_count"]) / nf)),
                float(r["total_amount_base_units"]) / nf,
                max(1, round(int(r["unique_buyers_census"]) / nf)),
                r["latest_block_timestamp"],
                r["tx_count"], r["total_amount_base_units"],
                r["unique_buyers_census"],
            ])

    validation = {
        "generated": utcnow(),
        "finding": ("x402scan public.sellers.all.list multiplies tx_count, "
                    "total_amount and unique_buyers by the seller's "
                    "facilitator count (LATERAL unnest before SUM in "
                    "apps/scan/src/services/transfers/sellers/list-mv.ts)."),
        "validation_ratio_census_over_pulled_by_facilitator_count": {
            str(nf): dict(c.most_common(6)) for nf, c in
            sorted(ratio_by_nf.items())},
        "raw_total_volume_base_units": sum(
            float(r["total_amount_base_units"]) for r in rows),
        "corrected_total_volume_base_units": sum(
            float(r["total_amount_base_units"]) /
            len(r["facilitators"].split("|")) for r in rows),
        "sellers_affected": sum(
            1 for r in rows if "|" in r["facilitators"]),
        "caveat": ("Division is exact per materialized-view row; only 2 "
                   "multi-chain sellers could mix rows with different "
                   "facilitator arrays."),
    }
    json.dump(validation,
              open(PROCESSED_DIR / "census_inflation_validation.json", "w"),
              indent=2)
    print(f"[correct] wrote {out}")
    print(json.dumps({k: v for k, v in validation.items()
                      if k != "validation_ratio_census_over_pulled_by_facilitator_count"},
                     indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
