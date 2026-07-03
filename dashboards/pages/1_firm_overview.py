"""Firm-wide overview: both funds' equity, P&L, exposure, drawdown."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from components import CFG, equity_curve_fig, header, metric_row, money, q

header("🏦 Quantzzz Capital", "Two autonomous quant funds · equity & biotech")

funds = {}
for fund in ("equity", "biotech"):
    funds[fund] = q("SELECT ts, equity, cash, gross_exposure, net_exposure, drawdown, "
                    "source FROM equity_snapshots WHERE fund=? ORDER BY ts", (fund,))

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

# forward (live-only) record per fund — the referee, separated from the
# replayed history that built most of the curve
fwd_cards = []
go_lives = {}
for fund in ("equity", "biotech"):
    df = funds[fund]
    live = df[df["source"] == "live"] if not df.empty else df
    if live.empty:
        fwd_cards.append((f"{fund.title()} forward (live)", "starts next cycle"))
        continue
    go_lives[fund] = pd.to_datetime(live["ts"].iloc[0], format="ISO8601", utc=True)
    fwd_ret = live["equity"].iloc[-1] / live["equity"].iloc[0] - 1
    fwd_cards.append((f"{fund.title()} forward (live)",
                      f"{fwd_ret:+.2%} since {go_lives[fund].date()}"))
metric_row(fwd_cards)
st.caption("Headline returns include replayed history (promoted strategies "
           "stepped through past dates). The forward (live) numbers count only "
           "real-time sessions — that's the track record being earned, not "
           "reconstructed.")

fig = equity_curve_fig(funds, "Equity curves")
for fund, ts in go_lives.items():
    fig.add_vline(x=ts, line_dash="dot", line_color="#f59e0b")
if go_lives:
    fig.add_annotation(x=min(go_lives.values()), y=1.02, yref="paper",
                       text="go-live", showarrow=False, font=dict(color="#f59e0b"))
st.plotly_chart(fig, width='stretch')

# ---- the bar to clear: fund vs plain buy-and-hold of its benchmark ----
st.subheader("Fund vs buy-and-hold benchmark")
from quantzzz.config import BENCHMARKS  # noqa: E402
from quantzzz.data.snapshots import SnapshotStore  # noqa: E402

store = SnapshotStore(CFG.snapshot_dir)
bench_rows = []
for fund in ("equity", "biotech"):
    df = funds[fund]
    if df.empty or len(df) < 2:
        continue
    start_ts = pd.to_datetime(df["ts"].iloc[0], format="ISO8601", utc=True).tz_localize(None)
    end_ts = pd.to_datetime(df["ts"].iloc[-1], format="ISO8601", utc=True).tz_localize(None)
    fund_ret = df["equity"].iloc[-1] / df["equity"].iloc[0] - 1
    bench_t = BENCHMARKS[fund]
    bench_px = store.load_prices(bench_t)
    bench_ret = None
    if bench_px is not None:
        window = bench_px.loc[(bench_px.index >= start_ts) & (bench_px.index <= end_ts), "close"]
        if len(window) >= 2:
            bench_ret = window.iloc[-1] / window.iloc[0] - 1
    bench_rows.append({
        "Fund": fund.title(),
        "Fund return": f"{fund_ret:+.2%}",
        "Buy & hold": f"{bench_ret:+.2%} ({bench_t})" if bench_ret is not None else "—",
        "Excess (the alpha that matters)":
            f"{fund_ret - bench_ret:+.2%}" if bench_ret is not None else "—",
    })
if bench_rows:
    st.dataframe(pd.DataFrame(bench_rows), width='stretch', hide_index=True)
    st.caption("A fund only earns its keep if the excess column is positive over time. "
               "Paper-traded forward results, net of simulated costs.")
else:
    st.caption("Needs trading history — run trader sessions or a replay first.")

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
