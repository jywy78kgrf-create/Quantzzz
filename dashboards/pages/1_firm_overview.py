"""Firm-wide overview: both funds' equity, P&L, exposure, drawdown."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import CFG, equity_curve_fig, header, metric_row, money, q

header("🏦 Quantzzz Capital", "Two autonomous quant funds · equity & biotech")

funds = {}
for fund in ("equity", "biotech"):
    funds[fund] = q("SELECT ts, equity, cash, gross_exposure, net_exposure, drawdown "
                    "FROM equity_snapshots WHERE fund=? ORDER BY ts", (fund,))

cards = []
total_equity = 0.0
for fund in ("equity", "biotech"):
    df = funds[fund]
    if df.empty:
        cards.append((f"{fund.title()} equity", "—"))
        continue
    eq = df["equity"].iloc[-1]
    total_equity += eq
    ret = eq / CFG.starting_cash - 1
    cards.append((f"{fund.title()} equity", f"{money(eq)}  ({ret:+.1%})"))
cards.insert(0, ("Total AUM", money(total_equity) if total_equity else "—"))
metric_row(cards)

st.plotly_chart(equity_curve_fig(funds, "Equity curves"), width='stretch')

col1, col2 = st.columns(2)
with col1:
    st.subheader("Exposure")
    rows = []
    for fund in ("equity", "biotech"):
        df = funds[fund]
        if not df.empty:
            rows.append({"Fund": fund.title(),
                         "Gross": f"{df['gross_exposure'].iloc[-1]:.0%}",
                         "Net": f"{df['net_exposure'].iloc[-1]:.0%}",
                         "Drawdown": f"{df['drawdown'].iloc[-1]:.1%}"})
    st.dataframe(pd.DataFrame(rows), width='stretch', hide_index=True)

    states = q("SELECT fund, mode, hwm FROM fund_state")
    for _, r in states.iterrows():
        badge = "🟢 normal" if r["mode"] == "normal" else "🔴 liquidate-only"
        st.write(f"**{r['fund'].title()}**: {badge}")

with col2:
    st.subheader("Strategy pipeline")
    pipe = q("SELECT desk, status, COUNT(*) n FROM strategies GROUP BY desk, status")
    if not pipe.empty:
        pivot = pipe.pivot(index="desk", columns="status", values="n").fillna(0).astype(int)
        st.dataframe(pivot, width='stretch')
    promoted = q("SELECT COUNT(*) n FROM strategies WHERE status='promoted'")
    st.metric("Promoted strategies (live)", int(promoted["n"].iloc[0]) if not promoted.empty else 0)

st.subheader("Recent activity")
act = q("SELECT ts, fund, entry_type, ticker, reasoning FROM journal_entries "
        "ORDER BY id DESC LIMIT 15")
st.dataframe(act, width='stretch', hide_index=True)
