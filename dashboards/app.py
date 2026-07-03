"""Quantzzz dashboards entry point."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Quantzzz", page_icon="📈", layout="wide")

pages = [
    st.Page("pages/1_firm_overview.py", title="Firm Overview", icon="🏦"),
    st.Page("pages/2_equity_lab.py", title="Equity Quant Lab", icon="🔬"),
    st.Page("pages/3_biotech_lab.py", title="Biotech Quant Lab", icon="🧬"),
    st.Page("pages/4_trader_equity.py", title="Trader Desk · Equity", icon="💹"),
    st.Page("pages/5_trader_biotech.py", title="Trader Desk · Biotech", icon="💊"),
    st.Page("pages/6_journal_learning.py", title="Journal & Learning", icon="📒"),
    st.Page("pages/7_data_health.py", title="Data Health", icon="🩺"),
]
st.navigation(pages).run()
