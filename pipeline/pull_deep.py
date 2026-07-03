"""Phase 2 deep pulls: per-seller transfer history from x402scan (resumable).

For each allocated seller:
  tx_count <= full_history_max_tx : ascending pages -> COMPLETE history
  tx_count  > full_history_max_tx : first page (asc) + latest page (desc)
                                    -> PARTIAL sample, flagged

Raw storage: data/raw/x402scan/deep-<label>/shard_XX.jsonl.gz — one line per
API request: {recipient, input, pulled_at, body}. Never rewritten; a progress
file (completed recipient set) makes the job resumable after interruption.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from lib import RAW_DIR, PROCESSED_DIR, X402ScanClient, append_jsonl_gz, load_config, utcnow

ALLOCATION = PROCESSED_DIR / "deep_allocation.csv"


def shard_path(base: Path, recipient: str) -> Path:
    key = recipient[2:4].lower() if recipient.startswith("0x") else recipient[:2]
    return base / f"shard_{key}.jsonl.gz"


def pull_seller(client: X402ScanClient, base: Path, recipient: str,
                tx_count: int, max_full: int) -> int:
    """Pull one seller's transfers; returns number of requests made."""
    requests_made = 0

    def fetch(sort_desc: bool, page: int) -> dict:
        nonlocal requests_made
        inp = {
            "timeframe": 0,
            "recipients": {"include": [recipient]},
            "sorting": {"id": "block_timestamp", "desc": sort_desc},
            "pagination": {"page": page, "page_size": 1000},
        }
        body = client.trpc("public.transfers.list", inp)
        append_jsonl_gz(shard_path(base, recipient), {
            "recipient": recipient, "input": inp,
            "pulled_at": utcnow(), "body": body,
        })
        requests_made += 1
        return body

    if tx_count <= max_full:
        page = 0
        while True:
            body = fetch(sort_desc=False, page=page)
            items = body.get("items", [])
            if not body.get("hasNextPage") or not items:
                break
            page += 1
            if page > max_full // 1000 + 2:   # safety: census count was stale
                break
    else:
        fetch(sort_desc=False, page=0)   # earliest 1000 (first-seen + early pattern)
        fetch(sort_desc=True, page=0)    # latest 1000 (current pattern)
    return requests_made


def main() -> None:
    cfg = load_config()
    label = cfg["snapshot"]["label"]
    max_full = cfg["deep_pull"]["full_history_max_tx"]
    base = RAW_DIR / "x402scan" / f"deep-{label}"
    base.mkdir(parents=True, exist_ok=True)
    progress_path = base / "progress.json"

    done: set[str] = set()
    if progress_path.exists():
        done = set(json.load(open(progress_path))["completed"])

    alloc = list(csv.DictReader(open(ALLOCATION)))
    todo = [r for r in alloc if r["recipient"] not in done]
    print(f"[deep] {len(alloc)} allocated, {len(done)} done, {len(todo)} to pull",
          flush=True)

    client = X402ScanClient(cfg)
    total_requests = 0
    for i, row in enumerate(todo):
        recipient = row["recipient"]
        try:
            total_requests += pull_seller(client, base, recipient,
                                          int(row["tx_count"]), max_full)
        except Exception as exc:  # log and continue; retried on next resume
            print(f"[deep] FAIL {recipient}: {exc}", flush=True)
            continue
        done.add(recipient)
        if (i + 1) % 25 == 0 or i == len(todo) - 1:
            with open(progress_path, "w") as f:
                json.dump({"completed": sorted(done),
                           "updated": utcnow()}, f)
            print(f"[deep] {i+1}/{len(todo)} sellers, "
                  f"{total_requests} requests", flush=True)
    with open(progress_path, "w") as f:
        json.dump({"completed": sorted(done), "updated": utcnow()}, f)
    print(f"[deep] DONE: {len(done)}/{len(alloc)} sellers, "
          f"{total_requests} requests this run", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
