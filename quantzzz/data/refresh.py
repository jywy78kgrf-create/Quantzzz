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
    for t in (options_for or [])[:120]:
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
    if not rows:
        # offline / no key: never clobber the committed pool with emptiness
        existing = store.load_json("delisted.json") or []
        return {"skipped": "no listing data; kept existing pool",
                "with_history": len(existing)}
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


def refresh_biotech_survivorship_pool(cfg: Config, conn) -> dict:
    """Dead biotechs for the biotech research universe.

    Biotech is the sector where survivorship bias bites hardest: failed
    readouts end in -80% delistings that a survivors-only history simply never
    shows. Candidates come from the curated seed (known 2020-2024 exits, both
    bankruptcies and acquisitions); price history is fetched budget-aware and
    only names with a real series (>=250 days) enter the pool."""
    from ..universe import BIOTECH_DELISTED_SEED
    store = SnapshotStore(cfg.snapshot_dir)
    av = AlphaVantageClient(cfg, conn, store)
    fetched = 0
    for r in BIOTECH_DELISTED_SEED:
        t = r["ticker"]
        if store.load_prices(t) is None and av.budget.remaining() > 0:
            if av.daily_adjusted(t) is not None:
                fetched += 1
    meta = []
    for r in BIOTECH_DELISTED_SEED:
        px = store.load_prices(r["ticker"])
        if px is not None and len(px) >= 250:
            meta.append(r)
    if meta or not (cfg.snapshot_dir / "delisted_biotech.json").exists():
        store.save_json("delisted_biotech.json", meta)
    return {"candidates": len(BIOTECH_DELISTED_SEED),
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
    if not rows:
        existing = store.load_json("av_earnings_calendar.json") or []
        return {"skipped": "no calendar data; kept existing", "in_universe": len(existing)}
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
        for t in universe[:60]:
            bpiq.historical_catalysts(t)          # cached; fills over cycles
        print("biotech prices:", refresh_prices(cfg, universe + ["XBI"], conn))
        print("biotech premium feeds:",
              refresh_premium_feeds(cfg, universe, conn, options_for=universe))
        if cfg.edgar_user_agent:
            # insider (Form 4) coverage feeds the external insider signals;
            # fill a few missing names per cycle to respect SEC pacing
            edgar = EdgarClient(cfg, conn)
            missing = [t for t in universe
                       if store.load_json(f"edgar/{t}.json") is None][:10]
            done = 0
            for t in missing:
                fund = edgar.fundamental_series(t)
                if fund is not None:
                    store.save_json(f"edgar/{t}.json", fund)
                    done += 1
            if done:
                print(f"biotech edgar fundamentals saved: {done}")
        from .external_refresh import backfill_options_history, refresh_external_signals
        print("options history backfill:",
              backfill_options_history(cfg, conn, max_calls=4000))
        print("external signal extension:", refresh_external_signals(cfg))
        print("biotech survivorship pool:",
              refresh_biotech_survivorship_pool(cfg, conn))

    if desk == "all":
        print("survivorship pool:", refresh_survivorship_pool(cfg, conn))
        print("earnings calendar:", refresh_earnings_calendar(cfg, conn))

    conn.close()
