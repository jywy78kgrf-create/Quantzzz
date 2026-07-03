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

# Index / sector / commodity ETFs whose OPTIONS greeks we ingest (meridian
# desk). We pull their PRICES here (AlphaVantage serves ETFs like equities) so
# the options-vol signals have an underlying to compute realized vol / regime
# against. Data-only: kept out of the single-stock trading universe so the
# cross-sectional stock families never rank an ETF against a stock.
OPTIONS_VOL_ETFS = [
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO",                       # broad index
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLP", "XLU", "XLB",         # sectors
    "XLRE", "XLC", "XOP", "KRE", "SMH", "ITA", "IBB",
    "GLD", "SLV", "USO", "TLT", "HYG", "LQD", "UNG", "DBC",         # commodity/rates
]

# Volatility-regime indices, fetched via AlphaVantage INDEX_DATA (not the equity
# TIME_SERIES path). VIX (30d) vs VIX3M (3-month) is the term-structure signal —
# contango (ratio < 1) = calm, backwardation (> 1) = stress; VIX9D adds the
# near-term/event slope, VVIX the vol-of-vol fragility, SKEW the tail-hedging
# demand. Nothing trades these — they feed a market-level regime feature only.
VOL_INDEX_SYMBOLS = ["VIX", "VIX3M", "VIX9D", "VVIX", "SKEW"]

# Broad liquid US large/mid-cap pool (~S&P 500) so the equity desk has real
# breadth to find edges in, not just the 63-name core. Names are price-gated
# into the universe — they only enter once their history has been pulled (same
# pattern as the biotech catalyst universe), so this can be added before the
# data backfill catches up.
EQUITY_RESEARCH_SEED = [
    # semis / hardware
    "ADI", "AMAT", "LRCX", "KLAC", "MRVL", "NXPI", "MCHP", "ON", "MPWR", "SWKS",
    "QRVO", "TER", "KEYS", "GLW", "STX", "WDC", "NTAP", "HPQ", "DELL", "HPE",
    "ANET", "CSCO", "JNPR", "FFIV", "ZBRA", "MSI", "SMCI", "GFS", "ENPH", "FSLR",
    # software / internet / fintech
    "INTU", "ADSK", "ANSS", "CDNS", "SNPS", "ROP", "PTC", "TYL", "FICO", "WDAY",
    "TEAM", "PANW", "FTNT", "CRWD", "ZS", "DDOG", "SNOW", "NET", "MDB", "PLTR",
    "GDDY", "AKAM", "VRSN", "CTSH", "ACN", "IBM", "IT", "EPAM", "PAYX", "ADP",
    "FI", "FIS", "GPN", "PYPL", "MSCI", "SPGI", "MCO", "ICE", "CME", "NDAQ", "CBOE",
    # comms / media
    "GOOG", "TMUS", "CHTR", "WBD", "PARA", "FOXA", "OMC", "IPG", "EA", "TTWO",
    "MTCH", "PINS", "SNAP", "RBLX", "SPOT", "TTD", "LYV",
    # consumer discretionary
    "TSLA", "LOW", "BKNG", "ABNB", "MAR", "HLT", "RCL", "CCL", "NCLH", "YUM",
    "CMG", "DRI", "ORLY", "AZO", "ROST", "TJX", "LULU", "DECK", "DG", "DLTR",
    "BBY", "EBAY", "ETSY", "F", "GM", "APTV", "GPC", "LEN", "DHI", "PHM", "NVR",
    "MGM", "LVS", "WYNN", "EXPE", "DPZ", "GRMN", "POOL", "TSCO", "ULTA", "BBWI",
    # consumer staples
    "CL", "KMB", "GIS", "K", "HSY", "MDLZ", "MNST", "KDP", "STZ", "TAP", "KHC",
    "SYY", "ADM", "KR", "WBA", "EL", "CLX", "CHD", "MKC", "CAG", "CPB", "HRL",
    "TSN", "KVUE",
    # healthcare
    "ISRG", "SYK", "BSX", "MDT", "EW", "ZBH", "BDX", "BAX", "RMD", "IDXX", "IQV",
    "A", "MTD", "WAT", "DGX", "LH", "HCA", "CI", "CVS", "HUM", "CNC", "ELV",
    "MCK", "COR", "CAH", "DXCM", "ALGN", "HOLX", "STE", "COO", "PODD", "GEHC",
    "VRTX", "REGN", "GILD", "BIIB", "MRNA",
    # financials
    "C", "USB", "PNC", "TFC", "COF", "BK", "STT", "TROW", "AMP", "DFS", "SYF",
    "AIG", "MET", "PRU", "AFL", "TRV", "ALL", "PGR", "CB", "HIG", "CINF", "WRB",
    "MMC", "AON", "AJG", "BRO", "FITB", "HBAN", "RF", "KEY", "CFG", "MTB", "NTRS",
    # industrials
    "MMM", "GD", "LMT", "RTX", "NOC", "EMR", "ETN", "PH", "ITW", "ROK", "AME",
    "DOV", "IR", "XYL", "FTV", "OTIS", "CARR", "JCI", "TT", "CMI", "PCAR", "FAST",
    "GWW", "URI", "UPS", "FDX", "CSX", "NSC", "LUV", "DAL", "UAL", "WM", "RSG",
    "GNRC", "PWR", "HUBB", "PNR", "AOS", "DAY",
    # energy
    "EOG", "OXY", "PSX", "VLO", "MPC", "KMI", "WMB", "OKE", "HES", "DVN", "FANG",
    "HAL", "BKR", "CTRA", "APA", "TRGP", "LNG",
    # materials
    "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "NUE", "STLD", "DOW", "DD", "PPG",
    "VMC", "MLM", "IP", "BALL", "ALB", "CF", "MOS", "CTVA", "IFF",
    # utilities
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL", "PEG", "ED", "WEC", "ES",
    "EIX", "PCG", "AEE", "DTE", "FE", "ETR", "CMS", "CNP", "PPL", "ATO",
    # real estate
    "AMT", "PLD", "CCI", "EQIX", "PSA", "O", "SPG", "WELL", "DLR", "VICI", "AVB",
    "EQR", "EXR", "MAA", "INVH", "ARE", "VTR", "SBAC", "CBRE", "WY",
    # ---- mid-cap / growth tier: more cross-sectional dispersion than the
    # mega-cap core, where the momentum edges are already mined out. All
    # price-gated, so thin/short-history names are filtered automatically.
    "DKNG", "COIN", "HOOD", "SOFI", "AFRM", "UPST", "RIVN", "LCID", "U", "PATH",
    "DASH", "ROKU", "CVNA", "W", "CHWY", "RH", "DKS", "BURL", "FIVE", "BLDR",
    "OC", "MAS", "WMS", "TREX", "BLD", "EME", "MTZ", "FIX", "BWXT", "CW",
    "EXAS", "NTRA", "HIMS", "DOCS", "GH", "PEN", "INSP", "SHC", "BRKR", "RGEN",
    "TECH", "BIO", "MEDP", "HQY", "MOH", "GTLB", "S", "DOCN", "CART", "TOST",
]


