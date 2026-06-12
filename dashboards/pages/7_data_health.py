"""Data health: source freshness, snapshot coverage, AV budget, LLM availability."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from components import CFG, header, q

header("🩺 Data Health", "Freshness, coverage, and budgets across data sources")

# ---- LLM + live-trading status ----
c1, c2, c3 = st.columns(3)
c1.metric("LLM advisor", "enabled" if CFG.llm_enabled else "disabled (algorithmic)")
c2.metric("Live trading", "ON" if CFG.live_trading else "OFF (paper)")
budget = q("SELECT calls_used FROM api_budget WHERE source='alphavantage' AND date=?",
           (date.today().isoformat(),))
used = int(budget["calls_used"].iloc[0]) if not budget.empty else 0
c3.metric("Alpha Vantage calls today", f"{used} / {CFG.av_daily_budget:,}")

# ---- snapshot coverage ----
st.subheader("Price snapshot coverage")
prices_dir = CFG.snapshot_dir / "prices"
files = sorted(prices_dir.glob("*.parquet"))
rows = []
for f in files:
    try:
        df = pd.read_parquet(f)
        rows.append({"ticker": f.stem, "rows": len(df),
                     "from": str(pd.to_datetime(df.index).min().date()),
                     "to": str(pd.to_datetime(df.index).max().date())})
    except Exception:
        rows.append({"ticker": f.stem, "rows": 0, "from": "—", "to": "—"})
cov = pd.DataFrame(rows)
st.metric("Tickers with price history", len(cov))
st.dataframe(cov, width='stretch', hide_index=True, height=300)

# ---- bpiq / edgar snapshot presence ----
col1, col2 = st.columns(2)
with col1:
    st.subheader("EDGAR fundamentals")
    edgar = list((CFG.snapshot_dir / "edgar").glob("*.json"))
    st.metric("Companies with fundamentals", len(edgar))
with col2:
    st.subheader("BPIQ snapshots")
    bpiq = list((CFG.snapshot_dir / "bpiq").glob("*.json"))
    st.write(", ".join(sorted(f.stem for f in bpiq)) or "none")

# ---- external signal export (contaminated-discovery bundle) ----
st.subheader("External signal export")
ext_dir = CFG.snapshot_dir / "external"
hist_path = ext_dir / "signal_history_export.parquet"
ev_path = ext_dir / "catalyst_events_export.csv"
if not hist_path.exists():
    st.caption("No external export present (data/snapshots/external/).")
else:
    @st.cache_data(ttl=600)
    def _external_coverage():
        hist = pd.read_parquet(hist_path, columns=["ticker", "as_of_date",
                                                   "signal_name"])
        cov = (hist.groupby("signal_name")["as_of_date"]
               .agg(rows="size", first="min", last="max").reset_index())
        n_events = len(pd.read_csv(ev_path)) if ev_path.exists() else 0
        return cov, hist["ticker"].nunique(), len(hist), n_events

    cov, n_tickers, n_rows, n_events = _external_coverage()
    c1, c2, c3 = st.columns(3)
    c1.metric("Signal rows", f"{n_rows:,}")
    c2.metric("Tickers", n_tickers)
    c3.metric("Pinned catalyst events", f"{n_events:,}")
    st.dataframe(cov.sort_values("rows", ascending=False),
                 width='stretch', hide_index=True, height=300)

    from quantzzz.data.external_signals import EXCLUDED_SIGNALS
    st.caption(
        "Reconciliation flags enforced by the loader: excluded signals — "
        f"{', '.join(sorted(EXCLUDED_SIGNALS))} (look-ahead confirmed or "
        "pending temporal audit); risk reversal exposed only in unsigned "
        "|RR| form; correlated ATM-IV tenor cluster collapsed to iv_atm_30d. "
        "Excluded signals above appear in the raw export but never reach "
        "strategies.")

# ---- recent fetch events / errors ----
st.subheader("Recent data events")
health = q("SELECT ts, source, ticker, status, detail FROM data_health "
           "ORDER BY id DESC LIMIT 40")
if not health.empty:
    st.dataframe(health, width='stretch', hide_index=True)
else:
    st.caption("No data events logged yet.")
