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
                ("Return (incl. replayed history)", f"{ret:+.2%}"),
                ("Drawdown", f"{snap['drawdown'].iloc[0]:.1%}" if not snap.empty else "—")])

    # forward record: live sessions only — the part of the curve that counts
    # as evidence (replayed history re-trades strategies on the data that
    # selected them)
    live = q("SELECT ts, equity, drawdown FROM equity_snapshots "
             "WHERE fund=? AND source='live' ORDER BY id", (fund,))
    if live.empty:
        st.caption("**Forward record:** none yet — starts with the next live "
                   "trading cycle. The return above is replayed history (the "
                   "promoted strategies stepped through past dates), a demo of "
                   "the machinery rather than forward evidence.")
    else:
        fwd_ret = live["equity"].iloc[-1] / live["equity"].iloc[0] - 1
        go_live = pd.to_datetime(live["ts"].iloc[0], format="ISO8601", utc=True)
        metric_row([("Forward record (live only)", f"{fwd_ret:+.2%}"),
                    ("Live since", str(go_live.date())),
                    ("Live sessions", f"{len(live):,}"),
                    ("Forward drawdown", f"{live['drawdown'].iloc[-1]:.1%}")])
        st.caption("The forward record is the referee: it only counts sessions "
                   "traded in real time after promotion, never replayed history.")

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

    # backtest vs live: promised (research) vs delivered (live trades) per strategy
    st.subheader("Backtest vs live — promised vs delivered")
    bvl = q("""
        SELECT s.id, s.family, s.status,
               (SELECT MAX(hit_rate) FROM research_iterations WHERE strategy_id=s.id) bt_hit,
               (SELECT MAX(oos_sharpe) FROM research_iterations WHERE strategy_id=s.id) bt_sharpe,
               COUNT(t.id) live_trades,
               AVG(CASE WHEN t.pnl_pct > 0 THEN 1.0 ELSE 0.0 END) live_hit,
               SUM(t.pnl) live_pnl
        FROM strategies s
        LEFT JOIN trades t ON t.strategy_id = s.id AND t.exit_ts IS NOT NULL
                          AND t.source='live'
        WHERE s.desk=? AND s.status IN ('promoted','retired')
        GROUP BY s.id ORDER BY s.status, s.id""", (fund,))
    if bvl.empty:
        st.caption("No promoted strategies yet.")
    else:
        bvl["bt_hit"] = (bvl["bt_hit"] * 100).round(0)
        bvl["live_hit"] = (bvl["live_hit"] * 100).round(0)
        bvl = bvl.rename(columns={"bt_hit": "backtest_hit_%", "bt_sharpe": "backtest_sharpe",
                                  "live_hit": "live_hit_%", "live_pnl": "live_pnl_$"})
        st.dataframe(bvl.round(2), width='stretch', hide_index=True)
        st.caption("Once a strategy has ≥15 live trades, the learning loop flags it "
                   "if its live hit rate falls >2σ below the backtest promise — "
                   "production overfit detection. Until then this is just the "
                   "promise accumulating its forward verdict.")

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
