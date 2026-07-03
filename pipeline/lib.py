"""Shared plumbing for the x402 endpoint quality audit.

Every outbound HTTP request goes through Client.get()/post(), which enforces
the per-source throttle and appends one line per request to the append-only
request log (data/raw/request_log.jsonl): timestamp, source, URL, params,
status, latency, and a sha256 of the response body.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
RAW_DIR = REPO_ROOT / "data" / "raw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
REQUEST_LOG = RAW_DIR / "request_log.jsonl"

_log_lock = threading.Lock()


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_request(entry: dict) -> None:
    REQUEST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock, open(REQUEST_LOG, "a") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


class Client:
    """Throttled, retrying, request-logging HTTP client for one source."""

    def __init__(self, source: str, min_interval: float, cfg: dict | None = None):
        cfg = cfg or load_config()
        self.source = source
        self.min_interval = min_interval
        self.timeout = cfg["http"]["timeout_seconds"]
        self.max_retries = cfg["http"]["max_retries"]
        self.backoff = cfg["http"]["backoff_base_seconds"]
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg["http"]["user_agent"]
        self._last_request = 0.0
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get(self, url: str, params: dict | None = None, ok_statuses=(200,),
            log_extra: dict | None = None) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            t0 = time.monotonic()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                _log_request({
                    "ts": utcnow(), "source": self.source, "method": "GET",
                    "url": url, "params": params, "status": resp.status_code,
                    "elapsed_ms": elapsed_ms,
                    "sha256": hashlib.sha256(resp.content).hexdigest(),
                    "bytes": len(resp.content), "attempt": attempt,
                    **(log_extra or {}),
                })
                if resp.status_code in ok_statuses:
                    return resp
                if resp.status_code in (429, 500, 502, 503, 504):
                    time.sleep(self.backoff * (2 ** attempt))
                    continue
                resp.raise_for_status()
                return resp  # unexpected but non-error status
            except requests.RequestException as exc:
                last_exc = exc
                _log_request({
                    "ts": utcnow(), "source": self.source, "method": "GET",
                    "url": url, "params": params, "status": None,
                    "error": str(exc)[:300], "attempt": attempt,
                    **(log_extra or {}),
                })
                time.sleep(self.backoff * (2 ** attempt))
        raise RuntimeError(f"{self.source}: GET {url} failed after "
                           f"{self.max_retries} attempts: {last_exc}")


class X402ScanClient(Client):
    """tRPC-over-GET client for x402scan's public API (superjson envelope)."""

    def __init__(self, cfg: dict | None = None):
        cfg = cfg or load_config()
        src = cfg["sources"]["x402scan"]
        super().__init__("x402scan", src["min_interval_seconds"], cfg)
        self.base_url = src["base_url"]

    def trpc(self, procedure: str, inp: dict) -> dict:
        envelope = json.dumps({"json": inp}, separators=(",", ":"))
        url = (f"{self.base_url}/{procedure}?input="
               f"{urllib.parse.quote(envelope)}")
        resp = self.get(url, log_extra={"procedure": procedure, "input": inp})
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"tRPC error from {procedure}: "
                               f"{json.dumps(body['error'])[:500]}")
        return body["result"]["data"]["json"]


def save_raw_gz(path: Path, payload) -> None:
    """Store a raw pull (parsed JSON payload) gzip-compressed, never overwriting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite raw file: {path}")
    with gzip.open(path, "wt") as f:
        json.dump(payload, f, separators=(",", ":"))


def load_raw_gz(path: Path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def append_jsonl_gz(path: Path, record: dict) -> None:
    """Append one record to a gzip JSONL shard (raw deep-pull storage)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


def iter_jsonl_gz(path: Path):
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def seeded_rng(cfg_seed: int, namespace: str) -> random.Random:
    """Deterministic RNG derived from the committed seed and a namespace."""
    h = hashlib.sha256(f"{cfg_seed}:{namespace}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))
