"""Phase 3 analysis: every figure in the report traces to this script.

Outputs (analysis/out/):
  headline_numbers.json   bucket shares (sellers + corrected volume)
  concentration.json      top-10/top-100 volume shares, cumulative curve
  cohort_survival.json    monthly first-seen cohorts (control sample), 60-day survival
  liveness_summary.json   probe outcome funnel
All volume figures use facilitator-inflation-CORRECTED values (see
data/processed/census_inflation_validation.json).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from lib import PROCESSED_DIR, utcnow  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
NOW = datetime.now(timezone.utc)


def headline() -> dict:
    d = json.load(open(PROCESSED_DIR / "final_bucket_summary.json"))
    cov = json.load(open(PROCESSED_DIR / "coverage_bazaar_vs_census.json"))
    live = liveness()
    out = {
        "generated": utcnow(),
        "total_sellers": d["total_sellers"],
        "buckets": d["buckets"],
        "headline_pair": {
            "active_legitimate_seller_share": d["buckets"]["ACTIVE_LEGITIMATE"]["share_sellers"],
            "active_legitimate_volume_share": d["buckets"]["ACTIVE_LEGITIMATE"]["share_volume"],
        },
        "liveness_headline": {
            "valid_x402_rate_all_probed": live["valid_402_rate"],
            "valid_x402_rate_bazaar_resources": live["bazaar"]["valid_402_rate"],
        },
        "bazaar_collapse": {
            "listings": cov["bazaar_resources"],
            "unique_paytos": cov["bazaar_unique_paytos"],
            "paytos_with_zero_indexed_tx": cov["paytos_absent_from_index"],
            "zero_tx_share": cov["index_miss_rate_listed_services"],
        },
    }
    json.dump(out, open(OUT / "headline_numbers.json", "w"), indent=2)
    return out


def concentration() -> dict:
    rows = list(csv.DictReader(open(PROCESSED_DIR / "final_classification.csv")))
    vols = sorted((float(r["total_amount_base_units"]) for r in rows),
                  reverse=True)
    total = sum(vols)
    cum, curve = 0.0, []
    checkpoints = {10: None, 100: None, 1000: None}
    for i, v in enumerate(vols, 1):
        cum += v
        if i in checkpoints:
            checkpoints[i] = round(cum / total, 4)
        if i <= 1000 or i % 1000 == 0:
            curve.append((i, round(cum / total, 6)))
    al = sorted((float(r["total_amount_base_units"]) for r in rows
                 if r["bucket_final"] == "ACTIVE_LEGITIMATE"), reverse=True)
    al_total = sum(al)
    al_top10 = round(sum(al[:10]) / al_total, 4)
    al_top100 = round(sum(al[:100]) / al_total, 4)
    out = {
        "generated": utcnow(),
        "note": "corrected all-time volume, all 163,417 sellers",
        "top10_share_all": checkpoints[10],
        "top100_share_all": checkpoints[100],
        "top1000_share_all": checkpoints[1000],
        "within_active_legitimate": {
            "sellers": len(al),
            "top10_share": al_top10,
            "top100_share": al_top100,
        },
        "curve_topN_cumshare": curve,
    }
    json.dump(out, open(OUT / "concentration.json", "w"), indent=2)
    return out


def cohort_survival() -> dict:
    """Control-sample cohorts: unbiased population estimate of survival."""
    alloc = {r["recipient"]: r["reasons"] for r in csv.DictReader(
        open(PROCESSED_DIR / "deep_allocation.csv"))}
    feats = {r["recipient"]: r for r in csv.DictReader(
        open(PROCESSED_DIR / "deep_features.csv")) if r["n_pulled"] not in ("", "0")}
    census_last = {}
    for r in csv.DictReader(open(PROCESSED_DIR / "census_sellers_corrected.csv")):
        k = r["recipient"].lower() if r["recipient"].startswith("0x") else r["recipient"]
        census_last[k] = r["latest_block_timestamp"]

    cohorts: dict[str, dict] = defaultdict(lambda: {"n": 0, "survived": 0})
    for rec, reasons in alloc.items():
        if "control" not in reasons:
            continue
        k = rec.lower() if rec.startswith("0x") else rec
        f = feats.get(k)
        if not f:
            continue
        first = datetime.fromisoformat(f["first_seen"])
        # census latest timestamp is authoritative for last activity
        last_s = census_last.get(k) or f["last_seen"]
        last = datetime.fromisoformat(last_s.replace("Z", "+00:00"))
        if NOW - first < timedelta(days=60):
            continue  # right-censored
        m = first.strftime("%Y-%m")
        cohorts[m]["n"] += 1
        if (last - first) >= timedelta(days=60):
            cohorts[m]["survived"] += 1

    out = {
        "generated": utcnow(),
        "method": ("1,500-seller seeded control sample; cohort = month of "
                   "first observed transfer; survived = any transfer >=60 "
                   "days after first; cohorts younger than 60 days excluded "
                   "(right-censored)."),
        "cohorts": {m: {**c, "survival_rate": round(c["survived"] / c["n"], 3)
                        if c["n"] else None}
                    for m, c in sorted(cohorts.items())},
    }
    json.dump(out, open(OUT / "cohort_survival.json", "w"), indent=2)
    return out


def liveness() -> dict:
    rows = list(csv.DictReader(open(PROCESSED_DIR / "liveness_results.csv")))
    def stats(rs):
        n = len(rs)
        got_any = sum(1 for r in rs if r["status"])
        s402 = sum(1 for r in rs if r["status"] == "402")
        valid = sum(1 for r in rs if r["status"] == "402"
                    and r["valid_402_body"] == "True")
        return {"probed": n, "responded": got_any,
                "http_402": s402, "valid_x402_402": valid,
                "http_402_rate": round(s402 / n, 4),
                "valid_402_rate": round(valid / n, 4)}
    bazaar = [r for r in rows if r["kind"] == "bazaar_resource"]
    out = {"generated": utcnow(), **stats(rows), "bazaar": stats(bazaar),
           "status_distribution": dict(Counter(
               r["status"] or "network_error" for r in rows).most_common())}
    json.dump(out, open(OUT / "liveness_summary.json", "w"), indent=2)
    return out


if __name__ == "__main__":
    h = headline()
    c = concentration()
    s = cohort_survival()
    print(json.dumps({"headline_pair": h["headline_pair"],
                      "liveness": h["liveness_headline"],
                      "bazaar_collapse": h["bazaar_collapse"],
                      "concentration": {k: c[k] for k in
                                        ("top10_share_all", "top100_share_all",
                                         "within_active_legitimate")},
                      "cohorts": s["cohorts"]}, indent=2))
