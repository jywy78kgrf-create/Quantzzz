"""Per-bucket hand-inspection sample: 5 seeded-random sellers per final bucket.

Emits the evidence table (analysis/hand_inspection_evidence.json) with each
seller's raw transfer-pattern summary: tx count, buyers, self-pay share,
top-2 concentration, modal amount/share, span, silence, example tx hashes.
Sellers without deep-pull coverage are pulled ad hoc here (logged like every
other request). Human verdicts live in analysis/hand_inspection.md.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from lib import (PROCESSED_DIR, RAW_DIR, X402ScanClient,  # noqa: E402
                 iter_jsonl_gz, load_config, seeded_rng, utcnow)


def transfers_from_shards(recipient: str, base: Path) -> list[dict]:
    key = recipient[2:4].lower() if recipient.startswith("0x") else recipient[:2]
    shard = base / f"shard_{key}.jsonl.gz"
    rows: dict = {}
    if shard.exists():
        for rec in iter_jsonl_gz(shard):
            if rec["recipient"].lower() == recipient.lower() or \
                    rec["recipient"] == recipient:
                for t in rec["body"].get("items", []):
                    rows[(t["tx_hash"], t.get("log_index"))] = t
    return list(rows.values())


def summarize(recipient: str, transfers: list[dict]) -> dict:
    if not transfers:
        return {"n": 0}
    def norm(a): return a.lower() if a.startswith("0x") else a
    seller = norm(recipient)
    ts = sorted(t["block_timestamp"] for t in transfers)
    vol_by_payer: Counter = Counter()
    amounts: Counter = Counter()
    self_vol = tot = 0.0
    for t in transfers:
        p, a = norm(t["sender"]), float(t["amount"])
        vol_by_payer[p] += a
        amounts[a] += 1
        tot += a
        if p == seller:
            self_vol += a
    top = vol_by_payer.most_common(2)
    modal_amt, modal_n = amounts.most_common(1)[0]
    now = datetime.now(timezone.utc)
    last = datetime.fromisoformat(ts[-1].replace("Z", "+00:00"))
    return {
        "n": len(transfers),
        "unique_payers": len(vol_by_payer),
        "self_pay_vol_share": round(self_vol / tot, 3) if tot else 0,
        "top2_vol_share": round(sum(v for _, v in top) / tot, 3) if tot else 0,
        "modal_amount_usdc": modal_amt / 1e6,
        "modal_share": round(modal_n / len(transfers), 3),
        "first_tx": ts[0][:10], "last_tx": ts[-1][:10],
        "days_silent": round((now - last).days, 1),
        "example_tx_hashes": [t["tx_hash"] for t in transfers[:3]],
    }


def main() -> None:
    cfg = load_config()
    base = RAW_DIR / "x402scan" / f"deep-{cfg['snapshot']['label']}"
    rows = list(csv.DictReader(open(PROCESSED_DIR / "final_classification.csv")))
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_bucket[r["bucket_final"]].append(r)

    client = X402ScanClient(cfg)
    rng = seeded_rng(cfg["deep_pull"]["random_seed"], "hand-inspection")
    evidence = {}
    for bucket in sorted(by_bucket):
        picks = rng.sample(sorted(by_bucket[bucket],
                                  key=lambda r: r["recipient"]),
                           min(5, len(by_bucket[bucket])))
        out = []
        for r in picks:
            rec = r["recipient"]
            transfers = transfers_from_shards(rec, base)
            if not transfers:
                body = client.trpc("public.transfers.list", {
                    "timeframe": 0,
                    "recipients": {"include": [rec]},
                    "sorting": {"id": "block_timestamp", "desc": False},
                    "pagination": {"page": 0, "page_size": 1000},
                })
                transfers = body.get("items", [])
            out.append({
                "recipient": rec,
                "bucket_final": r["bucket_final"],
                "bucket_census": r["bucket_census"],
                "census_tx_count": int(r["tx_count"]),
                "pattern": summarize(rec, transfers),
            })
        evidence[bucket] = out

    out_path = Path(__file__).resolve().parent / "hand_inspection_evidence.json"
    json.dump({"generated": utcnow(),
               "seed_namespace": "hand-inspection",
               "buckets": evidence}, open(out_path, "w"), indent=2)
    print(f"wrote {out_path}")
    for bucket, sellers in evidence.items():
        print(f"\n== {bucket} ==")
        for s in sellers:
            p = s["pattern"]
            print(f"  {s['recipient'][:16]} tx={s['census_tx_count']} "
                  f"{json.dumps({k: v for k, v in p.items() if k != 'example_tx_hashes'})}")


if __name__ == "__main__":
    main()
