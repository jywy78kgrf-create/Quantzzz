"""Vendor-grade chain summary: ATM tenor interpolation, 25d RR, OI ratios."""

from quantzzz.data.alphavantage import AlphaVantageClient, summarize_chain


def _c(exp, strike, typ, iv, delta, vol=10, oi=100):
    return {"expiration": exp, "strike": str(strike), "type": typ,
            "implied_volatility": str(iv), "delta": str(delta),
            "volume": str(vol), "open_interest": str(oi), "date": "2026-06-12"}


def test_atm_tenor_interpolation_and_rr():
    spot = 100.0
    chain = [
        # 20d expiry: ATM IV 0.60
        _c("2026-07-02", 100, "call", 0.60, 0.50), _c("2026-07-02", 100, "put", 0.60, -0.50),
        _c("2026-07-02", 120, "call", 0.70, 0.25), _c("2026-07-02", 80, "put", 0.75, -0.25),
        # 40d expiry: ATM IV 0.80
        _c("2026-07-22", 100, "call", 0.80, 0.50), _c("2026-07-22", 100, "put", 0.80, -0.50),
        # 180d expiry: ATM IV 0.50
        _c("2026-12-09", 100, "call", 0.50, 0.50),
    ]
    s = summarize_chain(chain, spot)
    # 30d sits halfway between the 20d (0.60) and 40d (0.80) tenors
    assert abs(s["atm_iv_30d"] - 0.70) < 1e-6
    # RR from the 25-delta contracts on the expiry nearest 30d
    assert abs(s["rr_25d"] - (0.70 - 0.75)) < 1e-6
    assert s["total_open_interest"] == 700
    assert s["put_call_oi_ratio"] == round(300 / 400, 4)
    assert s["iv_term_structure_30_180"] == round(0.70 / 0.50, 4)


def test_chain_summary_degrades_without_spot_or_deltas():
    chain = [_c("2026-07-02", 100, "call", 0.6, "")]
    s = summarize_chain(chain, None)
    assert s["atm_iv_30d"] is None and s["rr_25d"] is None
    assert s["total_volume"] == 10


def test_parse_daily_carries_adjusted_ohlc():
    data = {"Time Series (Daily)": {"2026-06-12": {
        "1. open": "100", "2. high": "110", "3. low": "90",
        "4. close": "100", "5. adjusted close": "50", "6. volume": "1000"}}}
    df = AlphaVantageClient._parse_daily(data)
    assert df["open"].iloc[0] == 50.0 and df["low"].iloc[0] == 45.0
    assert df["high"].iloc[0] == 55.0 and df["close"].iloc[0] == 50.0
