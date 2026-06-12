"""Live paper trading — the forward record, isolated from replayed history.

Everything on this page is source='live': sessions traded in real time after
promotion. This is the referee's scoreboard; replayed history never appears
here.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import COLORS, header, metric_row, money, q

header("🔴 Live Trading — Forward Record",
       "Real-time paper sessions only · replayed history excluded")

live = {f: q("SELECT ts, equity, gross_exposure, drawdown FROM equity_snapshots "
             "WHERE fund=? AND source='live' ORDER BY ts", (f,))
        for f in ("equity", "biotech")}

if all(df.empty for df in live.values()):
    st.info("No live sessions recorded yet — the forward record starts with the "
            "next automated fund cycle. Everything on the other pages dated "
            "before go-live is replayed history.")
    st.stop()

# ---- headline: per-fund forward record ----
for fund in ("equity", "biotech"):
    df = live[fund]
    st.subheader(f"{'📈' if fund == 'equity' else '🧬'} {fund.title()} fund")
    if df.empty:
        st.caption("No live sessions yet for this fund.")
        continue
    start_eq, last_eq = df["equity"].iloc[0], df["equity"].iloc[-1]
    go_live = pd.to_datetime(df["ts"].iloc[0], format="ISO8601", utc=True)
    metric_row([
        ("Forward return", f"{last_eq / start_eq - 1:+.2%}"),
        ("Live equity", money(last_eq)),
        ("Go-live baseline", money(start_eq)),
        ("Live since", str(go_live.date())),
        ("Sessions", f"{len(df):,}"),
    ])

# ---- live equity curves, rebased to 100 at go-live ----
fig = go.Figure()
for fund, df in live.items():
    if df.empty:
        continue
    rebased = df["equity"] / df["equity"].iloc[0] * 100
    fig.add_trace(go.Scatter(
        x=pd.to_datetime(df["ts"], format="ISO8601", utc=True), y=rebased,
        name=fund.title(), mode="lines+markers",
        line=dict(color=COLORS.get(fund, "#888"), width=2)))
fig.add_hline(y=100, line_dash="dot", line_color="#9ca3af")
fig.update_layout(title="Forward equity (rebased to 100 at go-live)",
                  height=340, template="plotly_white",
                  margin=dict(l=10, r=10, t=40, b=10),
                  legend=dict(orientation="h"))
st.plotly_chart(fig, width='stretch')
st.caption("This curve starts at go-live and only ever extends in real time. "
           "It is the evidence the learning loop and the contaminated-discovery "
           "policy defer to — strategies keep their place by earning it here.")

# ---- live trades & orders ----
col1, col2 = st.columns(2)
with col1:
    st.subheader("Live trades")
    trades = q("SELECT fund, ticker, entry_ts, exit_ts, entry_px, exit_px, qty, "
               "pnl, pnl_pct, exit_reason FROM trades WHERE source='live' "
               "ORDER BY id DESC LIMIT 50")
    if not trades.empty:
        st.dataframe(trades.round(3), width='stretch', hide_index=True)
    else:
        st.caption("No trades opened in the live era yet — the rebalancer only "
                   "trades when target weights drift from holdings.")
with col2:
    st.subheader("Orders since go-live")
    first_live = min(df["ts"].iloc[0] for df in live.values() if not df.empty)
    orders = q("""SELECT o.fund, o.ts, o.ticker, o.side, o.qty, o.status,
                         f.price
                  FROM orders o LEFT JOIN fills f ON f.order_id=o.id
                  WHERE o.ts >= ? ORDER BY o.id DESC LIMIT 50""", (first_live,))
    if not orders.empty:
        st.dataframe(orders, width='stretch', hide_index=True)
    else:
        st.caption("No orders since go-live yet.")

# ---- live sessions log ----
st.subheader("Session log")
rows = []
for fund, df in live.items():
    for _, r in df.iterrows():
        rows.append({"ts": r["ts"], "fund": fund, "equity": round(r["equity"], 2),
                     "gross": f"{r['gross_exposure']:.0%}",
                     "drawdown": f"{r['drawdown']:.1%}"})
log = pd.DataFrame(rows).sort_values("ts", ascending=False)
st.dataframe(log, width='stretch', hide_index=True, height=240)
