"""On-chain validation of SURPLUS settlements (ours that x402scan lacks).

reconcile.py allows surplus — a direct chain read legitimately catches
settlements the reference index misses (observed on Solana, where x402scan
sources from Bitquery and lags/samples). But surplus must never be a hiding
place for false positives. This script samples surplus rows and confirms each
is a REAL facilitator-relayed USDC transfer landing at the recorded seller.

Solana: getTransaction, confirm fee payer == recorded facilitator and the
recorded seller is a USDC post-token-balance owner.
Read-only. Needs X402_SOLANA_RPC (keyed RPC) for Solana.

Usage: python3 indexer/validate_surplus.py [sample_n]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from storage import Store  # noqa: E402

USDC_SOLANA = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
X402SCAN = "https://www.x402scan.com/api/trpc"
UA = {"User-Agent": "x402-audit-indexer/1.0 (surplus-validation)"}
DB = Path(__file__).resolve().parent.parent / "data/indexer/base_settlements.sqlite"


def scan_hashes(seller: str, pages: int = 4) -> set[str]:
    out: set[str] = set()
    for page in range(pages):
        inp = {"json": {"timeframe": 0, "recipients": {"include": [seller]},
                        "sorting": {"id": "block_timestamp", "desc": True},
                        "pagination": {"page": page, "page_size": 1000}}}
        url = f"{X402SCAN}/public.transfers.list?input=" + urllib.parse.quote(
            json.dumps(inp))
        try:
            data = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=60))
            items = data["result"]["data"]["json"]["items"]
        except Exception as e:
            print(f"  scan err {seller[:10]}: {e}")
            break
        for t in items:
            out.add(t["tx_hash"])
        if len(items) < 1000:
            break
    return out


def verify_solana(rpc: str, sig: str, seller: str, facilitator: str) -> dict:
    body = requests.post(rpc, headers=UA, timeout=40, json={
        "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
        "params": [sig, {"encoding": "jsonParsed",
                         "maxSupportedTransactionVersion": 0}]}).json()
    tx = body.get("result")
    if not tx:
        return {"ok": False, "reason": "tx_not_found"}
    keys = tx["transaction"]["message"]["accountKeys"]
    fee_payer = keys[0]["pubkey"] if isinstance(keys[0], dict) else keys[0]
    owners = {b["owner"] for b in (tx.get("meta") or {}).get("postTokenBalances", [])
              if b.get("mint") == USDC_SOLANA and b.get("owner")}
    return {
        "ok": (fee_payer == facilitator) and (seller in owners),
        "fee_payer_matches_facilitator": fee_payer == facilitator,
        "seller_receives_usdc": seller in owners,
    }


def main() -> None:
    sample_n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    rpc = os.environ.get("X402_SOLANA_RPC")
    store = Store(DB)
    top = store.db.execute(
        "SELECT seller, COUNT(*) n FROM settlements WHERE chain='solana' "
        "GROUP BY seller ORDER BY n DESC LIMIT 5").fetchall()
    if not top:
        print("no solana settlements indexed")
        return
    if not rpc:
        print("X402_SOLANA_RPC not set — cannot validate Solana surplus")
        return

    checked, real = 0, 0
    details = []
    for seller, _ in top:
        ours = store.db.execute(
            "SELECT tx_hash, facilitator FROM settlements "
            "WHERE seller=? AND chain='solana'", (seller,)).fetchall()
        theirs = scan_hashes(seller)
        surplus = [(h, f) for h, f in ours if h not in theirs]
        for sig, fac in surplus[: max(1, sample_n // len(top))]:
            v = verify_solana(rpc, sig, seller, fac)
            checked += 1
            real += 1 if v["ok"] else 0
            details.append({"seller": seller[:12], "sig": sig[:16], **v})
            if not v["ok"]:
                print(f"  FALSE POSITIVE? {seller[:12]} {sig[:16]} {v}")

    out = {"checked": checked, "confirmed_real": real,
           "false_positives": checked - real, "details": details}
    path = Path(__file__).resolve().parent.parent / "data/indexer/surplus_validation.json"
    json.dump(out, open(path, "w"), indent=2)
    print(f"\nsurplus validated: {real}/{checked} confirmed real "
          f"facilitator-relayed USDC transfers")
    print("VERDICT:", "PASS — surplus is real, no false positives"
          if checked and real == checked else
          f"REVIEW — {checked - real} surplus rows not on-chain-confirmed")
    print("wrote", path)
    store.close()


if __name__ == "__main__":
    main()
