"""Phase 1: x402scan origin->wallet mapping (public.sellers.bazaar.list).

Gives the endpoint-URL <-> receiving-wallet join used for DUPLICATE detection
and the liveness-probe universe.

Raw   -> data/raw/x402scan/origins-<label>/page_NNNN.json.gz
Processed -> data/processed/origin_wallet_map.csv (origin URL x recipient)
"""

from __future__ import annotations

import csv
import sys

from lib import PROCESSED_DIR, RAW_DIR, X402ScanClient, load_config, load_raw_gz, save_raw_gz, utcnow


def pull(cfg: dict) -> list[dict]:
    client = X402ScanClient(cfg)
    label = cfg["snapshot"]["label"]
    out_dir = RAW_DIR / "x402scan" / f"origins-{label}"
    rows: list[dict] = []
    page = 0
    while True:
        page_path = out_dir / f"page_{page:04d}.json.gz"
        if page_path.exists():
            data = load_raw_gz(page_path)
        else:
            data = client.trpc("public.sellers.bazaar.list", {
                "timeframe": 0,
                "pagination": {"page": page, "page_size": 1000},
            })
            save_raw_gz(page_path, data)
        items = data.get("items", [])
        rows.extend(items)
        print(f"[origins] page {page}: {len(items)} rows "
              f"(cum {len(rows)}/{data.get('total_count')})", flush=True)
        if not data.get("hasNextPage") or not items:
            break
        page += 1
    return rows


def to_processed(rows: list[dict]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "origin_wallet_map.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["origin", "recipient", "group_tx_count",
                    "group_total_amount", "group_unique_buyers",
                    "group_latest_ts"])
        for r in rows:
            for o in r.get("origins", []):
                for rec in r.get("recipients", []):
                    w.writerow([o.get("origin", ""), rec,
                                r.get("tx_count", ""),
                                r.get("total_amount", ""),
                                r.get("unique_buyers", ""),
                                r.get("latest_block_timestamp") or ""])
    print(f"[origins] wrote {out}", flush=True)


if __name__ == "__main__":
    cfg = load_config()
    print(f"[origins] start {utcnow()}", flush=True)
    rows = pull(cfg)
    to_processed(rows)
    sys.exit(0)
