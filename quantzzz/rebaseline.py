"""Re-anchor the live paper book to each fund's fixed starting budget.

Replay (hindsight) stepped the promoted strategies through past dates and left
its gains inside the tradeable book, so live trading inherited an inflated NAV
(e.g. biotech at ~$2.2M instead of the $1M it started with) AND the holdings it
established carried replay-era cost bases (a name bought in the replay at 2025
prices shows a 2025 entry and a hindsight gain). Re-baselining fixes both:

1. NAV anchor — rescale the live book by f = starting_cash / equity-at-go-live
   so go-live == the starting budget. Exact, not a fudge: positions size as a %
   of equity, so the live RETURNS are identical at any scale.
       accounts.cash, positions.qty, equity_snapshots.equity/.cash (live),
       trades.pnl/.qty (live).

2. Mark-to-go-live — re-mark each holding established before go-live to its
   go-live price (and date), so the book reads as a clean forward book: entry =
   go-live, P&L = forward-only, with the replay holding period dropped. This is
   standard portfolio re-baselining (mark holdings to market at the baseline
   date), not fabrication.

Ratios (gross/net exposure, drawdown, pnl_pct, per-share prices) are scale-
invariant. Replay snapshots/trades stay as tagged demo history.

Idempotent: an already-anchored NAV is left untouched, and a holding already
marked at go-live is skipped — so re-running, or running on a DB with new live
sessions appended, is a no-op.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .db import utcnow

ANCHORED_TOL = 0.01   # within 1% of the starting budget == already anchored


def _golive_price(store, ticker: str, golive_date: str):
    """Close on or before the go-live date, for marking a holding to go-live."""
    if store is None:
        return None
    df = store.load_prices(ticker)
    if df is None or "close" not in df or not len(df):
        return None
    import pandas as pd
    cut = df.loc[df.index <= pd.Timestamp(golive_date), "close"]
    return float(cut.iloc[-1]) if len(cut) else None


def rebaseline(conn: sqlite3.Connection, snapshot_dir: Path | None = None) -> dict:
    store = None
    if snapshot_dir is not None:
        from .data.snapshots import SnapshotStore
        store = SnapshotStore(snapshot_dir)

    out: dict[str, str] = {}
    funds = [r["fund"] for r in conn.execute("SELECT DISTINCT fund FROM accounts")]
    for fund in funds:
        acct = conn.execute(
            "SELECT cash, starting_cash FROM accounts WHERE fund=?", (fund,)).fetchone()
        if not acct or not acct["starting_cash"]:
            out[fund] = "no account / starting budget"
            continue
        start = acct["starting_cash"]
        gl = conn.execute(
            "SELECT ts, equity FROM equity_snapshots WHERE fund=? AND source='live' "
            "ORDER BY id LIMIT 1", (fund,)).fetchone()
        if not gl or not gl["equity"]:
            out[fund] = "no live book yet — nothing to anchor"
            continue
        golive, golive_ts = gl["equity"], gl["ts"]
        golive_date = golive_ts[:10]
        notes: list[str] = []

        # 1. NAV anchor (once, when not already anchored)
        f = start / golive
        if abs(f - 1.0) >= ANCHORED_TOL:
            conn.execute("UPDATE accounts SET cash=cash*?, updated_ts=? WHERE fund=?",
                         (f, utcnow(), fund))
            conn.execute("UPDATE positions SET qty=qty*? WHERE fund=?", (f, fund))
            conn.execute("UPDATE equity_snapshots SET equity=equity*?, cash=cash*? "
                         "WHERE fund=? AND source='live'", (f, f, fund))
            conn.execute("UPDATE trades SET pnl=pnl*?, qty=qty*? "
                         "WHERE fund=? AND source='live'", (f, f, fund))
            # the high-water mark must move with the rescale, or the drawdown
            # (equity - hwm)/hwm compares two scales and reads a phantom crash
            # that false-triggers the risk halts
            conn.execute("UPDATE fund_state SET hwm=hwm*? WHERE fund=?", (f, fund))
            notes.append(f"NAV rescaled x{f:.4f} (go-live ${golive:,.0f} -> ${start:,.0f})")
        else:
            notes.append(f"NAV already anchored (${golive:,.0f})")

        # 2. Mark holdings established before go-live to their go-live price, so
        #    the book is forward-only. Holdings opened in the live era keep their
        #    real entry. Idempotent: a holding already dated at go-live is skipped.
        marked = skipped_no_px = 0
        if store is not None:
            pos = conn.execute(
                "SELECT ticker, opened_ts FROM positions WHERE fund=? AND qty!=0",
                (fund,)).fetchall()
            for p in pos:
                opened = (p["opened_ts"] or "")[:10]
                if not opened or opened >= golive_date:
                    continue                         # live-era entry: keep as-is
                gp = _golive_price(store, p["ticker"], golive_date)
                if gp is None:
                    skipped_no_px += 1
                    continue
                conn.execute(
                    "UPDATE positions SET avg_cost=?, opened_ts=? WHERE fund=? AND ticker=?",
                    (gp, golive_ts, fund, p["ticker"]))
                marked += 1
            if marked:
                notes.append(f"marked {marked} holdings to go-live ({golive_date}), "
                             f"P&L now forward-only")
            if skipped_no_px:
                notes.append(f"{skipped_no_px} holdings left as-is (no price at go-live)")

        out[fund] = "; ".join(notes)
    conn.commit()
    return out
