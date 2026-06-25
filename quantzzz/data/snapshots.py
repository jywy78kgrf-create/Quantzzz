"""Parquet/JSON snapshot store — the offline data bundle everything falls back to."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd


class SnapshotStore:
    def __init__(self, snapshot_dir: Path):
        self.dir = Path(snapshot_dir)
        self.prices_dir = self.dir / "prices"
        self.prices_dir.mkdir(parents=True, exist_ok=True)

    # ---- prices ----
    def save_prices(self, ticker: str, df: pd.DataFrame) -> None:
        """df: index=DatetimeIndex, columns include close, volume (adjusted)."""
        df.sort_index().to_parquet(self.prices_dir / f"{ticker}.parquet")

    def load_prices(self, ticker: str) -> pd.DataFrame | None:
        path = self.prices_dir / f"{ticker}.parquet"
        if not path.exists():
            return None
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        return df.sort_index()

    def available_tickers(self) -> list[str]:
        return sorted(p.stem for p in self.prices_dir.glob("*.parquet"))

    def load_close_panel(self, tickers: list[str]) -> pd.DataFrame:
        """Wide DataFrame of adjusted closes (dates x tickers) for available tickers."""
        cols = {}
        for t in tickers:
            df = self.load_prices(t)
            if df is not None and "close" in df.columns:
                cols[t] = df["close"]
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).sort_index()

    def load_volume_panel(self, tickers: list[str]) -> pd.DataFrame:
        cols = {}
        for t in tickers:
            df = self.load_prices(t)
            if df is not None and "volume" in df.columns:
                cols[t] = df["volume"]
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).sort_index()

    # ---- json blobs (edgar extracts, bpiq exports) ----
    def save_json(self, relpath: str, obj) -> None:
        path = self.dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        # atomic write: a process killed mid-write (e.g. a CI run cancelled at
        # the timeout) must never leave a truncated, unparseable file behind.
        # Write a temp sibling on the same filesystem, then os.replace — which
        # is atomic — so a reader sees the old file or the new one, never half.
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(obj, indent=1, default=str))
        os.replace(tmp, path)

    def load_json(self, relpath: str):
        path = self.dir / relpath
        if not path.exists():
            return None
        return json.loads(path.read_text())
