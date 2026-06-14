import numpy as np
import pandas as pd

from quantzzz.config import load_config
from quantzzz.trading.catalyst_sleeve import FUND, CatalystSleeve


class _FakeStore:
    def __init__(self, panels):
        self.panels = panels

    def load_prices(self, ticker):
        return self.panels.get(ticker)


def _rising_panel(cat: pd.Timestamp) -> pd.DataFrame:
    dates = pd.bdate_range(cat - pd.Timedelta(days=400), cat + pd.Timedelta(days=10))
    return pd.DataFrame(
        {"close": np.linspace(30.0, 150.0, len(dates)),   # ~ +54% over any 180d
         "volume": np.full(len(dates), 2e6)},
        index=dates)


def test_sleeve_enters_in_window_then_exits_before_catalyst(tmp_db):
    cfg = load_config()
    cat = pd.Timestamp("2024-10-01")
    store = _FakeStore({"AAA": _rising_panel(cat)})
    events = pd.DataFrame([{"event_id": "E1", "ticker": "AAA",
                            "catalyst_type": "Phase3", "catalyst_date": cat}])
    sleeve = CatalystSleeve(cfg, tmp_db, require_volume=False, store=store, events=events)

    # T-60: inside the entry window, momentum gate passes -> one discrete entry
    msg = sleeve.session(as_of=(cat - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))
    assert "1 entered" in msg
    assert tmp_db.execute(
        "SELECT COUNT(*) FROM catalyst_sleeve WHERE fund=?", (FUND,)).fetchone()[0] == 1

    # at the catalyst date: past the exit point -> close before the readout
    msg2 = sleeve.session(as_of=cat.strftime("%Y-%m-%d"))
    assert "1 exited" in msg2
    assert tmp_db.execute(
        "SELECT COUNT(*) FROM catalyst_sleeve WHERE fund=?", (FUND,)).fetchone()[0] == 0
    tr = tmp_db.execute(
        "SELECT pnl_pct, exit_reason, source FROM trades WHERE fund=?", (FUND,)).fetchone()
    assert tr is not None
    assert tr["pnl_pct"] > 0           # price rose over the hold window
    assert tr["source"] == "replay"    # as-of session is a replay


def test_sleeve_skips_weak_momentum(tmp_db):
    cfg = load_config()
    cat = pd.Timestamp("2024-10-01")
    dates = pd.bdate_range(cat - pd.Timedelta(days=400), cat + pd.Timedelta(days=10))
    flat = pd.DataFrame({"close": np.full(len(dates), 100.0),
                         "volume": np.full(len(dates), 2e6)}, index=dates)
    sleeve = CatalystSleeve(cfg, tmp_db, require_volume=False, store=_FakeStore({"BBB": flat}),
                            events=pd.DataFrame([{"event_id": "E2", "ticker": "BBB",
                                                  "catalyst_type": "Phase3", "catalyst_date": cat}]))
    msg = sleeve.session(as_of=(cat - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))
    assert "0 entered" in msg           # flat price fails the top-quintile run-up gate


def test_sleeve_respects_10_dollar_floor(tmp_db):
    cfg = load_config()
    cat = pd.Timestamp("2024-10-01")
    dates = pd.bdate_range(cat - pd.Timedelta(days=400), cat + pd.Timedelta(days=10))
    # huge run-up (+300%) but priced under $10 at entry -> excluded by the
    # validated price floor, even though it clears the momentum gate
    cheap = pd.DataFrame({"close": np.linspace(2.0, 8.0, len(dates)),
                          "volume": np.full(len(dates), 2e6)}, index=dates)
    sleeve = CatalystSleeve(cfg, tmp_db, require_volume=False, store=_FakeStore({"PNY": cheap}),
                            events=pd.DataFrame([{"event_id": "E3", "ticker": "PNY",
                                                  "catalyst_type": "Phase3", "catalyst_date": cat}]))
    msg = sleeve.session(as_of=(cat - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))
    assert "0 entered" in msg
    # with the floor lowered, the same name now qualifies
    sleeve2 = CatalystSleeve(cfg, tmp_db, require_volume=False, price_floor=1.0,
                             store=_FakeStore({"PNY": cheap}),
                             events=pd.DataFrame([{"event_id": "E3", "ticker": "PNY",
                                                   "catalyst_type": "Phase3", "catalyst_date": cat}]))
    msg2 = sleeve2.session(as_of=(cat - pd.Timedelta(days=60)).strftime("%Y-%m-%d"))
    assert "1 entered" in msg2
