"""DELTA 1: allocate transfer-level deep pulls after census classification.

  a) top N sellers by lifetime volume — exhaustive
  b) ALL census ACTIVE_LEGITIMATE candidates (seeded sample only if > cap)
  c) pure-random control sample across all buckets (seeded)

Output: data/processed/deep_allocation.csv  (recipient, reasons, census bucket)
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict

from lib import PROCESSED_DIR, load_config, seeded_rng, utcnow

CLASSIFIED = PROCESSED_DIR / "census_classified.csv"


def main() -> None:
    cfg = load_config()
    dp = cfg["deep_pull"]

    rows = list(csv.DictReader(open(CLASSIFIED)))
    by_wallet = {r["recipient"]: r for r in rows}

    top = sorted(rows, key=lambda r: -float(r["total_amount_base_units"]))
    top_set = [r["recipient"] for r in top[: dp["top_n_by_volume"]]]

    al = [r["recipient"] for r in rows if r["bucket_census"] == "ACTIVE_LEGITIMATE"]
    al_sampled = False
    if len(al) > dp["active_legit_cap"]:
        rng = seeded_rng(dp["random_seed"], "active-legit-sample")
        al = sorted(rng.sample(sorted(al), dp["active_legit_cap"]))
        al_sampled = True

    rng = seeded_rng(dp["random_seed"], "control-sample")
    control = rng.sample(sorted(by_wallet), dp["control_sample_size"])

    reasons: dict[str, list[str]] = defaultdict(list)
    for w in top_set:
        reasons[w].append("top_volume")
    for w in al:
        reasons[w].append("active_legit_candidate")
    for w in control:
        reasons[w].append("control")

    out = PROCESSED_DIR / "deep_allocation.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipient", "reasons", "bucket_census", "tx_count"])
        for wallet in sorted(reasons):
            w.writerow([wallet, "|".join(reasons[wallet]),
                        by_wallet[wallet]["bucket_census"],
                        by_wallet[wallet]["tx_count"]])

    est_requests = 0
    for wallet in reasons:
        tx = int(by_wallet[wallet]["tx_count"])
        if tx <= dp["full_history_max_tx"]:
            est_requests += max(1, -(-min(tx, dp["full_history_max_tx"]) // 1000))
        else:
            est_requests += 2

    meta = {
        "generated": utcnow(),
        "seed": dp["random_seed"],
        "top_volume": len(top_set),
        "active_legit_candidates": len(al),
        "active_legit_sampled": al_sampled,
        "control": len(control),
        "unique_sellers": len(reasons),
        "estimated_requests": est_requests,
    }
    with open(PROCESSED_DIR / "deep_allocation_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
