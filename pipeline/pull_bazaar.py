"""Phase 1: full pull of the CDP x402 Bazaar discovery catalog.

Raw pages -> data/raw/bazaar/<label>/page_NNNN.json.gz (untouched payloads).
Processed  -> data/processed/bazaar_resources.csv (one row per listed resource,
one row per `accepts` entry when a resource lists several payment options).
"""

from __future__ import annotations

import csv
import sys

from lib import Client, PROCESSED_DIR, RAW_DIR, load_config, load_raw_gz, save_raw_gz, utcnow


def pull(cfg: dict) -> list[dict]:
    src = cfg["sources"]["bazaar"]
    client = Client("bazaar", src["min_interval_seconds"], cfg)
    label = cfg["snapshot"]["label"]
    out_dir = RAW_DIR / "bazaar" / label
    limit = src["page_limit"]

    items: list[dict] = []
    offset, page = 0, 0
    total = None
    while True:
        page_path = out_dir / f"page_{page:04d}.json.gz"
        if page_path.exists():
            body = load_raw_gz(page_path)
        else:
            resp = client.get(f"{src['base_url']}/resources",
                              params={"limit": limit, "offset": offset})
            body = resp.json()
            save_raw_gz(page_path, body)
        got = body.get("items", [])
        items.extend(got)
        total = body.get("pagination", {}).get("total")
        print(f"[bazaar] page {page}: {len(got)} items "
              f"(cum {len(items)}/{total})", flush=True)
        if not got or (total is not None and offset + len(got) >= total):
            break
        offset += len(got)
        page += 1
    return items


def to_processed(items: list[dict]) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / "bazaar_resources.csv"
    cols = ["resource_url", "resource_type", "x402_version", "last_updated",
            "accept_index", "network", "asset", "amount_base_units",
            "pay_to", "scheme", "max_timeout_seconds", "description_len"]
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for it in items:
            accepts = it.get("accepts") or [{}]
            for i, acc in enumerate(accepts):
                w.writerow([
                    it.get("resource") or it.get("resourceUrl") or "",
                    it.get("type", ""),
                    it.get("x402Version", ""),
                    it.get("lastUpdated", ""),
                    i,
                    acc.get("network", ""),
                    acc.get("asset", ""),
                    acc.get("amount") or acc.get("maxAmountRequired") or "",
                    acc.get("payTo", ""),
                    acc.get("scheme", ""),
                    acc.get("maxTimeoutSeconds", ""),
                    len(it.get("description") or ""),
                ])
    print(f"[bazaar] wrote {out}", flush=True)


if __name__ == "__main__":
    cfg = load_config()
    print(f"[bazaar] start {utcnow()}", flush=True)
    items = pull(cfg)
    print(f"[bazaar] total resources: {len(items)}", flush=True)
    to_processed(items)
    sys.exit(0)
