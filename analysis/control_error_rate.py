"""Census-classifier error rate, measured on the seeded 1,500-seller control.

For every control-sample seller with extracted deep features, compare the
census-aggregate bucket to the final (deep-signal) bucket. Reports overall
agreement, per-census-bucket agreement, and the TEST_RIG breakout (TEST_RIG
carries most volume and most of its members were classified on aggregates).

Output: analysis/control_error_rate.json (committed).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from lib import PROCESSED_DIR, utcnow  # noqa: E402


def main() -> None:
    rows = [r for r in csv.DictReader(
        open(PROCESSED_DIR / "final_classification.csv"))
        if "control" in r["deep_reasons"] and r["census_only"] == "0"]

    n = len(rows)
    changed = [r for r in rows if r["bucket_final"] != r["bucket_census"]]
    per_bucket: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        per_bucket[r["bucket_census"]][r["bucket_final"]] += 1

    def bucket_stats(c: str) -> dict:
        total = sum(per_bucket[c].values())
        same = per_bucket[c][c]
        return {
            "n_control": total,
            "unchanged": same,
            "agreement": round(same / total, 4) if total else None,
            "moved_to": {b: k for b, k in per_bucket[c].most_common()
                         if b != c},
        }

    report = {
        "generated": utcnow(),
        "control_sellers_with_deep_features": n,
        "overall": {
            "changed_bucket": len(changed),
            "error_rate": round(len(changed) / n, 4),
            "agreement": round(1 - len(changed) / n, 4),
        },
        "per_census_bucket": {c: bucket_stats(c)
                              for c in sorted(per_bucket)},
        "test_rig_breakout": {
            **bucket_stats("TEST_RIG"),
            "note": ("Census TEST_RIG rule = >=5 tx AND <=2 unique buyers "
                     "(census field). Deep signals can only move a seller "
                     "OUT of TEST_RIG if recomputed buyers > 2 and no "
                     "concentration/self-dealing rule fires."),
        },
        "interpretation": (
            "Error direction is asymmetric: census under-detects TEST_RIG "
            "(aggregates cannot see self-dealing or payer concentration "
            "among >2 buyers), so census-only sellers in DORMANT/LOW_ACTIVITY "
            "may include undetected test rigs; the corrected shares in "
            "control_transition_matrix.json account for this."),
    }
    out = Path(__file__).resolve().parent / "control_error_rate.json"
    json.dump(report, open(out, "w"), indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
