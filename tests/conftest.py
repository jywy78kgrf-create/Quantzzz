from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def price_panel(rng) -> pd.DataFrame:
    """500 days of synthetic GBM-ish prices for 8 tickers."""
    dates = pd.bdate_range("2022-01-03", periods=500)
    tickers = [f"T{i}" for i in range(8)]
    drift = rng.uniform(-0.0002, 0.0008, size=len(tickers))
    rets = rng.normal(drift, 0.02, size=(len(dates), len(tickers)))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    return pd.DataFrame(prices, index=dates, columns=tickers)


@pytest.fixture
def tmp_db(tmp_path):
    from quantzzz.db import get_conn, init_schema

    conn = get_conn(tmp_path / "test.db")
    init_schema(conn)
    yield conn
    conn.close()
