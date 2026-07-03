"""Step 1: decode the committed paid-probe bodies IN ISOLATION for scoring.

Reads data/raw/paid_probes/<label>/results.jsonl (inert base64 bodies),
decodes only here — never at capture — and emits a per-settlement evidence
table (status, content-type, body text prefix, advertised description from
the Bazaar catalog) to analysis/out/paid_probe_evidence.json.

Human verdicts + rationales live in analysis/paid_probe_scoring.md.
"""

from __future__ import annotations

import base64
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from lib import PROCESSED_DIR, RAW_DIR, utcnow  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
LEDGER = RAW_DIR / "paid_probes" / "2026-07-03" / "results.jsonl"


def bazaar_descriptions() -> dict[str, str]:
    desc = {}
    for page in sorted((RAW_DIR / "bazaar" / "2026-07-03").glob("page_*.json.gz")):
        for it in json.load(gzip.open(page, "rt")).get("items", []):
            desc[it["resource"]] = (it.get("description") or "")[:300]
    return desc


def main() -> None:
    desc = bazaar_descriptions()
    strata = {r["url"]: r["stratum"] for r in csv.DictReader(
        open(PROCESSED_DIR / "paid_probe_sample.csv"))}
    evidence = []
    for line in open(LEDGER):
        r = json.loads(line)
        if not r.get("payment_response"):
            continue
        body = base64.b64decode(r.get("body_b64") or "")
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = "<binary>"
        evidence.append({
            "url": r["url"],
            "stratum": strata.get(r["url"], "?"),
            "status": r["status"],
            "content_type": r["content_type"],
            "settled_usdc_onchain": r.get("settled_usdc_onchain"),
            "listed_price_usdc": r["listed_price_usdc"],
            "overcharged": r.get("overcharged", False),
            "tx_hash": r.get("tx_hash"),
            "body_bytes_total": r["body_bytes_total"],
            "body_text_prefix": text[:900],
            "advertised": desc.get(r["url"], ""),
        })
    OUT.mkdir(exist_ok=True)
    json.dump({"generated": utcnow(), "settled_payments": len(evidence),
               "records": evidence},
              open(OUT / "paid_probe_evidence.json", "w"), indent=2)
    for e in evidence:
        print(f"\n=== [{e['stratum']}] {e['url']}")
        print(f"    status={e['status']} ct={e['content_type']} "
              f"settled=${e['settled_usdc_onchain']} bytes={e['body_bytes_total']}")
        print(f"    advertised: {e['advertised'][:140]}")
        print(f"    body: {e['body_text_prefix'][:350]}")


if __name__ == "__main__":
    main()
