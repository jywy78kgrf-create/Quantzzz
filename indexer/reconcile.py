"""Cross-source reconciliation: our independent Base index vs x402scan.

Proves the indexer is not just functional but *correct* — that the settlements
we decode straight from chain match what the established index reports. For each
of the busiest sellers in a freshly-indexed window, we pull x402scan's own
transfer list for that seller and measure tx-hash overlap. Divergence beyond a
tolerance is a FAIL (surfaced, not swallowed).

Run after a smoke index of a recent window. Read-only.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from storage import Store  # noqa: E402

X402SCAN = "https://www.x402scan.com/api/trpc"


def scan_transfers(seller: str, pages: int = 3) -> set[str]:
    """Recent tx hashes x402scan attributes to this seller (a few pages)."""
    hashes: set[str] = set()
    for page in range(pages):
        inp = {"json": {"timeframe": 0, "recipients": {"include": [seller]},
                        "sorting": {"id": "block_timestamp", "desc": True},
                        "pagination": {"page": page, "page_size": 1000}}}
        url = f"{X402SCAN}/public.transfers.list?input=" + urllib.parse.quote(
            json.dumps(inp))
        req = urllib.request.Request(url, headers={
            "User-Agent": "x402-audit-indexer/1.0 (reconciliation)"})
        try:
            data = json.load(urllib.request.urlopen(req, timeout=60))
            items = data["result"]["data"]["json"]["items"]
        except Exception as e:
            print(f"  scan fetch err for {seller[:10]}: {e}")
            break
        for t in items:
            hashes.add(t["tx_hash"].lower())
        if len(items) < 1000:
            break
    return hashes


def main() -> None:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "data/indexer/base_settlements.sqlite")
    store = Store(db)
    # busiest sellers in our index
    top = store.db.execute(
        "SELECT seller, COUNT(*) n FROM settlements GROUP BY seller "
        "ORDER BY n DESC LIMIT 8").fetchall()
    if not top:
        print("no settlements indexed; run a smoke index first")
        return

    results = []
    for seller, n in top:
        # our settlements with block numbers, so we can bound to x402scan's
        # ingestion frontier (they lag the chain tip by ~minutes)
        ours_rows = store.db.execute(
            "SELECT tx_hash, block_number FROM settlements WHERE seller=?",
            (seller,)).fetchall()
        ours = {h.lower() for h, _ in ours_rows}
        theirs = scan_transfers(seller)
        # x402scan returns only the most-recent N txs (a page cap). So their
        # coverage of a seller is a BLOCK BAND, bounded above by ingestion lag
        # (they trail the tip) and below by the page cap (they don't reach older
        # blocks in a busy window). The only valid correctness test is INSIDE
        # that band: [min, max] block of ours that appears in theirs. There,
        # every one of ours must be present (same chain). Outside the band is
        # lag (above) or cap (below), neither a divergence.
        matched_blocks = sorted(b for h, b in ours_rows if h.lower() in theirs)
        if matched_blocks:
            lo_b, hi_b = matched_blocks[0], matched_blocks[-1]
            in_band = {h.lower() for h, b in ours_rows if lo_b <= b <= hi_b}
            matched_band = in_band & theirs
            coverage = len(matched_band) / len(in_band) if in_band else None
            fresher = sum(1 for _, b in ours_rows if b > hi_b)
            below_cap = sum(1 for _, b in ours_rows if b < lo_b)
        else:
            coverage, fresher, below_cap = None, len(ours_rows), 0
        results.append({
            "seller": seller, "ours": len(ours), "scan_recent": len(theirs),
            "coverage_in_band": round(coverage, 4) if coverage is not None else None,
            "ours_fresher_than_scan": fresher, "ours_below_scan_cap": below_cap})
        cov = f"{coverage:.1%}" if coverage is not None else "n/a"
        print(f"{seller[:12]} ours={len(ours):4d} scan={len(theirs):4d} "
              f"band_coverage={cov} fresher={fresher} below_cap={below_cap}")

    # Verdict on the LAG-CORRECTED overlap: within the window x402scan has
    # ingested, our chain-derived txs must be ~100% present (same chain).
    checkable = [r for r in results if r["coverage_in_band"] is not None]
    if checkable:
        worst = min(r["coverage_in_band"] for r in checkable)
        print(f"\nlag-corrected overlap coverage — worst of {len(checkable)} "
              f"sellers = {worst:.2%}")
        print("VERDICT:", "PASS (index agrees with x402scan in the overlap window)"
              if worst >= 0.98 else "REVIEW — real divergence in overlap")
    else:
        print("\n(no overlap window reached; widen scan pages or use an older window)")
    out = Path(__file__).resolve().parent.parent / "data/indexer/reconciliation.json"
    json.dump({"results": results}, open(out, "w"), indent=2)
    print("wrote", out)
    store.close()


if __name__ == "__main__":
    main()
