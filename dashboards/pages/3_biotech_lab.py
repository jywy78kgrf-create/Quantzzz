"""Biotech quant lab: research view + catalyst calendar + historical move stats."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from components import CFG, header, q
from lab_view import render_lab

header("🧬 Biotech Quant Lab", "Catalyst-driven strategy search")
render_lab("biotech")

st.divider()

# ---- external signal families: the contaminated-discovery gauntlet ----
from quantzzz.config import PROMOTION_THRESHOLDS, PROMOTION_THRESHOLDS_EXTERNAL
from quantzzz.research.strategies.biotech import EXTERNAL_FAMILIES

ext_list = sorted(EXTERNAL_FAMILIES)
ph = ",".join("?" * len(ext_list))
ext = q(f"""
    SELECT s.family, i.oos_sharpe, i.oos_alpha, i.max_dd, i.n_trades,
           i.dsr_prob, i.bootstrap_q05, i.fitness, i.promoted, i.fail_reasons,
           s.params_json
    FROM research_iterations i JOIN strategies s ON s.id = i.strategy_id
    WHERE i.desk='biotech' AND s.family IN ({ph})""", tuple(ext_list))

st.subheader("External signal families — contaminated-discovery gate")
st.caption(
    "These families trade signals discovered by an external scan of the same "
    "history they are backtested on, so promotion uses a stricter bar than "
    "price-native families: OOS Sharpe ≥ "
    f"{PROMOTION_THRESHOLDS_EXTERNAL.min_oos_sharpe} (vs "
    f"{PROMOTION_THRESHOLDS['biotech'].min_oos_sharpe}), deflated-Sharpe prob ≥ "
    f"{PROMOTION_THRESHOLDS_EXTERNAL.min_dsr_prob} (vs "
    f"{PROMOTION_THRESHOLDS['biotech'].min_dsr_prob}), all "
    f"{PROMOTION_THRESHOLDS_EXTERNAL.min_positive_windows} walk-forward windows "
    f"positive, bootstrap q05 ≥ {PROMOTION_THRESHOLDS_EXTERNAL.min_bootstrap_q05}, "
    f"≥ {PROMOTION_THRESHOLDS_EXTERNAL.min_trades} trades. A backtest pass is a "
    "candidate for paper trading, not a verdict — the forward paper record is "
    "the referee.")

if ext.empty:
    st.info("No external-family candidates evaluated yet.")
else:
    held_out = ext[(ext["fail_reasons"].fillna("").str.startswith("dsr_prob"))
                   & (~ext["fail_reasons"].fillna("").str.contains(";"))
                   & (ext["dsr_prob"] >= PROMOTION_THRESHOLDS["biotech"].min_dsr_prob)]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidates evaluated", len(ext))
    c2.metric("Best OOS Sharpe", f"{ext['oos_sharpe'].max():.2f}")
    c3.metric("Promoted", int(ext["promoted"].sum()))
    c4.metric("Held out by strict gate alone", len(held_out),
              help="Pass every standard-gate criterion (incl. deflated Sharpe ≥ "
                   f"{PROMOTION_THRESHOLDS['biotech'].min_dsr_prob}) but miss the "
                   f"strict {PROMOTION_THRESHOLDS_EXTERNAL.min_dsr_prob} bar — the "
                   "candidates the contaminated-discovery policy is deliberately "
                   "keeping on the bench.")

    by_fam = (ext.groupby("family")
              .agg(candidates=("family", "size"), best_oos=("oos_sharpe", "max"),
                   best_dsr=("dsr_prob", "max"), promoted=("promoted", "sum"))
              .reset_index().sort_values("best_oos", ascending=False))
    st.dataframe(by_fam.round(3), width='stretch', hide_index=True)

    near = ext.sort_values("fitness", ascending=False).head(8)[
        ["family", "oos_sharpe", "oos_alpha", "max_dd", "n_trades", "dsr_prob",
         "bootstrap_q05", "fail_reasons", "params_json"]]
    st.markdown("**Closest to promotion (by fitness)**")
    st.dataframe(near.round(3), width='stretch', hide_index=True)

    # bench watch: the single most decision-relevant trend in the system —
    # does the bench's deflated Sharpe converge to 0.90 as uncontaminated
    # post-discovery data accrues, or decay (selection noise)?
    trend = q(f"""
        SELECT date(i.ts) d, MAX(i.dsr_prob) best_dsr
        FROM research_iterations i JOIN strategies s ON s.id = i.strategy_id
        WHERE i.desk='biotech' AND s.family IN ({ph}) AND i.dsr_prob IS NOT NULL
        GROUP BY date(i.ts) ORDER BY d""", tuple(ext_list))
    if len(trend) >= 2:
        import plotly.graph_objects as go
        fig = go.Figure(go.Scatter(x=trend["d"], y=trend["best_dsr"],
                                   mode="lines+markers", name="best DSR",
                                   line=dict(color="#16a34a", width=2)))
        fig.add_hline(y=PROMOTION_THRESHOLDS_EXTERNAL.min_dsr_prob, line_dash="dash",
                      line_color="#dc2626", annotation_text="strict gate (promotes here)")
        fig.add_hline(y=PROMOTION_THRESHOLDS["biotech"].min_dsr_prob, line_dash="dot",
                      line_color="#9ca3af", annotation_text="standard gate")
        fig.update_layout(title="Bench watch: best external-family deflated Sharpe by day",
                          height=300, template="plotly_white",
                          margin=dict(l=10, r=10, t=40, b=10),
                          yaxis_range=[0, 1.0])
        st.plotly_chart(fig, width='stretch')
        st.caption("Rising toward the strict line as post-discovery data accrues "
                   "= the edge is real and will promote itself. Decaying = the "
                   "discovery was selection noise. Either way, this chart is the "
                   "verdict arriving.")

st.divider()


# ---- catalyst calendar ----
cat_path = CFG.snapshot_dir / "bpiq" / "catalysts.json"
if cat_path.exists():
    cats = json.loads(cat_path.read_text())
    rows = []
    for c in cats:
        se = c.get("stage_event") or {}
        rows.append({"ticker": c.get("ticker"), "drug": c.get("drug_name"),
                     "stage": se.get("stage_label"), "event": se.get("event_label"),
                     "date": c.get("catalyst_date"),
                     "big_mover": c.get("is_big_mover")})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    today = pd.Timestamp.today().normalize()
    upcoming = df[df["date"] >= today]
    st.subheader(f"Upcoming catalyst calendar ({len(upcoming)})")
    st.dataframe(upcoming.head(40), width='stretch', hide_index=True)
else:
    st.info("No BPIQ catalyst snapshot found. Run `python -m quantzzz refresh-data --desk biotech`.")

# ---- historical catalyst move distribution ----
moves = []
for f in (CFG.snapshot_dir / "bpiq").glob("hist_*.json"):
    try:
        for rec in json.loads(f.read_text()):
            for key in ("open_price_gap_percent", "intra_day_price_change_percent"):
                if rec.get(key) is not None:
                    moves.append(float(rec[key]))
    except (ValueError, TypeError, json.JSONDecodeError):
        continue
if moves:
    st.subheader("Historical catalyst move distribution")
    fig = px.histogram(pd.DataFrame({"move %": moves}), x="move %", nbins=40,
                       template="plotly_white")
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, width='stretch')
