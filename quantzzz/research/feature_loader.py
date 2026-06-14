"""Assemble a FeatureBundle for a desk from snapshot/cache data."""

from __future__ import annotations

import sqlite3


from ..config import Config
from ..data.external_signals import load_external_signals
from ..data.features import FeatureBundle
from ..data.snapshots import SnapshotStore


def load_feature_bundle(cfg: Config, desk: str, tickers: list[str],
                        store: SnapshotStore, conn: sqlite3.Connection) -> FeatureBundle:
    close = store.load_close_panel(tickers)
    volume = store.load_volume_panel(tickers)
    # keep tickers that actually have price history; trim sparse leading dates
    if not close.empty:
        close = close.dropna(axis=1, how="all")
        close = close[close.notna().sum(axis=1) >= max(2, len(close.columns) // 5)]
        volume = volume.reindex(index=close.index, columns=close.columns)

    fundamentals: dict = {}
    catalysts: list = []
    hist: dict = {}
    earnings: dict = {}
    news: dict = {}
    external = None

    for t in close.columns:
        e = store.load_json(f"av_earnings/{t}.json")
        if e:
            earnings[t] = e
        n = store.load_json(f"av_news/{t}.json")
        if n:
            news[t] = n

    if desk == "equity":
        for t in close.columns:
            data = store.load_json(f"edgar/{t}.json")
            if data:
                fundamentals[t] = data

    if desk == "biotech":
        catalysts = store.load_json("bpiq/catalysts.json") or []
        for t in close.columns:
            h = store.load_json(f"bpiq/hist_{t}.json")
            if h:
                hist[t] = h
        external = load_external_signals(cfg.snapshot_dir)

    return FeatureBundle(desk=desk, prices=close, volume=volume,
                         fundamentals=fundamentals, catalysts=catalysts,
                         hist_catalysts=hist, earnings=earnings, news=news,
                         external=external)
