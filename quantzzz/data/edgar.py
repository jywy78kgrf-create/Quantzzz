"""SEC EDGAR client (free public APIs at data.sec.gov / www.sec.gov).

Provides point-in-time fundamental series for the "beat and raise" signal and
parsed Form 4 insider net-buy series. All series are keyed by *filed* date so
strategies only see information when the market could have seen it.
"""

from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET

import requests

from ..config import Config
from .cache import Cache
from .ratelimit import RateLimiter, with_backoff

WEEK_S = 7 * 24 * 3600
DAY_S = 24 * 3600

EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
REVENUE_TAGS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
CASH_TAGS = [
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
]
OPCF_TAGS = ["NetCashProvidedByUsedInOperatingActivities"]


class EdgarClient:
    def __init__(self, cfg: Config, conn: sqlite3.Connection):
        self.cache = Cache(conn)
        self.headers = {"User-Agent": cfg.edgar_user_agent}
        self.limiter = RateLimiter(calls_per=8, period_s=1)

    def _get_json(self, url: str, key: str, ttl_s: int):
        def fetch():
            self.limiter.wait()
            resp = with_backoff(
                lambda: requests.get(url, headers=self.headers, timeout=30)
            )
            resp.raise_for_status()
            return resp.json()

        return self.cache.get_or_fetch(key, "edgar", ttl_s, fetch)

    def _get_text(self, url: str) -> str:
        self.limiter.wait()
        resp = with_backoff(lambda: requests.get(url, headers=self.headers, timeout=30))
        resp.raise_for_status()
        return resp.text

    # ---- company identity ----
    def ticker_map(self) -> dict[str, str]:
        """ticker -> zero-padded 10-digit CIK."""
        data = self._get_json(
            "https://www.sec.gov/files/company_tickers.json", "edgar:tickers", WEEK_S
        )
        return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in data.values()}

    def cik_for(self, ticker: str) -> str | None:
        return self.ticker_map().get(ticker.upper())

    # ---- fundamentals ----
    def company_facts(self, cik: str) -> dict | None:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            return self._get_json(url, f"edgar:facts:{cik}", DAY_S * 3)
        except Exception:
            return None

    @staticmethod
    def _quarterly_series(facts: dict, tags: list[str]) -> list[dict]:
        """[{end, filed, val}] quarterly points from the first tag that has them."""
        gaap = facts.get("facts", {}).get("us-gaap", {})
        for tag in tags:
            units = gaap.get(tag, {}).get("units", {})
            pts = units.get("USD") or units.get("USD/shares") or []
            quarterly = [
                {"end": p["end"], "filed": p["filed"], "val": p["val"]}
                for p in pts
                if p.get("form") in ("10-Q", "10-K") and p.get("fp")
                and p.get("start") and _months_between(p["start"], p["end"]) <= 4
            ]
            if quarterly:
                # dedupe by period end, keep the earliest filing of each period
                by_end: dict[str, dict] = {}
                for p in sorted(quarterly, key=lambda x: x["filed"]):
                    by_end.setdefault(p["end"], p)
                return sorted(by_end.values(), key=lambda x: x["end"])
        return []

    @staticmethod
    def _instant_series(facts: dict, tags: list[str]) -> list[dict]:
        gaap = facts.get("facts", {}).get("us-gaap", {})
        for tag in tags:
            pts = gaap.get(tag, {}).get("units", {}).get("USD", [])
            instants = [
                {"end": p["end"], "filed": p["filed"], "val": p["val"]}
                for p in pts
                if p.get("form") in ("10-Q", "10-K") and not p.get("start")
            ]
            if instants:
                by_end: dict[str, dict] = {}
                for p in sorted(instants, key=lambda x: x["filed"]):
                    by_end.setdefault(p["end"], p)
                return sorted(by_end.values(), key=lambda x: x["end"])
        return []

    def fundamental_series(self, ticker: str) -> dict | None:
        """Quarterly EPS, revenue, cash and operating cash flow with filed dates."""
        cik = self.cik_for(ticker)
        if cik is None:
            return None
        facts = self.company_facts(cik)
        if facts is None:
            return None
        return {
            "ticker": ticker,
            "cik": cik,
            "eps": self._quarterly_series(facts, EPS_TAGS),
            "revenue": self._quarterly_series(facts, REVENUE_TAGS),
            "cash": self._instant_series(facts, CASH_TAGS),
            "op_cash_flow": self._quarterly_series(facts, OPCF_TAGS),
        }

    # ---- insider transactions (Form 4) ----
    def insider_transactions(self, ticker: str, max_filings: int = 25) -> list[dict]:
        """Parsed Form 4 open-market transactions: [{filed, code, shares, value}]."""
        cik = self.cik_for(ticker)
        if cik is None:
            return []
        subs = self._get_json(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            f"edgar:subs:{cik}", DAY_S,
        )
        recent = subs.get("filings", {}).get("recent", {})
        txns: list[dict] = []
        count = 0
        for form, accession, filed, doc in zip(
            recent.get("form", []),
            recent.get("accessionNumber", []),
            recent.get("filingDate", []),
            recent.get("primaryDocument", []),
        ):
            if form != "4" or count >= max_filings:
                continue
            count += 1
            try:
                txns.extend(self._parse_form4(cik, accession, filed, doc))
            except Exception:
                continue
        return txns

    def _parse_form4(self, cik: str, accession: str, filed: str, doc: str) -> list[dict]:
        acc = accession.replace("-", "")
        # the primary document is usually an xsl-rendered page; the raw xml sits beside it
        xml_name = re.sub(r"^.*/", "", doc).replace(".html", ".xml").replace(".htm", ".xml")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{xml_name}"
        key = f"edgar:form4:{accession}"

        def fetch():
            return {"xml": self._get_text(url)}

        payload = self.cache.get_or_fetch(key, "edgar", WEEK_S * 52, fetch)
        root = ET.fromstring(payload["xml"])
        out = []
        for txn in root.iter("nonDerivativeTransaction"):
            code = txn.findtext("./transactionCoding/transactionCode", "")
            if code not in ("P", "S"):  # open-market purchase / sale only
                continue
            shares = float(txn.findtext(
                "./transactionAmounts/transactionShares/value", "0") or 0)
            price = float(txn.findtext(
                "./transactionAmounts/transactionPricePerShare/value", "0") or 0)
            out.append({
                "filed": filed,
                "code": code,
                "shares": shares,
                "value": shares * price,
            })
        return out


def _months_between(start: str, end: str) -> int:
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    return (ey - sy) * 12 + (em - sm)
