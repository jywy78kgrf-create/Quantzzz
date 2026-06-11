"""Biotech quant lab: research view + catalyst calendar + historical move stats."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from components import CFG, header
from lab_view import render_lab

header("🧬 Biotech Quant Lab", "Catalyst-driven strategy search")
render_lab("biotech")

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
