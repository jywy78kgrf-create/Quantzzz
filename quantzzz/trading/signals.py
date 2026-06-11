"""Generate live trade candidates from a fund's promoted strategies."""

from __future__ import annotations

import sqlite3

import pandas as pd

from ..config import Config
from ..data.snapshots import SnapshotStore
from ..research.feature_loader import load_feature_bundle
from ..research.strategies import signal_fn_for
from ..research.strategy_space import StrategySpec
from ..universe import universe_for


def promoted_strategies(conn: sqlite3.Connection, fund: str) -> list[tuple[int, StrategySpec]]:
    rows = conn.execute(
        "SELECT id, family, params_json FROM strategies "
        "WHERE desk=? AND status='promoted'", (fund,)).fetchall()
    return [(r["id"], StrategySpec.from_row(r["family"], fund, r["params_json"]))
            for r in rows]


def generate_candidates(cfg: Config, fund: str, conn: sqlite3.Connection,
                        store: SnapshotStore, as_of=None, bundle=None) -> list[dict]:
    """For each promoted strategy, read the latest target weights and emit candidates.

    Returns dicts: {strategy_id, ticker, direction, strength, target_weight}.
    Direction 'long' = strategy wants exposure; the trader reconciles vs holdings.
    When as_of is set, signals are computed as if that date were the present.
    A prebuilt `bundle` can be passed to avoid reloading snapshots each call.
    """
    if bundle is None:
        tickers = universe_for(fund, cfg.snapshot_dir)
        bundle = load_feature_bundle(cfg, fund, tickers, store, conn)
    if bundle.prices.empty:
        return []
    if as_of is not None:
        dates = bundle.prices.index[bundle.prices.index <= as_of]
        if len(dates) < 2:
            return []
        bundle = bundle.slice(dates)

    out: list[dict] = []
    for strat_id, spec in promoted_strategies(conn, fund):
        try:
            weights = signal_fn_for(spec.family)(bundle, spec.params)
        except Exception:
            continue
        if weights.empty:
            continue
        latest = weights.iloc[-1]
        prev = weights.iloc[-2] if len(weights) > 1 else latest * 0
        for ticker, w in latest.items():
            if w > 1e-4:
                out.append({
                    "strategy_id": strat_id, "ticker": ticker, "direction": "long",
                    "strength": float(w), "target_weight": float(w),
                })
            elif prev.get(ticker, 0) > 1e-4 >= w:
                out.append({
                    "strategy_id": strat_id, "ticker": ticker, "direction": "exit",
                    "strength": 0.0, "target_weight": 0.0,
                })
    return out
