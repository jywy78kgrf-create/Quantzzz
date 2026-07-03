"""DELTA 2a: coverage measurement — Bazaar payTo wallets vs x402scan index.

For every payTo wallet in the Bazaar catalog, check whether it appears in the
x402scan seller census. Absence = the listed service has zero transfers in the
index (either truly never used, or settled outside indexed facilitators).

Also reports listing-level duplication inside the Bazaar catalog:
  - same resource URL listed with >1 distinct payTo
  - same payTo behind >1 distinct resource URL / origin

Outputs: data/processed/coverage_bazaar_vs_census.json
         data/processed/bazaar_paytos_unindexed.csv
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from urllib.parse import urlparse

from lib import PROCESSED_DIR, utcnow

BAZAAR = PROCESSED_DIR / "bazaar_resources.csv"
CENSUS = PROCESSED_DIR / "census_sellers_corrected.csv"


def norm_wallet(addr: str) -> str:
    # EVM addresses: case-insensitive hex -> lowercase. Solana: base58,
    # case-sensitive -> leave untouched.
    return addr.lower() if addr.startswith("0x") else addr


def main() -> None:
    census_wallets: set[str] = set()
    census_tx: dict[str, int] = {}
    with open(CENSUS) as f:
        for row in csv.DictReader(f):
            wallet = norm_wallet(row["recipient"])
            census_wallets.add(wallet)
            census_tx[wallet] = int(row["tx_count"])

    paytos: set[str] = set()
    payto_urls: dict[str, set[str]] = defaultdict(set)
    url_paytos: dict[str, set[str]] = defaultdict(set)
    payto_networks: dict[str, set[str]] = defaultdict(set)
    n_resources = set()
    with open(BAZAAR) as f:
        for row in csv.DictReader(f):
            pay_to = row["pay_to"]
            if not pay_to:
                continue
            wallet = norm_wallet(pay_to)
            url = row["resource_url"]
            n_resources.add(url)
            paytos.add(wallet)
            payto_urls[wallet].add(url)
            url_paytos[url].add(wallet)
            payto_networks[wallet].add(row["network"])

    indexed = {w for w in paytos if w in census_wallets}
    unindexed = paytos - indexed

    # listing-level duplication
    urls_multi_payto = {u: sorted(p) for u, p in url_paytos.items() if len(p) > 1}
    payto_multi_origin: dict[str, list[str]] = {}
    for w, urls in payto_urls.items():
        origins = {urlparse(u).netloc for u in urls}
        if len(origins) > 1:
            payto_multi_origin[w] = sorted(origins)

    report = {
        "generated": utcnow(),
        "bazaar_resources": len(n_resources),
        "bazaar_unique_paytos": len(paytos),
        "paytos_in_census_index": len(indexed),
        "paytos_absent_from_index": len(unindexed),
        "index_miss_rate_listed_services": round(len(unindexed) / len(paytos), 4),
        "indexed_but_ghost_lt5tx": sum(
            1 for w in indexed if census_tx.get(w, 0) < 5),
        "listing_duplication": {
            "resource_urls_with_multiple_paytos": len(urls_multi_payto),
            "paytos_spanning_multiple_origins": len(payto_multi_origin),
        },
        "method": ("Join key: payTo wallet (EVM lowercased; Solana verbatim) "
                   "against census recipient set (163,417 wallets, all-time)."),
    }
    with open(PROCESSED_DIR / "coverage_bazaar_vs_census.json", "w") as f:
        json.dump(report, f, indent=2)

    with open(PROCESSED_DIR / "bazaar_paytos_unindexed.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pay_to", "networks", "n_listed_urls", "example_url"])
        for wallet in sorted(unindexed):
            urls = sorted(payto_urls[wallet])
            w.writerow([wallet, "|".join(sorted(payto_networks[wallet])),
                        len(urls), urls[0]])

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
