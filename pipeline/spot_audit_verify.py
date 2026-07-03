"""DELTA 2b follow-up: re-verify apparent phantom claims via direct Base RPC.

The Blockscout token-transfers listing missed some transfers (its filter/index
quirk, e.g. transfers emitted inside batched or contract-routed txs). Every
claimed-but-unmatched tx_hash is checked against eth_getTransactionReceipt:
a claim is a TRUE phantom only if the tx does not exist, failed, or contains
no USDC Transfer log paying the audited seller.

Rewrites data/processed/spot_audit.json in place with corrected fields
(original per-seller rows preserved; adds rpc_verified_* fields).
"""

from __future__ import annotations

import gzip
import json
import sys

from lib import PROCESSED_DIR, RAW_DIR, Client, load_config, utcnow

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # ERC-20 Transfer event topic (public constant, not-a-key)


def main() -> None:
    cfg = load_config()
    label = cfg["snapshot"]["label"]
    report = json.load(open(PROCESSED_DIR / "spot_audit.json"))

    claimed_by_seller: dict[str, list[str]] = {}
    for line in gzip.open(RAW_DIR / "onchain" / label /
                          "x402scan_claimed.jsonl.gz", "rt"):
        r = json.loads(line)
        claimed_by_seller[r["recipient"]] = r["tx_hashes"]

    # matched hashes per seller come from blockscout pages
    onchain_by_seller: dict[str, set[str]] = {}
    for line in gzip.open(RAW_DIR / "onchain" / label /
                          "blockscout_pages.jsonl.gz", "rt"):
        r = json.loads(line)
        s = onchain_by_seller.setdefault(r["addr"], set())
        for it in r["body"].get("items", []):
            h = (it.get("transaction_hash") or "").lower()
            if h:
                s.add(h)

    rpc = Client("base-rpc", cfg["sources"]["base_rpc"]["min_interval_seconds"], cfg)
    true_phantoms = 0
    recovered = 0
    details = []
    for row in report["per_seller"]:
        addr = row["recipient"]
        B = {h.lower() for h in claimed_by_seller.get(addr, [])}
        A = onchain_by_seller.get(addr, set())
        for h in sorted(B - A):
            rpc._throttle()
            resp = rpc.session.post(
                cfg["sources"]["base_rpc"]["url"], timeout=30,
                json={"jsonrpc": "2.0", "id": 1,
                      "method": "eth_getTransactionReceipt", "params": [h]})
            rcpt = resp.json().get("result")
            ok = False
            if rcpt and rcpt.get("status") == "0x1":
                for log in rcpt.get("logs", []):
                    if (log["address"].lower() == USDC
                            and log["topics"][0] == TRANSFER_TOPIC
                            and len(log["topics"]) >= 3
                            and log["topics"][2][-40:].lower() == addr[2:].lower()):
                        ok = True
                        break
            details.append({"recipient": addr, "tx_hash": h,
                            "rpc_verified_usdc_to_seller": ok})
            if ok:
                recovered += 1
                row["match_rate"] = round(
                    (row["matched"] + 1) / row["x402scan_claimed"], 4)
                row["matched"] += 1
                row["phantom_claims"] -= 1
                row["rpc_recovered"] = row.get("rpc_recovered", 0) + 1
            else:
                true_phantoms += 1

    rates = sorted(r["match_rate"] for r in report["per_seller"]
                   if r["match_rate"] is not None)
    report["rpc_phantom_verification"] = {
        "verified_at": utcnow(),
        "apparent_phantoms_rechecked": recovered + true_phantoms,
        "recovered_via_rpc": recovered,
        "true_phantoms": true_phantoms,
        "detail": details,
        "note": ("Blockscout's token-transfers listing missed transfers "
                 "emitted inside contract-routed txs; direct receipt check "
                 "is authoritative."),
    }
    report["match_rate_claimed_vs_onchain"] = {
        "median": rates[len(rates) // 2] if rates else None,
        "min": rates[0] if rates else None,
        "max": rates[-1] if rates else None,
    }
    report["total_phantom_claims"] = true_phantoms
    json.dump(report, open(PROCESSED_DIR / "spot_audit.json", "w"), indent=2)
    print(json.dumps({"recovered": recovered, "true_phantoms": true_phantoms,
                      "match_rate": report["match_rate_claimed_vs_onchain"]},
                     indent=2))


if __name__ == "__main__":
    main()
    sys.exit(0)
