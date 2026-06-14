import pandas as pd

from quantzzz.data.features import days_to_catalyst_frame


class _Bundle:
    dates = pd.bdate_range("2024-01-01", periods=60)
    prices = pd.DataFrame(1.0, index=dates, columns=["AAA"])
    catalysts = [{"ticker": "AAA", "catalyst_date": str(dates[40].date())}]


def test_days_to_catalyst_is_trading_days_not_calendar():
    f = days_to_catalyst_frame(_Bundle())
    # 40 TRADING days to the catalyst, not the ~58 calendar days the old
    # (timestamp - timestamp).days computed
    assert f["AAA"].iloc[0] == 40
    assert f["AAA"].iloc[10] == 30
    assert f["AAA"].iloc[40] == 0          # zero on the catalyst day
    assert pd.isna(f["AAA"].iloc[41])      # nothing ahead after it
