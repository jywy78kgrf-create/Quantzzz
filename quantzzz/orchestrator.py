"""Continuous orchestrator: refresh data, run research on both desks, run trader
sessions, repeat. All state is in SQLite so the loop is restart-safe."""

from __future__ import annotations

import signal
import time

from .config import FUNDS, Config
from .data.refresh import refresh_data
from .research.loop import ResearchDesk
from .trading.trader import TraderAgent

_STOP = False


def replay(cfg: Config, fund: str, lookback_days: int = 180, step_days: int = 3) -> str:
    """Step a trader through historical snapshot dates to build a realistic track
    record (moving equity curve, closed trades, learning-loop activity)."""
    import pandas as pd
    from .trading.trader import TraderAgent

    agent = TraderAgent.build(cfg, fund)
    # use the benchmark's calendar as the trading-day clock
    bench = agent.store.load_prices("SPY" if fund == "equity" else "XBI")
    if bench is None or bench.empty:
        return f"[{fund}] no benchmark calendar for replay"
    dates = bench.index[bench.index >= bench.index.max() - pd.Timedelta(days=lookback_days)]
    dates = dates[::step_days]
    last = None
    for d in dates:
        last = agent.session(as_of=d)
    return f"[{fund}] replayed {len(dates)} sessions over {lookback_days}d -> {last}"


def _handle_sigint(signum, frame):
    global _STOP
    _STOP = True
    print("\nshutdown requested; finishing current step...")


def _journal_cycle_gap(cfg: Config) -> None:
    """Make scheduler droughts visible: if the previous cycle is much older
    than the market-hours cadence promises, surface it in the decision feed
    (GitHub cron is best-effort and silently skips slots)."""
    from datetime import datetime, timezone
    from .db import get_conn, insert, utcnow
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5 or not (13 <= now.hour <= 21):
        return  # off-hours cadence is intentionally sparse
    conn = get_conn(cfg.db_path)
    try:
        row = conn.execute("SELECT MAX(ts) m FROM equity_snapshots").fetchone()
        if not row or not row["m"]:
            return
        last = datetime.fromisoformat(row["m"].replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        gap_h = (now - last).total_seconds() / 3600
        throttled = conn.execute(
            "SELECT 1 FROM journal_entries WHERE entry_type='advice' AND "
            "action='cycle_gap' AND ts > datetime('now','-6 hours') LIMIT 1").fetchone()
        if gap_h > 3 and not throttled:
            insert(conn, "journal_entries", fund="equity", ts=utcnow(),
                   entry_type="advice", action="cycle_gap",
                   reasoning=(f"Cycle gap: {gap_h:.1f}h since the last session during "
                              "market hours. GitHub cron likely skipped slots; this "
                              "cycle is catching up. Manual 'Run workflow' fills gaps."))
    finally:
        conn.close()


def run_loop(cfg: Config, cycles: int = 0, interval_s: int = 900,
             research_iterations: int = 25) -> None:
    signal.signal(signal.SIGINT, _handle_sigint)
    cycle = 0
    while not _STOP and (cycles == 0 or cycle < cycles):
        cycle += 1
        print(f"\n=== cycle {cycle} ===")
        try:
            _journal_cycle_gap(cfg)
        except Exception as e:
            print(f"cycle-gap check error (non-fatal): {e}")
        try:
            refresh_data(cfg, desk="all")
        except Exception as e:
            print(f"data refresh error (continuing on snapshots): {e}")

        for desk in FUNDS:
            try:
                result = ResearchDesk.build(cfg, desk).run(research_iterations)
                print(result.summary())
            except Exception as e:
                print(f"research {desk} error: {e}")

        for fund in FUNDS:
            try:
                print(TraderAgent.build(cfg, fund).session())
            except Exception as e:
                print(f"trader {fund} error: {e}")

        if _STOP or (cycles and cycle >= cycles):
            break
        print(f"sleeping {interval_s}s...")
        for _ in range(interval_s):
            if _STOP:
                break
            time.sleep(1)
    print("orchestrator stopped.")
