"""Phase 2: derive per-seller behavioral features from raw deep-pull shards.

Reads data/raw/x402scan/deep-<label>/shard_*.jsonl.gz and emits
data/processed/deep_features.csv with, per seller:

  n_pulled, complete (full lifetime history captured?), first_seen, last_seen,
  unique_buyers_recomputed (DELTA 3; exact when complete),
  self_pay_tx_share / self_pay_vol_share (payer wallet == seller wallet),
  top1/top2 payer volume shares, modal amount share + value,
  active_span_days, max_tx_in_1d, n_unique_amounts.

Raw is never modified; this script is pure derivation and safe to re-run.
"""

from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime

from lib import PROCESSED_DIR, RAW_DIR, iter_jsonl_gz, load_config


def norm(addr: str) -> str:
    return addr.lower() if addr.startswith("0x") else addr


def main() -> None:
    cfg = load_config()
    label = cfg["snapshot"]["label"]
    base = RAW_DIR / "x402scan" / f"deep-{label}"

    # transfers per seller, deduped by (tx_hash, log_index) — asc + desc
    # samples of big sellers can overlap
    per_seller: dict[str, dict] = defaultdict(lambda: {
        "rows": {}, "complete_signal": False, "requests": 0})

    for shard in sorted(base.glob("shard_*.jsonl.gz")):
        for rec in iter_jsonl_gz(shard):
            seller = norm(rec["recipient"])
            st = per_seller[seller]
            st["requests"] += 1
            body = rec["body"]
            inp = rec["input"]
            asc = not inp["sorting"]["desc"]
            if asc and not body.get("hasNextPage"):
                st["complete_signal"] = True
            for t in body.get("items", []):
                key = (t["tx_hash"], t.get("log_index"))
                st["rows"][key] = t

    out = PROCESSED_DIR / "deep_features.csv"
    cols = ["recipient", "n_pulled", "complete", "first_seen", "last_seen",
            "unique_buyers_recomputed", "self_pay_tx_share",
            "self_pay_vol_share", "top1_payer_vol_share",
            "top2_payer_vol_share", "modal_amount_share",
            "modal_amount_base_units", "n_unique_amounts",
            "active_span_days", "max_tx_in_1d", "chains_seen"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for seller in sorted(per_seller):
            st = per_seller[seller]
            rows = list(st["rows"].values())
            if not rows:
                w.writerow([seller, 0, 0] + [""] * (len(cols) - 3))
                continue
            ts = sorted(datetime.fromisoformat(
                r["block_timestamp"].replace("Z", "+00:00")) for r in rows)
            first, last = ts[0], ts[-1]
            vol_by_payer: Counter = Counter()
            amounts: Counter = Counter()
            self_tx = 0
            self_vol = 0.0
            total_vol = 0.0
            days: Counter = Counter()
            chains = set()
            for r in rows:
                payer = norm(r["sender"])
                amt = float(r["amount"])
                vol_by_payer[payer] += amt
                amounts[amt] += 1
                total_vol += amt
                chains.add(r.get("chain", ""))
                days[r["block_timestamp"][:10]] += 1
                if payer == seller:
                    self_tx += 1
                    self_vol += amt
            n = len(rows)
            top = vol_by_payer.most_common(2)
            top1 = top[0][1] / total_vol if total_vol else 0.0
            top2 = sum(v for _, v in top) / total_vol if total_vol else 0.0
            modal_amt, modal_n = amounts.most_common(1)[0]
            w.writerow([
                seller, n, int(st["complete_signal"]),
                first.isoformat(), last.isoformat(),
                len(vol_by_payer),
                round(self_tx / n, 4),
                round(self_vol / total_vol, 4) if total_vol else 0.0,
                round(top1, 4), round(top2, 4),
                round(modal_n / n, 4), modal_amt, len(amounts),
                round((last - first).total_seconds() / 86400, 2),
                max(days.values()),
                "|".join(sorted(c for c in chains if c)),
            ])
    print(f"[features] wrote {out} ({len(per_seller)} sellers)")


if __name__ == "__main__":
    main()
    sys.exit(0)
