"""Decision journal feed and recursive-learning evolution."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components import header, q

header("📒 Journal & Learning", "Why each trade happened, and how the agents adapt")

col_f1, col_f2 = st.columns(2)
fund = col_f1.selectbox("Fund", ["all", "equity", "biotech"])
etypes = ["all", "entry", "exit", "reject", "resize", "halt", "learning",
          "promotion", "llm_review"]
etype = col_f2.selectbox("Entry type", etypes)

where, params = [], []
if fund != "all":
    where.append("fund=?"); params.append(fund)
if etype != "all":
    where.append("entry_type=?"); params.append(etype)
clause = ("WHERE " + " AND ".join(where)) if where else ""

st.subheader("Decision journal")
journal = q(f"SELECT ts, fund, entry_type, ticker, action, reasoning FROM journal_entries "
            f"{clause} ORDER BY id DESC LIMIT 100", tuple(params))
st.dataframe(journal, width='stretch', hide_index=True)

# LLM reviews surfaced prominently
reviews = q("SELECT ts, fund, reasoning FROM journal_entries WHERE entry_type='llm_review' "
            "ORDER BY id DESC LIMIT 5")
if not reviews.empty:
    st.subheader("🤖 LLM desk reviews")
    for _, r in reviews.iterrows():
        st.info(f"**{r['fund'].title()}** · {r['ts']}\n\n{r['reasoning']}")

st.subheader("Strategy weight multipliers over time")
perf = q("SELECT strategy_id, as_of_ts, weight_multiplier, hit_rate, payoff, "
         "n_closed, active FROM strategy_performance ORDER BY as_of_ts")
if not perf.empty:
    fig = go.Figure()
    for sid, g in perf.groupby("strategy_id"):
        fig.add_trace(go.Scatter(x=g["as_of_ts"], y=g["weight_multiplier"],
                                 mode="lines+markers", name=f"#{sid}"))
    fig.update_layout(height=320, template="plotly_white", yaxis_title="weight multiplier",
                      margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width='stretch')
    st.dataframe(perf.round(3).sort_values("as_of_ts", ascending=False),
                 width='stretch', hide_index=True)
else:
    st.caption("No learning reviews yet — they run after enough trades close.")
