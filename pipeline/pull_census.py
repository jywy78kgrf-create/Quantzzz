"""Phase 1: full seller census from x402scan (public.sellers.all.list).

Uses 'editorial' ordering (recipient ascending) — a stable pagination key that
does not drift as new transactions land mid-pull, unlike activity-based sorts.

Raw pages -> data/raw/x402scan/census-<label>/page_NNNN.json.gz
Processed  -> data/processed/census_sellers.csv
"""

from __future__ import annotations

import csv
import sys

from lib import PROCESSED_DIR, RAW_DIR, X402ScanClient, load_config, load_raw_gz, save_raw_gz, utcnow


def pull(cfg: dict) -> list[dict]:
    src = cfg["sources"]["x402scan"]
    client = X402ScanClient(cfg)
    label = cfg["snapshot"]["label"]
    out_dir = RAW_DIR / "x402scan" / f"census-{label}"
    page_size = src["page_size"]

    sellers: list[dict] = []
    page = 0
    while True:
        page_path = out_dir / f"page_{page:04d}.json.gz"
        if page_path.exists():
            data = load_raw_gz(page_path)
        else:
            data = client.trpc("public.sellers.all.list", {
                "timeframe": 0,
                "sorting": src["census_sort"],
                "pagination": {"page": page, "page_size": page_size},
            })
            save_raw_gz(page_path, data)
        items = data.get("items", [])
        sellers.extend(items)
        print(f"[census] page {page}: {len(items)} rows "
              f"(cum {len(sellers)}/{data.get('total_count')})", flush=True)
        if not data.get("hasNextPage") or not items:
            break
        page += 1
    return sellers


def to_processed(sellers: list[dict]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "census_sellers.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["recipient", "chains", "facilitators", "tx_count",
                    "total_amount_base_units", "unique_buyers_census",
                    "latest_block_timestamp"])
        for s in sellers:
            w.writerow([
                s["recipient"],
                "|".join(s.get("chains", [])),
                "|".join(s.get("facilitator_ids", [])),
                s["tx_count"],
                s["total_amount"],
                s["unique_buyers"],
                s.get("latest_block_timestamp") or "",
            ])
    print(f"[census] wrote {out} ({len(sellers)} sellers)", flush=True)


if __name__ == "__main__":
    cfg = load_config()
    print(f"[census] start {utcnow()}", flush=True)
    sellers = pull(cfg)
    # dedupe safety: editorial order should be unique per recipient
    seen = set()
    dupes = 0
    for s in sellers:
        if s["recipient"] in seen:
            dupes += 1
        seen.add(s["recipient"])
    print(f"[census] {len(sellers)} rows, {len(seen)} unique recipients, "
          f"{dupes} pagination dupes", flush=True)
    to_processed(sellers)
    sys.exit(0)
