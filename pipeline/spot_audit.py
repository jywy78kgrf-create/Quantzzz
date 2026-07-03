"""DELTA 2b: on-chain spot-audit of the x402scan index.

For a seeded-random set of Base-chain sellers (census tx_count <= cap so the
keyless Blockscout API can enumerate their full USDC inflow), compare:

  B = x402scan's claimed transfer set for the seller (tx_hash-keyed)
  A = on-chain USDC incoming transfers per base.blockscout.com

Metrics per seller: match rate |A∩B|/|B| (phantom check: claimed-but-absent),
and unindexed on-chain inflows |A\\B| — a sample of those txs is resolved via
public Base RPC to test whether their initiator is a known facilitator
(missed x402 settlement) or not (ordinary USDC transfer, expected).

Solana sellers: existence check of up to 20 x402scan-claimed signatures per
seller via public RPC getTransaction (full inflow enumeration is not feasible
keylessly; documented in the report).

Sellers whose census tx_count exceeds the cap are substituted (seeded walk
continues) and every substitution is recorded.

Outputs: data/raw/onchain/<label>/*.jsonl.gz, data/processed/spot_audit.json
"""

from __future__ import annotations

import csv
import json
import sys
import time

from lib import (PROCESSED_DIR, RAW_DIR, Client, X402ScanClient,
                 append_jsonl_gz, load_config, seeded_rng, utcnow)

CENSUS = PROCESSED_DIR / "census_sellers.csv"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def pick_sellers(cfg: dict) -> tuple[list[dict], list[dict], list[dict]]:
    sa = cfg["spot_audit"]
    rows = list(csv.DictReader(open(CENSUS)))
    rng = seeded_rng(sa["random_seed"], "spot-audit")
    order = list(range(len(rows)))
    rng.shuffle(order)

    base_picks, sol_picks, substitutions = [], [], []
    want_base = sa["n_sellers"]
    want_sol = 10
    for i in order:
        r = rows[i]
        if len(base_picks) >= want_base and len(sol_picks) >= want_sol:
            break
        chains = r["chains"].split("|")
        tx = int(r["tx_count"])
        if tx < 1:
            continue
        if chains == ["base"] and len(base_picks) < want_base:
            if tx > sa["max_tx_for_audit"]:
                substitutions.append({"recipient": r["recipient"],
                                      "reason": f"tx_count {tx} > cap"})
                continue
            base_picks.append(r)
        elif chains == ["solana"] and len(sol_picks) < want_sol:
            sol_picks.append(r)
    return base_picks, sol_picks, substitutions


def x402scan_transfers(client: X402ScanClient, recipient: str) -> list[dict]:
    out, page = [], 0
    while True:
        body = client.trpc("public.transfers.list", {
            "timeframe": 0,
            "recipients": {"include": [recipient]},
            "sorting": {"id": "block_timestamp", "desc": False},
            "pagination": {"page": page, "page_size": 1000},
        })
        out.extend(body.get("items", []))
        if not body.get("hasNextPage") or not body.get("items"):
            return out
        page += 1


def blockscout_usdc_in(client: Client, raw_dir, addr: str,
                       max_pages: int = 25) -> list[dict]:
    items: list[dict] = []
    params = {"token": USDC_BASE, "filter": "to", "type": "ERC-20"}
    url = f"https://base.blockscout.com/api/v2/addresses/{addr}/token-transfers"
    for _ in range(max_pages):
        resp = client.get(url, params=params, ok_statuses=(200, 404))
        if resp.status_code == 404:
            break
        body = resp.json()
        append_jsonl_gz(raw_dir / "blockscout_pages.jsonl.gz",
                        {"addr": addr, "params": params,
                         "pulled_at": utcnow(), "body": body})
        items.extend(body.get("items", []))
        nxt = body.get("next_page_params")
        if not nxt:
            break
        params = {"token": USDC_BASE, "filter": "to", "type": "ERC-20", **nxt}
    return items


def rpc_tx_from(client: Client, tx_hash: str) -> str | None:
    resp = client.session.post(
        "https://mainnet.base.org", timeout=30,
        json={"jsonrpc": "2.0", "id": 1,
              "method": "eth_getTransactionByHash", "params": [tx_hash]})
    try:
        return (resp.json().get("result") or {}).get("from", "").lower() or None
    except Exception:
        return None


