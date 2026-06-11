"""Shared trader-desk rendering for both funds."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import CFG, gauge, metric_row, money, q


def render_desk(fund: str) -> None:
    acct = q("SELECT cash, starting_cash FROM accounts WHERE fund=?", (fund,))
    snap = q("SELECT ts, equity, cash, gross_exposure, net_exposure, drawdown "
             "FROM equity_snapshots WHERE fund=? ORDER BY id DESC LIMIT 1", (fund,))
    limits = CFG.risk_limits(fund)

    if acct.empty:
        st.info(f"No trading yet. Run `python -m quantzzz trade --fund {fund}`.")
        return

    equity = snap["equity"].iloc[0] if not snap.empty else acct["cash"].iloc[0]
    cash = acct["cash"].iloc[0]
    ret = equity / acct["starting_cash"].iloc[0] - 1
    metric_row([("Equity", money(equity)), ("Cash", money(cash)),
                ("Return", f"{ret:+.2%}"),
                ("Drawdown", f"{snap['drawdown'].iloc[0]:.1%}" if not snap.empty else "—")])

    # positions
    st.subheader("Positions")
    pos = q("SELECT ticker, qty, avg_cost, strategy_id, stop_px FROM positions "
            "WHERE fund=? AND qty != 0 ORDER BY ticker", (fund,))
    if not pos.empty:
        # mark with last snapshot close via the snapshot store
        from quantzzz.data.snapshots import SnapshotStore
        store = SnapshotStore(CFG.snapshot_dir)
        def last_px(t):
            df = store.load_prices(t)
            return float(df["close"].iloc[-1]) if df is not None and len(df) else None
        pos["last"] = pos["ticker"].map(last_px)
        pos["mkt_value"] = pos["qty"] * pos["last"].fillna(pos["avg_cost"])
        pos["unreal_pnl"] = (pos["last"].fillna(pos["avg_cost"]) - pos["avg_cost"]) * pos["qty"]
        pos["unreal_%"] = (pos["last"].fillna(pos["avg_cost"]) / pos["avg_cost"] - 1)
        st.dataframe(pos.round(3), width='stretch', hide_index=True)
    else:
        st.caption("No open positions.")

    # risk gauges
    st.subheader("Risk")
    g1, g2, g3 = st.columns(3)
    if not snap.empty:
        with g1:
            st.plotly_chart(gauge(snap["gross_exposure"].iloc[0], limits.max_gross_exposure,
                                  "Gross exposure"), width='stretch')
        with g2:
            st.plotly_chart(gauge(abs(snap["drawdown"].iloc[0]), limits.drawdown_halt_pct,
                                  "Drawdown vs halt"), width='stretch')
        with g3:
            n_pos = len(pos)
            st.plotly_chart(gauge(n_pos, limits.max_positions, "Positions vs max"),
                            width='stretch')

    # candidate queue + orders
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Recent orders & fills")
        orders = q("""SELECT o.ts, o.ticker, o.side, o.qty, o.status, o.reject_reason,
                             f.price
                      FROM orders o LEFT JOIN fills f ON f.order_id=o.id
                      WHERE o.fund=? ORDER BY o.id DESC LIMIT 20""", (fund,))
        st.dataframe(orders, width='stretch', hide_index=True)
    with col2:
        st.subheader("Closed trades")
        trades = q("SELECT ticker, entry_px, exit_px, qty, pnl, pnl_pct, exit_reason "
                   "FROM trades WHERE fund=? AND exit_ts IS NOT NULL "
                   "ORDER BY id DESC LIMIT 20", (fund,))
        if not trades.empty:
            st.dataframe(trades.round(3), width='stretch', hide_index=True)
        else:
            st.caption("No closed trades yet.")
