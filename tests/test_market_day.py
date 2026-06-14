"""Forward sessions should count real trading days, and delisted holdings
should be closed rather than carried at a frozen price."""

import pandas as pd

from quantzzz.trading.trader import TraderAgent


class _Stub:
    DELIST_STALE_DAYS = 15
    _latest_price_date = TraderAgent._latest_price_date
    _stale_tickers = TraderAgent._stale_tickers

    def __init__(self, panels):
        self._all_prices = panels


def test_latest_price_date_and_stale_detection():
    s = _Stub({
        "FRESH": pd.Series([1.0, 2.0], index=pd.bdate_range("2026-06-08", periods=2)),
        "STALE": pd.Series([1.0, 2.0], index=pd.bdate_range("2026-04-01", periods=2)),
    })
    assert s._latest_price_date() == "2026-06-09"     # max across the panel
    assert s._stale_tickers() == {"STALE"}            # 2+ months behind -> delisted/stale
    # a normal weekend gap (a few days) must NOT flag a name as stale
    s2 = _Stub({
        "A": pd.Series([1.0], index=pd.DatetimeIndex(["2026-06-12"])),  # Friday
        "B": pd.Series([1.0], index=pd.DatetimeIndex(["2026-06-12"])),
    })
    assert s2._stale_tickers() == set()
