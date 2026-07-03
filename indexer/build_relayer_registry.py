"""Extract the facilitator RELAYER address registry from the x402scan source.

Why this exists: the indexer's entire notion of "an x402 settlement" is "a USDC
transfer submitted by a facilitator relayer." If the relayer set is wrong, every
downstream number is silently wrong for as long as the indexer runs. So we parse
the *structured* `addresses: { [Network.X]: [{address, dateOfFirstTransaction}] }`
blocks from each facilitator definition — NOT a blind hex grep, which would pull
in example payTo/receiver addresses and poison the set.

Source: github.com/Merit-Systems/x402scan @ pinned commit (recorded in output).
Run against a local clone path passed as argv[1].

Output: data/indexer/relayer_registry.json
  { facilitator_id: { base: [{address, first_tx_date}], solana: [...] } }
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT = REPO_ROOT / "data" / "indexer" / "relayer_registry.json"

NETWORK_RE = re.compile(r"\[Network\.(\w+)\]\s*:")
ADDRESS_RE = re.compile(r"address:\s*['\"]([^'\"]+)['\"]")
DATE_RE = re.compile(r"dateOfFirstTransaction:\s*new Date\(['\"]([^'\"]+)['\"]\)")
ID_RE = re.compile(r"id:\s*['\"]([^'\"]+)['\"]")


def parse_facilitator(path: Path) -> tuple[str, dict]:
    """Return (facilitator_id, {network: [{address, first_tx_date}]}).

    We walk the file linearly, tracking which `[Network.X]:` section we're inside.
    An address line inherits the most recent network header. We only enter address
    collection once we've seen the `addresses:` key, to avoid picking up unrelated
    address literals elsewhere in the file (e.g. token constants).
    """
    text = path.read_text()
    fid_match = ID_RE.search(text)
    facilitator_id = fid_match.group(1) if fid_match else path.stem

    # Restrict to the `addresses: { ... }` object to avoid stray literals.
    addr_start = text.find("addresses:")
    if addr_start == -1:
        return facilitator_id, {}
    # find the matching closing brace for the addresses object
    brace_open = text.find("{", addr_start)
    depth, i = 0, brace_open
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = text[brace_open:i + 1]

    result: dict[str, list] = {}
    current_net: str | None = None
    pending_date: str | None = None
    for line in block.splitlines():
        nm = NETWORK_RE.search(line)
        if nm:
            current_net = nm.group(1).lower()
            result.setdefault(current_net, [])
            continue
        dm = DATE_RE.search(line)
        if dm:
            pending_date = dm.group(1)
        am = ADDRESS_RE.search(line)
        if am and current_net:
            result[current_net].append({
                "address": am.group(1),
                "first_tx_date": pending_date,
            })
            pending_date = None
    return facilitator_id, result


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: build_relayer_registry.py <path-to-x402scan-clone>")
        sys.exit(2)
    clone = Path(sys.argv[1])
    fac_dir = clone / "packages/external/facilitators/src/facilitators"
    if not fac_dir.is_dir():
        print(f"facilitators dir not found under {clone}")
        sys.exit(2)

    commit = "unknown"
    head = clone / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref:"):
            commit = (clone / ".git" / ref.split(" ", 1)[1].strip()).read_text().strip()
        else:
            commit = ref
    except Exception:
        pass

    registry: dict[str, dict] = {}
    norm_base: set[str] = set()
    norm_sol: set[str] = set()
    for f in sorted(fac_dir.glob("*.ts")):
        if f.stem == "index":
            continue
        fid, addrs = parse_facilitator(f)
        if not addrs:
            continue
        registry[fid] = addrs
        for a in addrs.get("base", []):
            norm_base.add(a["address"].lower())
        for a in addrs.get("solana", []):
            norm_sol.add(a["address"])

    out = {
        "source": "github.com/Merit-Systems/x402scan",
        "source_commit": commit,
        "note": ("Relayer (tx sender) addresses per facilitator per network, "
                 "parsed from the structured `addresses` blocks. A settlement "
                 "= a USDC transfer whose tx.from is one of these."),
        "facilitators": registry,
        "base_relayers_lower": sorted(norm_base),
        "solana_relayers": sorted(norm_sol),
        "counts": {
            "facilitators": len(registry),
            "base_relayers": len(norm_base),
            "solana_relayers": len(norm_sol),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(f"wrote {OUT}")
    print(json.dumps(out["counts"], indent=2))
    # sanity: flag any base address that isn't a well-formed 0x40hex
    bad = [a for a in norm_base if not re.fullmatch(r"0x[0-9a-f]{40}", a)]
    if bad:
        print("WARNING malformed base addresses:", bad)


if __name__ == "__main__":
    main()
