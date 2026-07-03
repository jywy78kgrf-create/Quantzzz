"""Defensive Solana JSON-RPC client. Retries, cursor pagination for signatures.

Solana has no log-topic filter, so we enumerate each facilitator relayer's
signature history (getSignaturesForAddress, cursor-based) and fetch each tx.
"""

from __future__ import annotations

import time

import requests


class SolRpcError(RuntimeError):
    pass


class SolanaClient:
    def __init__(self, url: str, *, timeout: int = 45, max_retries: int = 6,
                 user_agent: str = "x402-audit-indexer/1.0"):
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self._id = 0

    def _call(self, method: str, params: list):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method,
                   "params": params}
        last = None
        for attempt in range(self.max_retries):
            try:
                r = self.session.post(self.url, json=payload, timeout=self.timeout)
                if r.status_code == 429:
                    # public mainnet-beta throttles aggressively; honor
                    # Retry-After and back off hard. A keyed RPC (Helius/Triton/
                    # QuickNode free tier) avoids this — see README.
                    wait = float(r.headers.get("Retry-After", 0)) or min(2 ** attempt, 20)
                    time.sleep(wait + 0.5)
                    last = SolRpcError("http 429 (rate limited)")
                    continue
                if r.status_code in (500, 502, 503, 504):
                    raise SolRpcError(f"http {r.status_code}")
                body = r.json()
                if "error" in body:
                    # 429-equivalent rate limits come back as JSON errors too
                    msg = str(body["error"])
                    if "rate" in msg.lower() or "-32005" in msg:
                        raise SolRpcError(msg)
                    raise SolRpcError(msg)
                return body["result"]
            except (requests.RequestException, SolRpcError, ValueError) as e:
                last = e
                time.sleep(min(2 ** attempt, 30))
        raise SolRpcError(f"{method} failed after {self.max_retries}: {last}")

    def get_slot(self) -> int:
        return self._call("getSlot", [{"commitment": "finalized"}])

    def signatures_since(self, address: str, until_sig: str | None,
                         page: int = 1000):
        """All signatures for `address` newer than `until_sig`, oldest-first.

        getSignaturesForAddress returns newest-first; we page backward with
        `before` until we either reach `until_sig` or run out, then reverse so
        the caller processes chronologically. `until` makes the RPC stop at the
        cursor, so a fully-paginated result has no gap above the cursor.
        """
        collected = []
        before = None
        while True:
            params = [address, {"limit": page}]
            opts = params[1]
            if before:
                opts["before"] = before
            if until_sig:
                opts["until"] = until_sig
            batch = self._call("getSignaturesForAddress", params)
            if not batch:
                break
            collected.extend(batch)
            if len(batch) < page:
                break
            before = batch[-1]["signature"]
        collected.reverse()   # chronological (oldest -> newest)
        return collected

    def get_transaction(self, signature: str):
        return self._call("getTransaction", [signature, {
            "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