def equity_research_tickers(snapshot_dir: Path) -> list[str]:
    """The broad equity pool, price-gated to names we have history for."""
    return [t for t in EQUITY_RESEARCH_SEED if _has_price(snapshot_dir, t)]


def biotech_universe(snapshot_dir: Path) -> list[str]:
    """Universe from the BPIQ companies snapshot, else the curated seed."""
    path = snapshot_dir / "bpiq" / "universe.json"
    if path.exists():
        tickers = json.loads(path.read_text())
        if tickers:
            return tickers
    return list(BIOTECH_SEED)


# ---- small-cap (<$10) biotech sub-desk ------------------------------------
SMALLCAP_MAX_PRICE = 10.0           # the "under $10" band
SMALLCAP_MIN_DOLLAR_VOL = 250_000   # liquidity floor: keep the daily-bar backtest
                                    # from promoting names too thin to actually fill
                                    # in size (the #1 trap in sub-$10 biotech)


def _price_liquidity(snapshot_dir: Path, ticker: str):
    """(latest close, median daily dollar-volume over last ~60 sessions, last
    price date), or None when there's no usable price history."""
    path = snapshot_dir / "prices" / f"{ticker}.parquet"
    if not path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(path).tail(60)
    except Exception:
        return None
    if df.empty or "close" not in df:
        return None
    last = float(df["close"].iloc[-1])
    dollar_vol = float((df["close"] * df["volume"]).median()) if "volume" in df else 0.0
    return last, dollar_vol, df.index.max()


def smallcap_biotech_filter(snapshot_dir: Path, names: list[str],
                            require_fresh_days: int | None = None) -> list[str]:
    """Keep only the sub-$10, liquid-enough small-cap biotech names.

    require_fresh_days gates on recency (the live book must not hold names that
    stopped trading); left None for research, which deliberately keeps the dead
    sub-$10 tail for survivorship honesty."""
    import pandas as pd
    today = pd.Timestamp(pd.Timestamp.now("UTC").date())
    out = []
    for t in names:
        pl = _price_liquidity(snapshot_dir, t)
        if pl is None:
            continue
        price, dvol, last_date = pl
        if not (0 < price < SMALLCAP_MAX_PRICE and dvol >= SMALLCAP_MIN_DOLLAR_VOL):
            continue
        if require_fresh_days is not None and (today - last_date).days > require_fresh_days:
            continue                          # stale price -> not currently tradeable
        out.append(t)
    return out


