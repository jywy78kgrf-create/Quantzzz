import numpy as np
import pandas as pd
import pytest

from quantzzz.research.backtest import Backtester, chronological_split


def test_no_lookahead():
    """A signal fired on day T must not capture day T's return."""
    dates = pd.bdate_range("2023-01-02", periods=4)
    # price jumps +50% on day 2 only
    prices = pd.DataFrame({"A": [100.0, 100.0, 150.0, 150.0]}, index=dates)
    # signal turns on exactly on the jump day
    w = pd.DataFrame({"A": [0.0, 0.0, 1.0, 1.0]}, index=dates)
    res = Backtester(cost_bps=0).run(w, prices)
    # held weight on jump day is shift(1) = 0 -> no profit from the jump
    assert res.returns.sum() == pytest.approx(0.0)


def test_captures_return_after_signal():
    dates = pd.bdate_range("2023-01-02", periods=4)
    prices = pd.DataFrame({"A": [100.0, 100.0, 100.0, 120.0]}, index=dates)
    w = pd.DataFrame({"A": [0.0, 0.0, 1.0, 1.0]}, index=dates)
    res = Backtester(cost_bps=0).run(w, prices)
    assert res.returns.iloc[-1] == pytest.approx(0.20)


def test_costs_reduce_returns():
    dates = pd.bdate_range("2023-01-02", periods=10)
    prices = pd.DataFrame({"A": np.linspace(100, 110, 10)}, index=dates)
    w = pd.DataFrame({"A": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]}, index=dates, dtype=float)
    gross = Backtester(cost_bps=0).run(w, prices).returns.sum()
    net = Backtester(cost_bps=50).run(w, prices).returns.sum()
    assert net < gross


def test_round_trip_pnls_extracted():
    dates = pd.bdate_range("2023-01-02", periods=6)
    prices = pd.DataFrame({"A": [100, 100, 110, 121, 121, 121]}, index=dates, dtype=float)
    w = pd.DataFrame({"A": [0, 1, 1, 0, 0, 0]}, index=dates, dtype=float)
    res = Backtester(cost_bps=0).run(w, prices)
    # held on days 2 and 3 -> 10% then 10% compounded = 21%
    assert len(res.trade_pnls) == 1
    assert res.trade_pnls[0] == pytest.approx(0.21)


def test_chronological_split_no_overlap_with_embargo():
    dates = pd.bdate_range("2020-01-01", periods=100)
    train, test = chronological_split(dates, train_frac=0.7, embargo_days=5)
    assert train.max() < test.min()
    assert (test.min() - train.max()).days >= 5
    assert len(train) == 70


def test_liquidity_cost_panel_charges_small_caps_more():
    import numpy as np
    import pandas as pd
    from quantzzz.data.features import trading_cost_bps
    from quantzzz.research.backtest import Backtester

    dates = pd.bdate_range("2024-01-01", periods=120)
    prices = pd.DataFrame({"BIG": 100.0, "SML": 10.0}, index=dates)
    volume = pd.DataFrame({"BIG": 20_000_000.0, "SML": 100_000.0}, index=dates)
    cost = trading_cost_bps(prices, volume)
    assert cost["SML"].iloc[-1] > cost["BIG"].iloc[-1] * 3   # illiquid pays up

    # identical weights/returns -> the panel-cost run nets less on SML turnover
    w = pd.DataFrame(0.0, index=dates, columns=["BIG", "SML"])
    w.iloc[::5, 1] = 0.5                                     # churn the small cap
    flat = Backtester(cost_bps=10.0).run(w, prices)
    panel = Backtester(cost_bps=10.0).run(w, prices, cost_panel=cost)
    assert panel.returns.sum() < flat.returns.sum()


def test_cost_panel_falls_back_flat_without_volume():
    import pandas as pd
    from quantzzz.data.features import trading_cost_bps
    dates = pd.bdate_range("2024-01-01", periods=30)
    prices = pd.DataFrame({"A": 50.0}, index=dates)
    cost = trading_cost_bps(prices, pd.DataFrame(), fallback_bps=10.0)
    assert (cost["A"] == 10.0).all()
