"""Phase 2.5 SAMPLING DESIGN ONLY — no wallet, no payment, no execution.

Builds the stratified 75-endpoint sample for paid delivery verification:

  Universe : Bazaar-listed resources whose liveness probe returned a VALID
             x402 402 (parseable accepts with scheme/network/payTo).
  Filter   : price <= $1.00 USDC; one endpoint per payTo wallet and per
             origin (never pay the same operator twice).
  Strata   : top_volume   — payTo in the corrected top-1000 sellers
             mid_activity — indexed payTo with corrected tx_count >= 20
             low_new      — everything else (thin or unindexed payTo)
  Sampling : 25 per stratum, seeded (seed 402402, namespace "paid-probe").

Outputs: data/processed/paid_probe_sample.csv
         data/processed/paid_probe_projection.json

Execution is gated on config paid_probe.enabled (false) AND an explicit user
go after wallet funding; this script never touches keys or networks.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from urllib.parse import urlparse

from lib import PROCESSED_DIR, load_config, seeded_rng, utcnow

USDC_DECIMALS = 1_000_000


def main() -> None:
    cfg = load_config()
    pp = cfg["paid_probe"]

    # valid-402 URLs from the liveness sweep
    valid_urls = {r["url"] for r in csv.DictReader(
        open(PROCESSED_DIR / "liveness_results.csv"))
        if r["kind"] == "bazaar_resource" and r["status"] == "402"
        and r["valid_402_body"] == "True"}

    # census rank/activity per wallet (corrected values)
    census = {}
    for r in csv.DictReader(open(PROCESSED_DIR / "census_sellers_corrected.csv")):
        k = r["recipient"].lower() if r["recipient"].startswith("0x") else r["recipient"]
        census[k] = r
    top1000 = {(r["recipient"].lower() if r["recipient"].startswith("0x")
                else r["recipient"])
               for r in sorted(census.values(),
                               key=lambda x: -float(x["total_amount_base_units"]))[:1000]}

    # candidate endpoints from the Bazaar catalog (first accepts entry)
    candidates = []
    seen_url = set()
    for r in csv.DictReader(open(PROCESSED_DIR / "bazaar_resources.csv")):
        url = r["resource_url"]
        if url not in valid_urls or url in seen_url or r["accept_index"] != "0":
            continue
        seen_url.add(url)
        try:
            price = float(r["amount_base_units"]) / USDC_DECIMALS
        except (ValueError, TypeError):
            continue
        if price <= 0 or price > pp["max_price_usdc"]:
            continue
        # wallet is Base-mainnet USDC: testnet and Solana listings are
        # unpayable from it and excluded from the universe
        if r["network"] not in ("base", "eip155:8453"):
            continue
        payto = r["pay_to"].lower() if r["pay_to"].startswith("0x") else r["pay_to"]
        c = census.get(payto)
        if payto in top1000:
            stratum = "top_volume"
        elif c and int(c["tx_count"]) >= 20:
            stratum = "mid_activity"
        else:
            stratum = "low_new"
        candidates.append({
            "url": url, "origin": urlparse(url).netloc, "pay_to": r["pay_to"],
            "network": r["network"], "price_usdc": price, "stratum": stratum,
            "seller_tx_count": int(c["tx_count"]) if c else 0,
        })

    # one endpoint per payTo and per origin: keep the cheapest, tie-break by URL
    by_key: dict[tuple, dict] = {}
    for c in sorted(candidates, key=lambda c: (c["price_usdc"], c["url"])):
        for key in (("payto", c["pay_to"]), ("origin", c["origin"])):
            if key in by_key:
                break
        else:
            by_key[("payto", c["pay_to"])] = c
            by_key[("origin", c["origin"])] = c
    deduped = list({id(v): v for v in by_key.values()}.values())

    pools = defaultdict(list)
    for c in deduped:
        pools[c["stratum"]].append(c)
    rng = seeded_rng(cfg["deep_pull"]["random_seed"], "paid-probe")
    sample = []
    for stratum, want in pp["strata"].items():
        pool = sorted(pools[stratum], key=lambda c: c["url"])
        take = min(want, len(pool))
        sample.extend(rng.sample(pool, take))

    out_csv = PROCESSED_DIR / "paid_probe_sample.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["stratum", "url", "origin", "pay_to",
                                          "network", "price_usdc",
                                          "seller_tx_count"])
        w.writeheader()
        w.writerows(sorted(sample, key=lambda c: (c["stratum"], c["url"])))

    spend = sum(c["price_usdc"] for c in sample)
    projection = {
        "generated": utcnow(),
        "seed": cfg["deep_pull"]["random_seed"],
        "universe_valid_402_bazaar_urls": len(valid_urls),
        "candidates_after_price_filter": len(candidates),
        "after_operator_dedup": len(deduped),
        "pool_sizes": {s: len(p) for s, p in sorted(pools.items())},
        "sample_sizes": {s: sum(1 for c in sample if c["stratum"] == s)
                         for s in pp["strata"]},
        "projected_spend_usdc": round(spend, 2),
        "budget_cap_usdc": pp["budget_cap_usdc"],
        "halt_at_usdc": pp["halt_at_usdc"],
        "price_distribution": {
            "min": min(c["price_usdc"] for c in sample),
            "median": sorted(c["price_usdc"] for c in sample)[len(sample) // 2],
            "max": max(c["price_usdc"] for c in sample),
        },
        "networks": {n: sum(1 for c in sample if c["network"] == n)
                     for n in {c["network"] for c in sample}},
        "status": "DESIGN ONLY — no payment executes without explicit user go",
    }
    json.dump(projection, open(PROCESSED_DIR / "paid_probe_projection.json", "w"),
              indent=2)
    print(json.dumps(projection, indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
