"""Re-anchor the live paper book to each fund's fixed starting budget.

Replay (hindsight) stepped the promoted strategies through past dates and left
its gains inside the tradeable book, so live trading inherited an inflated NAV
(e.g. biotech at ~$2.2M instead of the $1M it started with). Because positions
size as a percentage of equity, the live RETURNS are identical at any scale —
so rescaling the live book down to the starting budget is exact, not a fudge:
the same names at the same weights, just honest dollars.

What is rescaled (per fund, by f = starting_cash / equity-at-go-live):
  - accounts.cash and positions.qty (current book)
  - equity_snapshots.equity / .cash for source='live' (the forward curve)
  - trades.pnl / .qty for source='live'
Ratios (gross/net exposure, drawdown, pnl_pct, per-share prices) are scale-
invariant and left alone. Replay snapshots/trades are demo history and are NOT
rescaled.

Idempotent: a book whose go-live NAV already equals its starting budget is left
untouched, so re-running — or running on a DB that has new live sessions
appended to an already-anchored book — is a no-op.
"""

from __future__ import annotations

import sqlite3

from .db import utcnow

ANCHORED_TOL = 0.01   # within 1% of the starting budget == already anchored


def rebaseline(conn: sqlite3.Connection) -> dict:
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
            "SELECT equity FROM equity_snapshots WHERE fund=? AND source='live' "
            "ORDER BY id LIMIT 1", (fund,)).fetchone()
        if not gl or not gl["equity"]:
            out[fund] = "no live book yet — nothing to anchor"
            continue
        golive = gl["equity"]
        f = start / golive
        if abs(f - 1.0) < ANCHORED_TOL:
            out[fund] = f"already anchored (go-live ${golive:,.0f} ~= ${start:,.0f})"
            continue
        conn.execute("UPDATE accounts SET cash=cash*?, updated_ts=? WHERE fund=?",
                     (f, utcnow(), fund))
        conn.execute("UPDATE positions SET qty=qty*? WHERE fund=?", (f, fund))
        conn.execute("UPDATE equity_snapshots SET equity=equity*?, cash=cash*? "
                     "WHERE fund=? AND source='live'", (f, f, fund))
        conn.execute("UPDATE trades SET pnl=pnl*?, qty=qty*? "
                     "WHERE fund=? AND source='live'", (f, f, fund))
        out[fund] = (f"rescaled live book x{f:.4f}: go-live ${golive:,.0f} -> "
                     f"${start:,.0f}, now anchored to the starting budget")
    conn.commit()
    return out
