"""Shared research-lab rendering used by both the equity and biotech lab pages."""

from __future__ import annotations

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from components import line_fig, q


def render_lab(desk: str) -> None:
    runs = q("SELECT id, iterations, promotions FROM research_runs WHERE desk=? "
             "ORDER BY id DESC", (desk,))
    iters = q("SELECT iter_num, oos_sharpe, fitness, promoted, family, origin "
              "FROM research_iterations i JOIN strategies s ON s.id=i.strategy_id "
              "WHERE i.desk=? ORDER BY i.id", (desk,))

    c1, c2, c3 = st.columns(3)
    c1.metric("Research runs", len(runs))
    c2.metric("Iterations", len(iters))
    c3.metric("Promoted", int((iters["promoted"] == 1).sum()) if not iters.empty else 0)

    if iters.empty:
        st.info(f"No research yet. Run `python -m quantzzz research --desk {desk} "
                f"--iterations 50`.")
        return

    prog = iters.dropna(subset=["oos_sharpe"]).reset_index(drop=True)
    if not prog.empty:
        prog["best_so_far"] = prog["oos_sharpe"].cummax()
        fig = go.Figure()
        fig.add_trace(go.Scatter(y=prog["oos_sharpe"], mode="markers",
                                 name="iteration OOS Sharpe",
                                 marker=dict(size=5, color="#93c5fd")))
        fig.add_trace(go.Scatter(y=prog["best_so_far"], mode="lines", name="best so far",
                                 line=dict(color="#2563eb", width=3)))
        fig.update_layout(title="Search progress (out-of-sample Sharpe)", height=320,
                          template="plotly_white", margin=dict(l=10, r=10, t=40, b=10),
                          xaxis_title="iteration")
        st.plotly_chart(fig, width='stretch')

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Strategy leaderboard")
        board = q("""
            SELECT s.id, s.family, s.origin, s.status,
                   i.oos_sharpe, i.oos_alpha, i.max_dd, i.n_trades, i.hit_rate,
                   i.fitness, i.dsr_prob, i.window_sharpes
            FROM strategies s
            JOIN research_iterations i ON i.strategy_id = s.id
            WHERE s.desk=? AND i.oos_sharpe IS NOT NULL
            GROUP BY s.id HAVING i.fitness = MAX(i.fitness)
            ORDER BY i.fitness DESC LIMIT 25""", (desk,))
        if not board.empty:
            st.dataframe(board.round(3), width='stretch', hide_index=True)
            st.caption(
                "dsr_prob = deflated Sharpe: probability the OOS Sharpe beats the "
                "noise floor of the multi-candidate search. window_sharpes = Sharpe "
                "in each walk-forward window (consistency check).")
    with col2:
        st.subheader("Proposal origins")
        origins = iters["origin"].value_counts().reset_index()
        origins.columns = ["origin", "count"]
        st.dataframe(origins, width='stretch', hide_index=True)
        st.subheader("Top failure reasons")
        fails = q("SELECT fail_reasons FROM research_iterations WHERE desk=? "
                  "AND promoted=0 AND fail_reasons IS NOT NULL", (desk,))
        if not fails.empty:
            reasons = (fails["fail_reasons"].str.split(";").explode().str.strip()
                       .str.replace(r"[\d.]+", "", regex=True).str.strip())
            top = reasons.value_counts().head(6).reset_index()
            top.columns = ["reason", "count"]
            st.dataframe(top, width='stretch', hide_index=True)

    st.subheader("Tearsheet")
    promoted = q("SELECT id, family, params_json FROM strategies "
                 "WHERE desk=? AND status='promoted'", (desk,))
    if promoted.empty:
        st.caption("No promoted strategies yet.")
        return
    options = {f"#{r.id} {r.family}": int(r.id) for r in promoted.itertuples()}
    choice = st.selectbox("Promoted strategy", list(options), key=f"ts_{desk}")
    sid = options[choice]
    row = promoted[promoted["id"] == sid].iloc[0]
    st.caption(f"Params: {row['params_json']}")
    curve = q("SELECT equity_curve_json FROM research_iterations WHERE strategy_id=? "
              "AND equity_curve_json IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,))
    if not curve.empty and curve["equity_curve_json"].iloc[0]:
        data = json.loads(curve["equity_curve_json"].iloc[0])
        s = pd.Series(data)
        s.index = pd.to_datetime(s.index)
        cdf = s.reset_index()
        cdf.columns = ["date", "equity"]
        st.plotly_chart(line_fig(cdf, "date", "equity", "Out-of-sample equity curve"),
                        width='stretch')
