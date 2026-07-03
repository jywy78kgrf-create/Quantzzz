"""Phase 2, pass 2: final classification merging census + deep features.

For deep-pulled sellers, transfer-level signals refine the census bucket:
TEST_RIG (self-dealing / payer concentration / uniformity+low-diversity) and
MEMECOIN (burst-then-silence pay-to-mint signature) become detectable, and
buyer diversity uses RECOMPUTED counts (DELTA 3) rather than the census field.

Non-deep-pulled sellers keep their census bucket (flagged census_only=1); the
control sample's census->final transition matrix estimates the census
classifier's error and produces corrected population shares.

Outputs:
  data/processed/final_classification.csv
  data/processed/final_bucket_summary.json
  data/processed/delta3_buyer_inflation.json
  data/processed/control_transition_matrix.json
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

from lib import PROCESSED_DIR, load_config, utcnow

CLASSIFIED = PROCESSED_DIR / "census_classified.csv"
FEATURES = PROCESSED_DIR / "deep_features.csv"
ALLOCATION = PROCESSED_DIR / "deep_allocation.csv"


def deep_bucket(cen: dict, feat: dict, cfg: dict, now: datetime) -> str:
    cl = cfg["classification"]
    tx = int(cen["tx_count"])
    complete = feat["complete"] == "1"
    buyers = int(feat["unique_buyers_recomputed"])
    self_vol = float(feat["self_pay_vol_share"])
    top2 = float(feat["top2_payer_vol_share"])
    modal_share = float(feat["modal_amount_share"])
    modal_amt = float(feat["modal_amount_base_units"])
    span = float(feat["active_span_days"])
    # last activity: census latest timestamp is authoritative (deep sample of
    # a big seller can be stale on the asc side, never on the census side)
    last = datetime.fromisoformat(
        cen["latest_block_timestamp"].replace("Z", "+00:00"))
    days_since = (now - last).total_seconds() / 86400

    if tx <= cl["ghost"]["max_lifetime_tx"]:
        return "GHOST"

    d = cl["test_rig"]["deep"]
    if self_vol >= d["self_pay_share_min"]:
        return "TEST_RIG"
    if buyers <= cl["test_rig"]["census"]["max_unique_buyers"] and complete:
        return "TEST_RIG"
    if buyers > 2 and top2 >= d["top2_payer_volume_share_min"]:
        return "TEST_RIG"
    if (modal_share >= d["uniform_amount_share_min"]
            and buyers <= d["uniform_max_unique_buyers"]):
        return "TEST_RIG"

    if cen["is_url_duplicate"] == "1":
        return "DUPLICATE"

    m = cl["memecoin"]
    if (tx >= m["min_lifetime_tx"]
            and span <= m["max_active_span_days"]
            and days_since >= m["min_silence_days"]
            and modal_share >= m["modal_amount_share_min"]
            and modal_amt <= m["max_amount_usdc"] * 1_000_000):
        return "MEMECOIN"

    if days_since > cl["dormant"]["primary_window_days"]:
        return "DORMANT"

    a = cl["active_legitimate"]
    if (tx >= a["min_lifetime_tx"] and buyers >= a["min_unique_buyers"]
            and days_since <= a["max_days_since_last_tx"]):
        return "ACTIVE_LEGITIMATE"
    return "LOW_ACTIVITY"


def main() -> None:
    cfg = load_config()
    now = datetime.now(timezone.utc)

    feats = {r["recipient"]: r for r in csv.DictReader(open(FEATURES))
             if r["n_pulled"] not in ("", "0")}
    alloc_reasons = {r["recipient"]: r["reasons"]
                     for r in csv.DictReader(open(ALLOCATION))}

    out_path = PROCESSED_DIR / "final_classification.csv"
    summary_sellers: Counter = Counter()
    summary_vol: dict[str, float] = defaultdict(float)
    summary_tx: dict[str, int] = defaultdict(int)
    control_trans: Counter = Counter()          # (census, final) pairs
    inflation_samples: list[float] = []
    census_buyers_used: list[tuple[int, int]] = []
    n = 0

    with open(CLASSIFIED) as f_in, open(out_path, "w", newline="") as f_out:
        w = csv.writer(f_out)
        w.writerow(["recipient", "bucket_final", "bucket_census",
                    "census_only", "deep_reasons", "tx_count",
                    "unique_buyers_final", "total_amount_base_units",
                    "days_since_last"])
        for cen in csv.DictReader(f_in):
            n += 1
            rec = cen["recipient"]
            feat = feats.get(rec.lower() if rec.startswith("0x") else rec)
            if feat:
                bucket = deep_bucket(cen, feat, cfg, now)
                census_only = 0
                buyers_final = int(feat["unique_buyers_recomputed"])
                if feat["complete"] == "1":
                    rb = buyers_final
                    cb = int(cen["unique_buyers_census"])
                    census_buyers_used.append((cb, rb))
                    if rb > 0:
                        inflation_samples.append(cb / rb)
                reasons = alloc_reasons.get(rec, "")
                if "control" in reasons:
                    control_trans[(cen["bucket_census"], bucket)] += 1
            else:
                bucket = cen["bucket_census"]
                census_only = 1
                buyers_final = int(cen["unique_buyers_census"])
                reasons = ""
            summary_sellers[bucket] += 1
            summary_vol[bucket] += float(cen["total_amount_base_units"])
            summary_tx[bucket] += int(cen["tx_count"])
            w.writerow([rec, bucket, cen["bucket_census"], census_only,
                        reasons, cen["tx_count"], buyers_final,
                        cen["total_amount_base_units"],
                        cen["days_since_last"]])

    total_vol = sum(summary_vol.values()) or 1.0
    report = {
        "generated": utcnow(),
        "total_sellers": n,
        "deep_pulled": len(feats),
        "buckets": {
            b: {"sellers": summary_sellers[b],
                "share_sellers": round(summary_sellers[b] / n, 4),
                "tx": summary_tx[b],
                "volume_base_units": summary_vol[b],
                "share_volume": round(summary_vol[b] / total_vol, 4)}
            for b in sorted(summary_sellers, key=lambda b: -summary_sellers[b])
        },
    }
    json.dump(report, open(PROCESSED_DIR / "final_bucket_summary.json", "w"),
              indent=2)

    # DELTA 3 — census buyer-count inflation among complete-history sellers
    inflation_samples.sort()
    def pct(p: float) -> float:
        i = min(len(inflation_samples) - 1,
                int(p * len(inflation_samples)))
        return inflation_samples[i]
    delta3 = {
        "generated": utcnow(),
        "complete_history_sellers": len(inflation_samples),
        "inflation_ratio_census_over_recomputed": {
            "median": round(pct(0.5), 4),
            "p25": round(pct(0.25), 4), "p75": round(pct(0.75), 4),
            "p95": round(pct(0.95), 4),
            "share_exact_match": round(
                sum(1 for x in inflation_samples if abs(x - 1) < 1e-9)
                / len(inflation_samples), 4) if inflation_samples else None,
        },
        "method": ("census unique_buyers / recomputed unique payers, sellers "
                   "with complete transfer history only; recomputed counts "
                   "dedupe payer wallets across chains."),
    }
    json.dump(delta3, open(PROCESSED_DIR / "delta3_buyer_inflation.json", "w"),
              indent=2)

    # control-sample transition matrix + corrected shares
    census_counts = Counter(r["bucket_census"]
                            for r in csv.DictReader(open(CLASSIFIED)))
    trans: dict[str, dict[str, float]] = defaultdict(dict)
    by_census: Counter = Counter()
    for (c, fi), k in control_trans.items():
        by_census[c] += k
    for (c, fi), k in sorted(control_trans.items()):
        trans[c][fi] = round(k / by_census[c], 4)
    corrected: dict[str, float] = defaultdict(float)
    for c, cnt in census_counts.items():
        probs = trans.get(c) or {c: 1.0}
        for fi, p in probs.items():
            corrected[fi] += cnt * p
    control_report = {
        "generated": utcnow(),
        "control_sellers_classified": sum(control_trans.values()),
        "transition_matrix_census_to_final": {c: trans[c] for c in sorted(trans)},
        "control_corrected_population_shares": {
            b: round(v / n, 4) for b, v in sorted(corrected.items(),
                                                  key=lambda kv: -kv[1])},
        "caveat": ("Correction applies control-sample transition rates to "
                   "census counts; small cells have wide error bars — see "
                   "per-cell counts."),
        "cell_counts": {f"{c}->{fi}": k
                        for (c, fi), k in sorted(control_trans.items())},
    }
    json.dump(control_report,
              open(PROCESSED_DIR / "control_transition_matrix.json", "w"),
              indent=2)

    print(json.dumps(report["buckets"], indent=2))
    print(json.dumps(delta3, indent=2))
    print(f"[final] wrote {out_path}")


if __name__ == "__main__":
    main()
    sys.exit(0)
