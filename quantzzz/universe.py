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


def research_universe_for(desk: str, snapshot_dir: Path) -> list[str]:
    """The BACKTEST universe: live names plus delisted companies, so research
    sees the firms that died (survivorship-bias mitigation). The equity desk
    gets the delisted pool; biotech delistings lack sector tags, so the pool
    is equity-only for now."""
    base = universe_for(desk, snapshot_dir)
    if desk == "equity":
        return base + [t for t in delisted_pool(snapshot_dir) if t not in base]
    return base
