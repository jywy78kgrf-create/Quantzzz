"""Data refresh: populate price snapshots, EDGAR extracts, and BPIQ data.

Budget-aware — Alpha Vantage calls are capped by the persisted daily budget, so
this can be run repeatedly across days to fill the snapshot bundle without
exceeding the unknown rate tier.
"""

from __future__ import annotations

from ..config import Config
from ..db import get_conn
from ..universe import BENCH_TICKERS, EQUITY_UNIVERSE
from .alphavantage import AlphaVantageClient
from .bpiq import BpiqProvider
from .edgar import EdgarClient
from .snapshots import SnapshotStore


def refresh_prices(cfg: Config, tickers: list[str], conn) -> dict:
    store = SnapshotStore(cfg.snapshot_dir)
    av = AlphaVantageClient(cfg, conn, store)
    fetched, cached, skipped = 0, 0, 0
    for t in tickers:
        if store.load_prices(t) is not None and av.cache.get(f"av:daily:{t}") is not None:
            cached += 1
            continue
        if av.budget.remaining() <= 0 and store.load_prices(t) is None:
            skipped += 1
            continue
        df = av.daily_adjusted(t)
        if df is not None:
            fetched += 1
        else:
            skipped += 1
    return {"fetched": fetched, "cached": cached, "skipped": skipped,
            "budget_left": av.budget.remaining()}


def refresh_premium_feeds(cfg: Config, tickers: list[str], conn,
                          options_for: list[str] | None = None) -> dict:
    """Earnings surprises + news sentiment for the universe; options summaries
    for a subset (held names / leaders). All budget-aware and cached."""
    store = SnapshotStore(cfg.snapshot_dir)
    av = AlphaVantageClient(cfg, conn, store)
    counts = {"earnings": 0, "news": 0, "options": 0}
    for t in tickers:
        if av.earnings_surprises(t):
            counts["earnings"] += 1
        if av.news_sentiment(t):
            counts["news"] += 1
    for t in (options_for or [])[:30]:
        if av.options_summary(t):
            counts["options"] += 1
    return counts


def refresh_survivorship_pool(cfg: Config, conn, max_names: int = 40) -> dict:
    """Build a pool of DELISTED stocks with price history so backtests include
    companies that died — directly attacking survivorship bias.

    Selection: long-lived NYSE/NASDAQ common stocks delisted within the backtest
    era. Their price series simply end at delisting; strategies holding them ride
    the decline like a real portfolio would have.
    """
    store = SnapshotStore(cfg.snapshot_dir)
    av = AlphaVantageClient(cfg, conn, store)
    rows = av.listing_status("delisted")
    pool = [
        r for r in rows
        if r.get("assetType") == "Stock"
        and r.get("exchange") in ("NYSE", "NASDAQ")
        and (r.get("delistingDate") or "") >= "2019-01-01"
        and (r.get("ipoDate") or "9999") <= "2016-01-01"
        and "-" not in r.get("symbol", "-")          # skip warrants/units/when-issued
        and "." not in r.get("symbol", ".")
    ]
    # oldest listings first: long histories, were real index-grade companies
    pool.sort(key=lambda r: r.get("ipoDate") or "9999")
    selected = pool[:max_names]
    fetched = 0
    for r in selected:
        t = r["symbol"]
        if store.load_prices(t) is None:
            if av.daily_adjusted(t) is not None:
                fetched += 1
    meta = []
    for r in selected:
        px = store.load_prices(r["symbol"])
        if px is not None and len(px) >= 250:   # drop reused-ticker stubs
            meta.append({"ticker": r["symbol"], "name": r["name"],
                         "delistingDate": r["delistingDate"], "ipoDate": r["ipoDate"]})
    store.save_json("delisted.json", meta)
    return {"candidates": len(pool), "selected": len(selected),
            "with_history": len(meta), "newly_fetched": fetched}


def refresh_earnings_calendar(cfg: Config, conn) -> dict:
    """Upcoming report dates for our universes -> snapshot for the traders."""
    store = SnapshotStore(cfg.snapshot_dir)
    av = AlphaVantageClient(cfg, conn, store)
    from .bpiq import BpiqProvider
    universe = set(EQUITY_UNIVERSE)
    bpiq_uni = store.load_json("bpiq/universe.json") or []
    universe.update(bpiq_uni)
    rows = av.earnings_calendar()
    ours = [
        {"ticker": r["symbol"], "reportDate": r["reportDate"],
         "estimate": r.get("estimate") or None, "time": r.get("timeOfTheDay")}
        for r in rows if r.get("symbol") in universe and r.get("reportDate")
    ]
    store.save_json("av_earnings_calendar.json", ours)
    return {"total": len(rows), "in_universe": len(ours)}


def refresh_data(cfg: Config, desk: str = "all") -> None:
    conn = get_conn(cfg.db_path)
    store = SnapshotStore(cfg.snapshot_dir)

    if desk in ("equity", "all"):
        tickers = EQUITY_UNIVERSE + BENCH_TICKERS
        print("equity prices:", refresh_prices(cfg, tickers, conn))
        print("equity premium feeds:",
              refresh_premium_feeds(cfg, EQUITY_UNIVERSE, conn,
                                    options_for=EQUITY_UNIVERSE[:30]))
        if cfg.edgar_user_agent:
            edgar = EdgarClient(cfg, conn)
            done = 0
            for t in EQUITY_UNIVERSE:
                if store.load_json(f"edgar/{t}.json") is not None:
                    continue
                fund = edgar.fundamental_series(t)
                if fund is not None:
                    store.save_json(f"edgar/{t}.json", fund)
                    done += 1
            print(f"edgar fundamentals saved: {done}")

    if desk in ("biotech", "all"):
        bpiq = BpiqProvider(cfg, conn, store)
        universe = bpiq.universe()
        print(f"biotech universe: {len(universe)} tickers")
        bpiq.catalysts()
        bpiq.pdufa_catalysts()
        for t in universe[:20]:
            bpiq.historical_catalysts(t)
        print("biotech prices:", refresh_prices(cfg, universe + ["XBI"], conn))
        print("biotech premium feeds:",
              refresh_premium_feeds(cfg, universe, conn, options_for=universe[:20]))

    if desk == "all":
        print("survivorship pool:", refresh_survivorship_pool(cfg, conn))
        print("earnings calendar:", refresh_earnings_calendar(cfg, conn))

    conn.close()