def main() -> None:
    cfg = load_config()
    label = cfg["snapshot"]["label"]
    raw_dir = RAW_DIR / "onchain" / label
    raw_dir.mkdir(parents=True, exist_ok=True)

    facil = json.load(open(PROCESSED_DIR / "facilitator_addresses.json"))
    facil_addrs = {a for v in facil["evm_addresses_by_facilitator"].values()
                   for a in v}

    base_picks, sol_picks, subs = pick_sellers(cfg)
    print(f"[audit] base={len(base_picks)} solana={len(sol_picks)} "
          f"substitutions={len(subs)}", flush=True)

    scan = X402ScanClient(cfg)
    bs = Client("blockscout", cfg["sources"]["blockscout_base"]
                ["min_interval_seconds"], cfg)
    rpc = Client("base-rpc", cfg["sources"]["base_rpc"]
                 ["min_interval_seconds"], cfg)

    per_seller = []
    for i, row in enumerate(base_picks):
        addr = row["recipient"]
        claimed = x402scan_transfers(scan, addr)
        append_jsonl_gz(raw_dir / "x402scan_claimed.jsonl.gz",
                        {"recipient": addr, "pulled_at": utcnow(),
                         "n": len(claimed),
                         "tx_hashes": [t["tx_hash"] for t in claimed]})
        B = {t["tx_hash"].lower() for t in claimed}
        chain_items = blockscout_usdc_in(bs, raw_dir, addr)
        A = set()
        for it in chain_items:
            h = (it.get("transaction_hash") or it.get("tx_hash") or "").lower()
            if h:
                A.add(h)
        matched = A & B
        phantom = B - A
        extra = A - B
        # classify a sample of unindexed inflows by tx initiator
        extra_facilitator = 0
        extra_checked = 0
        for h in sorted(extra)[:5]:
            rpc._throttle()
            frm = rpc_tx_from(rpc, h)
            if frm is not None:
                extra_checked += 1
                if frm in facil_addrs:
                    extra_facilitator += 1
        per_seller.append({
            "recipient": addr, "census_tx": int(row["tx_count"]),
            "x402scan_claimed": len(B), "onchain_usdc_in": len(A),
            "matched": len(matched), "phantom_claims": len(phantom),
            "unindexed_inflows": len(extra),
            "unindexed_checked": extra_checked,
            "unindexed_from_facilitator": extra_facilitator,
            "match_rate": round(len(matched) / len(B), 4) if B else None,
        })
        print(f"[audit] {i+1}/{len(base_picks)} {addr[:10]} "
              f"claimed={len(B)} matched={len(matched)} "
              f"phantom={len(phantom)}", flush=True)

    # Solana: signature existence check
    sol = Client("solana-rpc", cfg["sources"]["solana_rpc"]
                 ["min_interval_seconds"], cfg)
    sol_results = []
    for row in sol_picks:
        addr = row["recipient"]
        claimed = x402scan_transfers(scan, addr)[:20]
        found = 0
        checked = 0
        for t in claimed:
            sol._throttle()
            try:
                resp = sol.session.post(
                    cfg["sources"]["solana_rpc"]["url"], timeout=30,
                    json={"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                          "params": [t["tx_hash"],
                                     {"maxSupportedTransactionVersion": 0,
                                      "encoding": "jsonParsed"}]})
                body = resp.json()
                checked += 1
                if body.get("result"):
                    found += 1
            except Exception:
                continue
        append_jsonl_gz(raw_dir / "solana_checks.jsonl.gz",
                        {"recipient": addr, "pulled_at": utcnow(),
                         "checked": checked, "found": found})
        sol_results.append({"recipient": addr, "checked": checked,
                            "found": found})
        print(f"[audit] solana {addr[:10]} {found}/{checked}", flush=True)

    rates = sorted(r["match_rate"] for r in per_seller
                   if r["match_rate"] is not None)
    report = {
        "generated": utcnow(),
        "seed": cfg["spot_audit"]["random_seed"],
        "base_sellers_audited": len(per_seller),
        "substitutions": subs,
        "match_rate_claimed_vs_onchain": {
            "median": rates[len(rates) // 2] if rates else None,
            "min": rates[0] if rates else None,
            "max": rates[-1] if rates else None,
        },
        "total_phantom_claims": sum(r["phantom_claims"] for r in per_seller),
        "total_claimed": sum(r["x402scan_claimed"] for r in per_seller),
        "unindexed_facilitator_txs_found": sum(
            r["unindexed_from_facilitator"] for r in per_seller),
        "unindexed_txs_checked": sum(
            r["unindexed_checked"] for r in per_seller),
        "per_seller": per_seller,
        "solana_signature_existence": sol_results,
    }
    json.dump(report, open(PROCESSED_DIR / "spot_audit.json", "w"), indent=2)
    print(json.dumps({k: report[k] for k in
                      ("match_rate_claimed_vs_onchain",
                       "total_phantom_claims", "total_claimed")}, indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