def universe_for(desk: str, snapshot_dir: Path) -> list[str]:
    """The LIVE/tradeable universe (active names only)."""
    if desk == "equity":
        dead = set(delisted_pool(snapshot_dir))           # never trade a dead name live
        out, seen = list(EQUITY_UNIVERSE), set(EQUITY_UNIVERSE)
        for t in equity_research_tickers(snapshot_dir):   # broad pool, price-gated
            if t not in seen and t not in dead:
                out.append(t)
                seen.add(t)
        return out
    if desk == "biotech":
        return biotech_universe(snapshot_dir)
    if desk == "biotech_smallcap":
        # widen beyond the BPIQ-tracked (mostly >$10) names to the active
        # catalyst-event small-caps; exclude known-dead names and require a
        # fresh price so the live book only trades names actually trading now.
        dead = set(delisted_biotech_pool(snapshot_dir))
        cands = list(dict.fromkeys(
            biotech_universe(snapshot_dir) + catalyst_event_tickers(snapshot_dir)))
        cands = [t for t in cands if t not in dead]
        return smallcap_biotech_filter(snapshot_dir, cands, require_fresh_days=15)
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
    # 2023 biotech bankruptcy wave (a 10-year record) plus recent failures —
    # clinical-stage names that went to zero, the exact survivorship tail a
    # survivors-only history hides. Sourced from public bankruptcy/delisting
    # records; carried as candidates and price-gated like the rest.
    {"ticker": "SRNE", "name": "Sorrento Therapeutics", "exit": "bankruptcy 2023"},
    {"ticker": "HGEN", "name": "Humanigen", "exit": "bankruptcy 2024"},
    {"ticker": "ACOR", "name": "Acorda Therapeutics", "exit": "bankruptcy 2024"},
    {"ticker": "RUBY", "name": "Rubius Therapeutics", "exit": "wind-down 2023"},
    {"ticker": "NMTR", "name": "9 Meters Biopharma", "exit": "wind-down 2023"},
    {"ticker": "INFI", "name": "Infinity Pharmaceuticals", "exit": "wind-down 2023"},
    {"ticker": "KLDO", "name": "Kaleido Biosciences", "exit": "shutdown 2023"},
    {"ticker": "NOVN", "name": "Novan", "exit": "bankruptcy 2023"},
    {"ticker": "STAB", "name": "Statera Biopharma", "exit": "bankruptcy 2023"},
    {"ticker": "BIOC", "name": "Biocept", "exit": "Chapter 7 2023"},
    {"ticker": "IOBT", "name": "IO Biotech", "exit": "Chapter 7 2026 (Phase 3 miss)"},
]


def delisted_biotech_pool(snapshot_dir: Path) -> list[str]:
    path = snapshot_dir / "delisted_biotech.json"
    if path.exists():
        return [m["ticker"] for m in json.loads(path.read_text())]
    return []


def catalyst_event_tickers(snapshot_dir: Path) -> list[str]:
    """Every ticker carrying a pinned catalyst event (export + live extension).

    The catalyst calendar spans ~776 tickers / 8k+ events, but research only
    backtests the names it has price history for. Widening the research
    universe to these names is the single biggest lever on statistical power:
    the event-anchored / PDUFA / drift families are only as well-estimated as
    the number of independent events behind them.
    """
    import csv
    tickers: set[str] = set()
    for fn in ("catalyst_events_export.csv", "catalyst_events_live.csv"):
        path = snapshot_dir / "external" / fn
        if not path.exists():
            continue
        try:
            with path.open(newline="") as fh:
                for row in csv.DictReader(fh):
                    t = (row.get("ticker") or "").strip()
                    if t and (row.get("catalyst_date") or "").strip():
                        tickers.add(t)
        except (OSError, csv.Error):
            continue
    return sorted(tickers)


def _has_price(snapshot_dir: Path, ticker: str) -> bool:
    return (snapshot_dir / "prices" / f"{ticker}.parquet").exists()


def research_universe_for(desk: str, snapshot_dir: Path) -> list[str]:
    """The BACKTEST universe: live names plus delisted companies, so research
    sees the firms that died (survivorship-bias mitigation). Equity draws on
    the generic delisted pool; biotech on the curated dead-biotech pool PLUS
    every catalyst-event ticker we have price history for — research broad
    (statistical power), trade focused (the liquid live universe)."""
    if desk == "biotech_smallcap":
        # the full biotech research universe (live + dead + catalyst names),
        # filtered to the sub-$10 small-cap band — survivorship-honest, so the
        # dead sub-$10 biotechs (the failure tail this space is full of) stay in.
        return smallcap_biotech_filter(
            snapshot_dir, research_universe_for("biotech", snapshot_dir))
    base = universe_for(desk, snapshot_dir)
    if desk == "equity":
        return base + [t for t in delisted_pool(snapshot_dir) if t not in base]
    if desk == "biotech":
        out = list(base)
        seen = set(base)
        # curated dead biotechs: unconditional (carried as candidates until the
        # data provider serves their history)
        for t in delisted_biotech_pool(snapshot_dir):
            if t not in seen:
                out.append(t)
                seen.add(t)
        # catalyst-event tickers: price-gated so the universe only grows with
        # names that actually contribute backtestable events
        for t in catalyst_event_tickers(snapshot_dir):
            if t not in seen and _has_price(snapshot_dir, t):
                out.append(t)
                seen.add(t)
        return out
    return base
