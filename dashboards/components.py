"""Shared dashboard helpers: DB access, charts, and formatting."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quantzzz.config import load_config  # noqa: E402
from quantzzz.db import get_conn  # noqa: E402

CFG = load_config()
COLORS = {"equity": "#2563eb", "biotech": "#16a34a", "bench": "#9ca3af"}


def _conn():
    # Fresh, read-only-ish connection per call: Streamlit runs scripts on
    # different threads and SQLite connections are thread-bound.
    return get_conn(CFG.db_path)


@st.cache_data(ttl=20)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = _conn()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def metric_row(items: list[tuple[str, str]]):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


def money(x: float) -> str:
    return f"${x:,.0f}"


def pct(x: float) -> str:
    return f"{x:+.2%}"


def equity_curve_fig(funds: dict[str, pd.DataFrame], title: str) -> go.Figure:
    fig = go.Figure()
    for fund, df in funds.items():
        if df.empty:
            continue
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(df["ts"]), y=df["equity"], name=fund.title(),
            line=dict(color=COLORS.get(fund, "#888"), width=2)))
    fig.update_layout(title=title, height=360, margin=dict(l=10, r=10, t=40, b=10),
                      yaxis_title="Equity ($)", template="plotly_white",
                      legend=dict(orientation="h"))
    return fig


def line_fig(df: pd.DataFrame, x: str, y: str, title: str, color: str = "#2563eb") -> go.Figure:
    fig = go.Figure(go.Scatter(x=df[x], y=df[y], mode="lines+markers",
                               line=dict(color=color)))
    fig.update_layout(title=title, height=300, margin=dict(l=10, r=10, t=40, b=10),
                      template="plotly_white")
    return fig


def gauge(value: float, limit: float, title: str) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value,
        title={"text": title},
        gauge={"axis": {"range": [0, max(limit * 1.3, value * 1.1, 0.01)]},
               "bar": {"color": "#2563eb" if value <= limit else "#dc2626"},
               "threshold": {"line": {"color": "red", "width": 3}, "value": limit}}))
    fig.update_layout(height=240, margin=dict(l=20, r=20, t=50, b=10))
    return fig


def header(title: str, subtitle: str = ""):
    st.title(title)
    if subtitle:
        st.caption(subtitle)
