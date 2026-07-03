"""Phase 2, pass 1: census-level classification of ALL sellers.

Assigns every census seller a provisional bucket using only census aggregates
(tx_count, unique_buyers, latest activity) plus the origin->wallet map for
DUPLICATE detection. Transfer-level signatures (TEST_RIG deep signals,
MEMECOIN) are applied in pass 2 (classify_final.py) for deep-pulled sellers.

Buckets (priority order, exactly one per seller):
  GHOST > TEST_RIG > DUPLICATE > DORMANT > ACTIVE_LEGITIMATE

Outputs:
  data/processed/census_classified.csv   (per-seller bucket + signals)
  data/processed/census_bucket_summary.json
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

from lib import PROCESSED_DIR, load_config

CENSUS = PROCESSED_DIR / "census_sellers.csv"
ORIGIN_MAP = PROCESSED_DIR / "origin_wallet_map.csv"


def parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build_duplicate_set(cfg: dict) -> set[str]:
    """Wallets that share an endpoint URL with a higher-volume wallet."""
    by_origin: dict[str, set[str]] = defaultdict(set)
    with open(ORIGIN_MAP) as f:
        for row in csv.DictReader(f):
            if row["origin"] and row["recipient"]:
                by_origin[row["origin"]].add(row["recipient"])

    volume: dict[str, float] = {}
    with open(CENSUS) as f:
        for row in csv.DictReader(f):
            volume[row["recipient"]] = float(row["total_amount_base_units"])

    dupes: set[str] = set()
    for origin, wallets in by_origin.items():
        if len(wallets) < 2:
            continue
        keep = max(wallets, key=lambda w: (volume.get(w, 0.0), w))
        dupes.update(w for w in wallets if w != keep)
    return dupes


def classify(cfg: dict) -> None:
    cl = cfg["classification"]
    now = datetime.now(timezone.utc)
    windows = cl["dormant"]["windows_days"]
    primary = cl["dormant"]["primary_window_days"]
    dupes = build_duplicate_set(cfg)

    out_path = PROCESSED_DIR / "census_classified.csv"
    summary: dict[str, int] = defaultdict(int)
    vol_by_bucket: dict[str, float] = defaultdict(float)
    tx_by_bucket: dict[str, int] = defaultdict(int)
    n = 0

    with open(CENSUS) as f_in, open(out_path, "w", newline="") as f_out:
        reader = csv.DictReader(f_in)
        w = csv.writer(f_out)
        w.writerow(["recipient", "bucket_census", "tx_count",
                    "unique_buyers_census", "total_amount_base_units",
                    "latest_block_timestamp", "days_since_last",
                    "dormant_30", "dormant_60", "dormant_90",
                    "is_url_duplicate", "chains"])
        for row in reader:
            n += 1
            tx = int(row["tx_count"])
            buyers = int(row["unique_buyers_census"])
            amount = float(row["total_amount_base_units"])
            last = parse_ts(row["latest_block_timestamp"])
            days_since = (now - last).total_seconds() / 86400 if last else None
            dorm = {wd: (days_since is None or days_since > wd)
                    for wd in windows}
            is_dupe = row["recipient"] in dupes

            if tx <= cl["ghost"]["max_lifetime_tx"]:
                bucket = "GHOST"
            elif buyers <= cl["test_rig"]["census"]["max_unique_buyers"]:
                bucket = "TEST_RIG"
            elif is_dupe:
                bucket = "DUPLICATE"
            elif dorm[primary]:
                bucket = "DORMANT"
            elif (tx >= cl["active_legitimate"]["min_lifetime_tx"]
                  and buyers >= cl["active_legitimate"]["min_unique_buyers"]
                  and days_since is not None
                  and days_since <= cl["active_legitimate"]["max_days_since_last_tx"]):
                bucket = "ACTIVE_LEGITIMATE"
            else:
                # Recent-ish + multi-buyer but thin history: not dormant by the
                # primary window, yet below the sustained-activity bar.
                bucket = "LOW_ACTIVITY"

            summary[bucket] += 1
            vol_by_bucket[bucket] += amount
            tx_by_bucket[bucket] += tx
            w.writerow([row["recipient"], bucket, tx, buyers, amount,
                        row["latest_block_timestamp"],
                        f"{days_since:.1f}" if days_since is not None else "",
                        int(dorm[30]), int(dorm[60]), int(dorm[90]),
                        int(is_dupe), row["chains"]])

    total_vol = sum(vol_by_bucket.values()) or 1.0
    report = {
        "generated": now.isoformat(),
        "total_sellers": n,
        "buckets": {
            b: {
                "sellers": summary[b],
                "share_sellers": round(summary[b] / n, 4),
                "tx": tx_by_bucket[b],
                "volume_base_units": vol_by_bucket[b],
                "share_volume": round(vol_by_bucket[b] / total_vol, 4),
            }
            for b in sorted(summary, key=lambda b: -summary[b])
        },
        "notes": [
            "Census pass only: TEST_RIG here means <=2 unique payers with >=5 tx;",
            "deep transfer signals refine TEST_RIG/MEMECOIN in classify_final.py.",
            "LOW_ACTIVITY = recent multi-buyer sellers below the sustained bar;",
            "they are not ACTIVE_LEGITIMATE candidates but are covered by the",
            "control sample for error estimation.",
        ],
    }
    with open(PROCESSED_DIR / "census_bucket_summary.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report["buckets"], indent=2))
    print(f"[classify] wrote {out_path}")


if __name__ == "__main__":
    classify(load_config())
    sys.exit(0)
