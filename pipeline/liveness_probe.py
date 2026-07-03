"""Phase 2: liveness probes — does the listed endpoint answer the phone?

Universe: unique Bazaar resource URLs (capped per origin, deterministic sorted
selection) plus x402scan-registered origin roots not covered by the Bazaar.

For each URL: unpaid GET (optional POST fallback for declared-POST routes),
record HTTP status, latency, and whether the response is a *valid x402 402*
(JSON body with x402Version + non-empty accepts[] containing scheme/network/
payTo). NO payment is ever constructed or sent by this script.

Raw    -> data/raw/liveness/<label>/results.jsonl.gz (one line per probe)
Processed -> data/processed/liveness_results.csv
Resumable via the raw shard itself (probed URL set).
"""

from __future__ import annotations

import csv
import gzip
import json
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from lib import PROCESSED_DIR, RAW_DIR, load_config, utcnow, iter_jsonl_gz

BAZAAR = PROCESSED_DIR / "bazaar_resources.csv"
ORIGIN_MAP = PROCESSED_DIR / "origin_wallet_map.csv"

_write_lock = threading.Lock()
_host_lock: dict[str, threading.Lock] = defaultdict(threading.Lock)
_host_last: dict[str, float] = defaultdict(float)
_global_lock = threading.Lock()
_global_last = [0.0]


def build_universe(cfg: dict) -> list[dict]:
    per_origin_cap = cfg["liveness"]["max_resources_per_origin"]
    by_origin: dict[str, list[dict]] = defaultdict(list)
    methods: dict[str, str] = {}

    # Bazaar resources (with declared method when present in extensions)
    with open(BAZAAR) as f:
        for row in csv.DictReader(f):
            url = row["resource_url"]
            if row["accept_index"] != "0" or not url.startswith("http"):
                continue
            origin = urlparse(url).netloc
            by_origin[origin].append({"url": url, "kind": "bazaar_resource"})

    # Declared HTTP methods from raw Bazaar pages (extensions.bazaar.info.input.method)
    label = cfg["snapshot"]["label"]
    raw_dir = RAW_DIR / "bazaar" / label
    for page in sorted(raw_dir.glob("page_*.json.gz")):
        body = json.load(gzip.open(page, "rt"))
        for it in body.get("items", []):
            try:
                m = it["extensions"]["bazaar"]["info"]["input"]["method"]
                methods[it["resource"]] = m
            except (KeyError, TypeError):
                pass

    # x402scan origins not present in the Bazaar universe: probe origin root
    bazaar_origins = set(by_origin)
    with open(ORIGIN_MAP) as f:
        for row in csv.DictReader(f):
            o = row["origin"]
            if not o.startswith("http"):
                continue
            netloc = urlparse(o).netloc
            if netloc and netloc not in bazaar_origins:
                by_origin[netloc].append({"url": o, "kind": "x402scan_origin_root"})
                bazaar_origins.add(netloc)

    universe: list[dict] = []
    for origin in sorted(by_origin):
        picks = sorted(by_origin[origin], key=lambda d: d["url"])[:per_origin_cap]
        for p in picks:
            p["declared_method"] = methods.get(p["url"], "")
            universe.append(p)
    return universe


def throttle(host: str, cfg: dict) -> None:
    lv = cfg["liveness"]
    with _global_lock:
        wait = _global_last[0] + lv["min_interval_seconds"] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _global_last[0] = time.monotonic()
    with _host_lock[host]:
        wait = _host_last[host] + lv["per_host_min_interval_seconds"] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _host_last[host] = time.monotonic()


def parse_x402(body_bytes: bytes) -> dict:
    """Is this a valid x402 payment-required response?"""
    out = {"valid_402_body": False, "x402_version": None, "n_accepts": 0,
           "schemes": "", "networks": ""}
    try:
        data = json.loads(body_bytes)
    except Exception:
        return out
    if not isinstance(data, dict):
        return out
    accepts = data.get("accepts")
    if not isinstance(accepts, list) or not accepts:
        return out
    ok = all(isinstance(a, dict) and a.get("scheme") and a.get("network")
             and (a.get("payTo") or a.get("pay_to")) for a in accepts)
    out["valid_402_body"] = bool(ok)
    out["x402_version"] = data.get("x402Version")
    out["n_accepts"] = len(accepts)
    out["schemes"] = "|".join(sorted({str(a.get("scheme")) for a in accepts}))
    out["networks"] = "|".join(sorted({str(a.get("network")) for a in accepts}))
    return out


def probe(entry: dict, cfg: dict, session: requests.Session, out_path) -> None:
    lv = cfg["liveness"]
    url = entry["url"]
    host = urlparse(url).netloc
    result = {"url": url, "kind": entry["kind"],
              "declared_method": entry["declared_method"],
              "ts": utcnow(), "method_used": "GET", "status": None,
              "elapsed_ms": None, "error": None, "final_url": None,
              "content_type": None, **parse_x402(b"")}
    for method in (["GET", "POST"] if lv["post_fallback"] else ["GET"]):
        if method == "POST" and not (
                result["status"] in (404, 405)
                and entry["declared_method"] in ("POST", "PUT", "PATCH")):
            continue
        throttle(host, cfg)
        t0 = time.monotonic()
        try:
            resp = session.request(
                method, url, timeout=lv["timeout_seconds"],
                json={} if method == "POST" else None,
                allow_redirects=True, stream=True)
            body = resp.raw.read(lv["max_body_bytes"], decode_content=True)
            result.update({
                "method_used": method,
                "status": resp.status_code,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "final_url": resp.url,
                "content_type": resp.headers.get("Content-Type", ""),
                "error": None,
            })
            result.update(parse_x402(body))
            resp.close()
        except requests.RequestException as exc:
            result.update({
                "method_used": method,
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "error": type(exc).__name__ + ": " + str(exc)[:200],
            })
            break  # network-level failure: no POST retry
        if result["status"] == 402 and result["valid_402_body"]:
            break
    with _write_lock, gzip.open(out_path, "at") as f:
        f.write(json.dumps(result, separators=(",", ":")) + "\n")


def main() -> None:
    cfg = load_config()
    label = cfg["snapshot"]["label"]
    out_dir = RAW_DIR / "liveness" / label
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.jsonl.gz"

    done: set[str] = set()
    if out_path.exists():
        done = {r["url"] for r in iter_jsonl_gz(out_path)}

    universe = build_universe(cfg)
    todo = [e for e in universe if e["url"] not in done]
    print(f"[liveness] universe={len(universe)} done={len(done)} todo={len(todo)}",
          flush=True)

    session = requests.Session()
    session.headers["User-Agent"] = cfg["http"]["user_agent"]
    n = [0]

    def run(entry: dict) -> None:
        probe(entry, cfg, session, out_path)
        n[0] += 1
        if n[0] % 200 == 0:
            print(f"[liveness] {n[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(max_workers=cfg["liveness"]["concurrency"]) as pool:
        list(pool.map(run, todo))

    # processed CSV
    rows = list(iter_jsonl_gz(out_path))
    out_csv = PROCESSED_DIR / "liveness_results.csv"
    cols = ["url", "kind", "declared_method", "method_used", "status",
            "valid_402_body", "x402_version", "n_accepts", "schemes",
            "networks", "elapsed_ms", "content_type", "error", "ts"]
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[liveness] wrote {out_csv} ({len(rows)} probes)", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
