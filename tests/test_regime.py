"""Volatility-regime feature: contango reads calm, backwardation reads stress,
and missing index data degrades to None (never an error)."""

import numpy as np
import pandas as pd

from quantzzz.data.alphavantage import AlphaVantageClient
from quantzzz.data.regime import vol_regime
from quantzzz.data.snapshots import SnapshotStore


def _store(tmp_path, series: dict):
    store = SnapshotStore(tmp_path)
    n = max(len(v) for v in series.values())
    dates = pd.bdate_range("2024-01-01", periods=n)
    for sym, vals in series.items():
        store.save_prices(sym, pd.DataFrame(
            {"close": vals, "raw_close": vals, "volume": 0.0}, index=dates))
    return store


def test_contango_reads_calm(tmp_path):
    rng = np.random.default_rng(0)
    vix3m = 20 + rng.normal(0, 2, 300)
    vix = vix3m - 3 + rng.normal(0, 1, 300)        # front below 3M: contango
    vix[-1] = vix.min()                            # end at a calm extreme
    vix3m[-1] = vix3m.max()
    r = vol_regime(_store(tmp_path, {"VIX": vix, "VIX3M": vix3m}))
    assert r is not None
    assert r["ratio"] < 1.0                        # contango
    assert r["label"] == "calm" and r["score"] < 0.6


def test_backwardation_reads_stress(tmp_path):
    rng = np.random.default_rng(1)
    vix3m = 20 + rng.normal(0, 2, 300)
    vix = vix3m - 3 + rng.normal(0, 1, 300)
    vix[-1] = vix.max() + 15                        # front-end spike
    vix3m[-1] = float(vix3m[-1])                    # 3M lags -> inversion
    r = vol_regime(_store(tmp_path, {"VIX": vix, "VIX3M": vix3m}))
    assert r["ratio"] > 1.0                         # backwardation
    assert r["label"] == "stress" and r["score"] >= 0.8


def test_extras_surface_when_present(tmp_path):
    base = 18 + np.zeros(40)
    store = _store(tmp_path, {"VIX": base, "VIX3M": base + 2,
                              "VVIX": base + 80, "SKEW": base + 120})
    r = vol_regime(store)
    assert "vvix" in r and "skew" in r


def test_missing_data_is_none_not_error(tmp_path):
    # only VIX present, no VIX3M -> cannot form term structure
    store = _store(tmp_path, {"VIX": np.full(50, 16.0)})
    assert vol_regime(store) is None
    assert vol_regime(SnapshotStore(tmp_path / "empty")) is None


def test_index_parser_shape():
    data = {"symbol": "VIX", "data": [
        {"date": "2026-06-15", "open": "16.8", "high": "16.9", "low": "16.0", "close": "16.2"},
        {"date": "2026-06-12", "open": "19.5", "high": "19.9", "low": "17.6", "close": "17.7"},
    ]}
    df = AlphaVantageClient._parse_index(data)
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-06-12", "2026-06-15"]  # sorted
    assert df["close"].iloc[-1] == 16.2
    assert AlphaVantageClient._parse_index({"data": []}) is None
