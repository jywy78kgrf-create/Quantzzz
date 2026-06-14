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


def refresh_survivorship_pool(cfg: Config, conn, max_names: int = 150) -> dict:
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


def _safe(label: str, fn):
    """Run one refresh step in isolation: a failure prints and is contained,
    so a single throwing source (EDGAR rate-limit, a missing ticker) can never
    abort the steps after it — the options backfill in particular must always
    get its turn to run."""
    try:
        result = fn()
        if result is not None:
            print(f"{label}: {result}")
    except Exception as e:
        print(f"{label}: SKIPPED ({type(e).__name__}: {str(e)[:200]})")


def _edgar_fill(cfg, store, tickers, limit):
    if not cfg.edgar_user_agent:
        return "no EDGAR user agent"
    edgar = EdgarClient(cfg, conn=get_conn(cfg.db_path))
    missing = [t for t in tickers if store.load_json(f"edgar/{t}.json") is None][:limit]
    done = 0
    for t in missing:
        try:
            fund = edgar.fundamental_series(t)
        except Exception:
            continue                       # one bad ticker never stops the rest
        if fund is not None:
            store.save_json(f"edgar/{t}.json", fund)
            done += 1
    return f"{done} fundamentals saved"


def refresh_data(cfg: Config, desk: str = "all") -> None:
    conn = get_conn(cfg.db_path)
    store = SnapshotStore(cfg.snapshot_dir)

    if desk in ("equity", "all"):
        from ..universe import EQUITY_RESEARCH_SEED
        # widen equity breadth: pull the broad liquid pool (~S&P 500), not just
        # the 63-name core. Budget-aware/cached, so it fills the gap over cycles
        # then idles — same pattern as the biotech catalyst-universe pull.
        eq_all = EQUITY_UNIVERSE + EQUITY_RESEARCH_SEED
        _safe("equity prices (expanded universe)",
              lambda: refresh_prices(cfg, eq_all + BENCH_TICKERS, conn))
        _safe("equity premium feeds",
              lambda: refresh_premium_feeds(cfg, eq_all, conn,
                                            options_for=EQUITY_UNIVERSE[:30]))
        _safe("equity edgar", lambda: _edgar_fill(cfg, store, eq_all, 999))

    if desk in ("biotech", "all"):
        from .external_refresh import backfill_options_history, refresh_external_signals
        bpiq = BpiqProvider(cfg, conn, store)
        universe = bpiq.universe()
        print(f"biotech universe: {len(universe)} tickers")
        _safe("biotech catalysts", lambda: (bpiq.catalysts(), bpiq.pdufa_catalysts(),
              [bpiq.historical_catalysts(t) for t in universe[:60]]) and "ok")
        _safe("biotech prices", lambda: refresh_prices(cfg, universe + ["XBI"], conn))
        # widen statistical power: pull prices for every catalyst-event ticker
        # (~776 names / 8k+ events vs the 60-name trading universe). One AV call
        # per name, budget-aware/cached, so it fills the gap fast then idles.
        from ..universe import catalyst_event_tickers
        _safe("catalyst-universe prices (statistical breadth)",
              lambda: refresh_prices(cfg, catalyst_event_tickers(cfg.snapshot_dir), conn))
        # backfill runs EARLY and isolated — the bench's forward evidence is the
        # priority; nothing downstream may starve it of its API budget or abort it.
        # Off-hours (weekends / outside US market hours) there's no live-trading
        # latency to protect, so spend the idle Alpha Vantage budget hard and
        # reach DEEPER into the discovery window for vendor-grade chains; during
        # market hours stay lean and forward-only.
        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc)
        _off_hours = _now.weekday() >= 5 or not (13 <= _now.hour <= 21)
        # max_seconds bounds the backfill well inside the 90-min cycle cap so the
        # research + trading steps that follow always get to run, and the CI run
        # finishes "success" instead of being cancelled at the timeout. Progress
        # is durable (fetched days persist), so the deep pull resumes next cycle.
        _bf = dict(max_calls=20000, since="2024-01-01", max_seconds=2400) if _off_hours \
            else dict(max_calls=3000, since="2026-05-11", max_seconds=600)
        _safe(f"options history backfill ({'deep/off-hours' if _off_hours else 'forward'})",
              lambda: backfill_options_history(cfg, conn, **_bf))
        _safe("biotech premium feeds",
              lambda: refresh_premium_feeds(cfg, universe, conn, options_for=universe))
        _safe("biotech edgar insider", lambda: _edgar_fill(cfg, store, universe, 10))
        _safe("external signal extension", lambda: refresh_external_signals(cfg))
        _safe("biotech survivorship pool",
              lambda: refresh_biotech_survivorship_pool(cfg, conn))

    if desk == "all":
        _safe("survivorship pool", lambda: refresh_survivorship_pool(cfg, conn))
        _safe("earnings calendar", lambda: refresh_earnings_calendar(cfg, conn))

    conn.close()
