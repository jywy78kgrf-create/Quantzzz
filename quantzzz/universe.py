"""Trading universes for each desk.

The equity universe is a fixed seed of liquid US large/mid caps. The biotech
universe is derived from the BPIQ company snapshot (small/mid-cap names with
catalyst history), falling back to a curated seed when no snapshot exists.
"""

from __future__ import annotations

import json
from pathlib import Path

EQUITY_UNIVERSE = [
    # mega/large tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "CRM", "ORCL", "ADBE",
    "AMD", "QCOM", "TXN", "INTC", "MU", "NOW", "UBER", "SHOP",
    # financials
    "JPM", "BAC", "WFC", "GS", "MS", "BLK", "SCHW", "AXP", "V", "MA",
    # healthcare (large-cap, non-speculative)
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "BMY", "AMGN",
    # consumer
    "WMT", "COST", "HD", "MCD", "NKE", "SBUX", "TGT", "PG", "KO", "PEP",
    # industrials / energy
    "CAT", "DE", "BA", "GE", "HON", "UNP", "XOM", "CVX", "COP", "SLB",
    # comms / media
    "DIS", "NFLX", "CMCSA", "T", "VZ",
]

BIOTECH_SEED = [
    "VRTX", "REGN", "GILD", "BIIB", "MRNA", "ALNY", "BMRN", "INCY", "SRPT", "IONS",
    "NBIX", "EXEL", "HALO", "UTHR", "RARE", "ACAD", "PTCT", "INSM", "AXSM", "MDGL",
    "KRYS", "CYTK", "ARWR", "BPMC", "FOLD", "DVAX", "VKTX", "RYTM", "AGIO", "IMVT",
    "APLS", "ARQT", "AURA", "BCRX", "CLDX", "CORT", "CPRX", "ETNB", "IRWD", "KURA",
    "LQDA", "MIRM", "PCRX", "PRTA", "RIGL", "SAVA", "SUPN", "TGTX", "VERA", "XNCR",
]

BENCH_TICKERS = ["SPY", "XBI"]


def biotech_universe(snapshot_dir: Path) -> list[str]:
    """Universe from the BPIQ companies snapshot, else the curated seed."""
    path = snapshot_dir / "bpiq" / "universe.json"
    if path.exists():
        tickers = json.loads(path.read_text())
        if tickers:
            return tickers
    return list(BIOTECH_SEED)


def universe_for(desk: str, snapshot_dir: Path) -> list[str]:
    """The LIVE/tradeable universe (active names only)."""
    if desk == "equity":
        return list(EQUITY_UNIVERSE)
    if desk == "biotech":
        return biotech_universe(snapshot_dir)
    raise ValueError(f"unknown desk: {desk}")


def delisted_pool(snapshot_dir: Path) -> list[str]:
    meta = []
    path = snapshot_dir / "delisted.json"
    if path.exists():
        meta = json.loads(path.read_text())
    return [m["ticker"] for m in meta]


# Biotechs that left the market 2020-2024 — both tails of the outcome
# distribution: failures/bankruptcies (the survivorship hole that flatters
# catalyst backtests most) and acquisitions (the upside exits). Price history
# is fetched by refresh_biotech_survivorship_pool; names without history are
# carried as candidates until the data provider serves them.
BIOTECH_DELISTED_SEED = [
    {"ticker": "CLVS", "name": "Clovis Oncology", "exit": "bankruptcy 2022"},
    {"ticker": "ATHX", "name": "Athersys", "exit": "bankruptcy 2024"},
    {"ticker": "NBRV", "name": "Nabriva Therapeutics", "exit": "wind-down 2023"},
    {"ticker": "BIVI", "name": "BiOptio (reverse-split spiral)", "exit": "delisted"},
    {"ticker": "SGEN", "name": "Seagen", "exit": "acquired (Pfizer) 2023"},
    {"ticker": "HZNP", "name": "Horizon Therapeutics", "exit": "acquired (Amgen) 2023"},
    {"ticker": "RETA", "name": "Reata Pharmaceuticals", "exit": "acquired (Biogen) 2023"},
    {"ticker": "KRTX", "name": "Karuna Therapeutics", "exit": "acquired (BMS) 2024"},
    {"ticker": "CERE", "name": "Cerevel Therapeutics", "exit": "acquired (AbbVie) 2024"},
    {"ticker": "GBT",  "name": "Global Blood Therapeutics", "exit": "acquired (Pfizer) 2022"},
    {"ticker": "ARNA", "name": "Arena Pharmaceuticals", "exit": "acquired (Pfizer) 2022"},
    {"ticker": "ZGNX", "name": "Zogenix", "exit": "acquired (UCB) 2022"},
    {"ticker": "AKCA", "name": "Akcea Therapeutics", "exit": "acquired (Ionis) 2020"},
    {"ticker": "CINC", "name": "CinCor Pharma", "exit": "acquired (AstraZeneca) 2023"},
    {"ticker": "PRVB", "name": "Provention Bio", "exit": "acquired (Sanofi) 2023"},
    {"ticker": "AMAG", "name": "AMAG Pharmaceuticals", "exit": "acquired 2020"},
]


def delisted_biotech_pool(snapshot_dir: Path) -> list[str]:
    path = snapshot_dir / "delisted_biotech.json"
    if path.exists():
        return [m["ticker"] for m in json.loads(path.read_text())]
    return []


def research_universe_for(desk: str, snapshot_dir: Path) -> list[str]:
    """The BACKTEST universe: live names plus delisted companies, so research
    sees the firms that died (survivorship-bias mitigation). Equity draws on
    the generic delisted pool; biotech on the curated dead-biotech pool —
    the sector where ignoring the dead flatters backtests the most."""
    base = universe_for(desk, snapshot_dir)
    if desk == "equity":
        return base + [t for t in delisted_pool(snapshot_dir) if t not in base]
    if desk == "biotech":
        return base + [t for t in delisted_biotech_pool(snapshot_dir) if t not in base]
    return base
