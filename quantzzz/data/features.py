"""Feature builders: the only inputs strategies see.

A FeatureBundle holds a wide close-price panel plus optional fundamental and
catalyst context, all aligned to the price calendar. Functions are pure pandas
and vectorized so strategies and the backtester stay fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd


@dataclass
class FeatureBundle:
    desk: str
    prices: pd.DataFrame                              # dates x tickers (adjusted close)
    volume: pd.DataFrame = field(default_factory=pd.DataFrame)
    fundamentals: dict = field(default_factory=dict)  # ticker -> edgar series dict
    catalysts: list = field(default_factory=list)     # bpiq catalyst records
    hist_catalysts: dict = field(default_factory=dict)  # ticker -> historical catalysts
    earnings: dict = field(default_factory=dict)      # ticker -> AV earnings surprises
    news: dict = field(default_factory=dict)          # ticker -> AV news sentiment
    external: object = None                           # ExternalSignals | None (biotech desk)

    @property
    def tickers(self) -> list[str]:
        return list(self.prices.columns)

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.prices.index

    def slice(self, dates: pd.DatetimeIndex) -> "FeatureBundle":
        return FeatureBundle(
            desk=self.desk,
            prices=self.prices.loc[self.prices.index.isin(dates)],
            volume=self.volume.loc[self.volume.index.isin(dates)] if not self.volume.empty else self.volume,
            fundamentals=self.fundamentals,
            catalysts=self.catalysts,
            hist_catalysts=self.hist_catalysts,
            earnings=self.earnings,
            news=self.news,
            external=self.external,
        )


# ---- price/volume features (vectorized over the whole panel) ----
def returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change()


def momentum(prices: pd.DataFrame, lookback: int, skip: int = 0) -> pd.DataFrame:
    """Trailing total return over `lookback` days, skipping the most recent `skip`."""
    return prices.shift(skip) / prices.shift(lookback + skip) - 1.0


def realized_vol(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    return returns(prices).rolling(lookback).std() * np.sqrt(252)


def zscore(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    """Cross-sectionally comparable mean-reversion z-score of price vs its SMA."""
    sma = prices.rolling(lookback).mean()
    sd = prices.rolling(lookback).std()
    return (prices - sma) / sd.replace(0, np.nan)


def moving_average(prices: pd.DataFrame, lookback: int) -> pd.DataFrame:
    return prices.rolling(lookback).mean()


def dollar_volume(prices: pd.DataFrame, volume: pd.DataFrame, lookback: int) -> pd.DataFrame:
    if volume.empty:
        return pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    return (prices * volume).rolling(lookback).mean()


def trading_cost_bps(prices: pd.DataFrame, volume: pd.DataFrame,
                     base_bps: float = 5.0, fallback_bps: float = 10.0,
                     floor_bps: float = 8.0, cap_bps: float = 120.0) -> pd.DataFrame:
    """Liquidity-aware per-name round-trip cost (bps of traded notional).

    A flat 10bps flatters small-cap names whose spreads alone run 30-100bps —
    exactly the names the biotech catalyst families trade. Model: half-spread +
    impact shrinking with the square root of dollar liquidity,

        cost = clip(base + 50 * sqrt($5M / ADV$), floor, cap)

    using a trailing 63-day median dollar volume, shifted one day (causal).
    Mega-caps land near the floor (~8bps); a $20M-ADV biotech ~30bps; an
    illiquid name saturates at the cap. Names without volume data fall back to
    the flat assumption rather than pretending precision.
    """
    if volume.empty:
        return pd.DataFrame(fallback_bps, index=prices.index, columns=prices.columns)
    adv = (prices * volume).rolling(63, min_periods=10).median().shift(1)
    cost = base_bps + 50.0 * np.sqrt(5e6 / adv.clip(lower=1e4))
    cost = cost.clip(lower=floor_bps, upper=cap_bps)
    return cost.fillna(fallback_bps).reindex(columns=prices.columns)


# ---- fundamental features (EDGAR) → as-filed point-in-time DataFrames ----
def _as_filed_frame(prices_index: pd.DatetimeIndex, fundamentals: dict,
                    score_fn) -> pd.DataFrame:
    """Build a dates x tickers frame from per-ticker scores stamped at filing date.

    Each score becomes available on its filing date and forward-fills until the
    next filing — strictly point-in-time, no lookahead.
    """
    cols = {}
    for ticker, series in fundamentals.items():
        events = score_fn(series)  # list of (filed_date, value)
        if not events:
            continue
        s = pd.Series({pd.to_datetime(d): v for d, v in events}).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        cols[ticker] = s.reindex(prices_index, method="ffill")
    if not cols:
        return pd.DataFrame(index=prices_index)
    return pd.DataFrame(cols).reindex(index=prices_index)


def beat_and_raise_scores(series: dict) -> list[tuple[str, float]]:
    """Score = QoQ EPS growth + revenue growth, positive when 'beat and raise'."""
    eps = series.get("eps", [])
    rev = series.get("revenue", [])
    out = []
    for seq in (eps, rev):
        for prev, cur in zip(seq, seq[1:]):
            if prev["val"] in (0, None):
                continue
            growth = (cur["val"] - prev["val"]) / abs(prev["val"])
            out.append((cur["filed"], float(np.clip(growth, -1, 1))))
    # combine same-filing-date scores by summing
    agg: dict[str, float] = {}
    for d, v in out:
        agg[d] = agg.get(d, 0.0) + v
    return sorted(agg.items())


def insider_scores(txns: list[dict]) -> list[tuple[str, float]]:
    """Net insider buy value, accumulated by filing date (positive = buying)."""
    agg: dict[str, float] = {}
    for t in txns:
        sign = 1.0 if t["code"] == "P" else -1.0
        agg[t["filed"]] = agg.get(t["filed"], 0.0) + sign * t["value"]
    return sorted(agg.items())


def cash_runway_scores(series: dict) -> list[tuple[str, float]]:
    """Quarters of cash runway = cash / quarterly burn (higher is safer)."""
    cash = series.get("cash", [])
    ocf = series.get("op_cash_flow", [])
    out = []
    ocf_by_filed = {p["filed"]: p["val"] for p in ocf}
    for c in cash:
        burn = ocf_by_filed.get(c["filed"])
        if burn is None or burn >= 0:
            out.append((c["filed"], 99.0))  # cash-flow positive → very safe
        else:
            out.append((c["filed"], float(c["val"] / abs(burn))))
    return out


def beat_and_raise_frame(bundle: FeatureBundle) -> pd.DataFrame:
    return _as_filed_frame(bundle.dates, bundle.fundamentals, beat_and_raise_scores)


def insider_frame(bundle: FeatureBundle) -> pd.DataFrame:
    insider = {t: s.get("insider", []) for t, s in bundle.fundamentals.items()}
    return _as_filed_frame(bundle.dates, insider, lambda s: insider_scores(s))


def cash_runway_frame(bundle: FeatureBundle) -> pd.DataFrame:
    return _as_filed_frame(bundle.dates, bundle.fundamentals, cash_runway_scores)


# ---- earnings surprise (Alpha Vantage EARNINGS, point-in-time by reportedDate) ----
def earnings_surprise_frame(bundle: FeatureBundle, hold_days: int = 63) -> pd.DataFrame:
    """Latest EPS surprise %, available from the report date, expiring after
    hold_days trading days (the classic PEAD window)."""
    cols = {}
    for ticker, events in bundle.earnings.items():
        if not events:
            continue
        pts = {}
        for e in events:
            d, s = e.get("reportedDate"), e.get("surprisePct")
            if d and s is not None:
                pts[pd.to_datetime(d)] = float(np.clip(s, -100, 100))
        if not pts:
            continue
        s = pd.Series(pts).sort_index()
        s = s[~s.index.duplicated(keep="last")]
        cols[ticker] = s.reindex(bundle.dates, method=None).ffill(limit=hold_days)
    if not cols:
        return pd.DataFrame(index=bundle.dates)
    return pd.DataFrame(cols).reindex(index=bundle.dates)


# ---- news sentiment (Alpha Vantage NEWS_SENTIMENT) ----
def news_sentiment_frame(bundle: FeatureBundle, lookback: int = 10) -> pd.DataFrame:
    """Relevance-weighted mean sentiment per ticker, rolled over `lookback` days."""
    cols = {}
    for ticker, articles in bundle.news.items():
        if not articles:
            continue
        df = pd.DataFrame(articles).dropna(subset=["date", "sentiment"])
        if df.empty:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df["w"] = df["relevance"].fillna(0.5)
        daily = df.groupby("date").apply(
            lambda g: float(np.average(g["sentiment"], weights=g["w"].clip(lower=0.01))),
            include_groups=False)
        cols[ticker] = daily.reindex(bundle.dates).rolling(lookback, min_periods=1).mean()
    if not cols:
        return pd.DataFrame(index=bundle.dates)
    return pd.DataFrame(cols).reindex(index=bundle.dates)


# ---- catalyst features (BPIQ) ----
def days_to_catalyst_frame(bundle: FeatureBundle) -> pd.DataFrame:
    """TRADING-day distance to each ticker's next catalyst (NaN if none ahead).

    Measured in trading days (positions in the price calendar), not calendar
    days — the entry/exit window params the catalyst families learn are trading
    days, so a calendar-day delta (``(timestamp - timestamp).days``) mis-times
    every window by ~1.4x.
    """
    if not bundle.catalysts:
        return pd.DataFrame(index=bundle.dates)
    dates = pd.DatetimeIndex(bundle.dates)
    n = len(dates)
    pos = np.arange(n)
    by_ticker: dict[str, list[pd.Timestamp]] = {}
    for c in bundle.catalysts:
        tk, cd = c.get("ticker"), c.get("catalyst_date")
        if tk not in bundle.prices.columns or not cd:
            continue
        try:
            cd_parsed = pd.to_datetime(cd)
        except (ValueError, TypeError):
            continue
        if pd.isna(cd_parsed):                          # NaT would break searchsorted ordering
            continue
        by_ticker.setdefault(tk, []).append(cd_parsed)
    cols = {}
    for tk, dates_list in by_ticker.items():
        cat_dates = pd.DatetimeIndex(sorted(dates_list))
        # drop catalysts before the panel starts — a past catalyst clamps to
        # position 0 and would otherwise read as "catalyst today" on day 0 and
        # mask the real upcoming one
        cat_dates = cat_dates[cat_dates >= dates[0]]
        if len(cat_dates) == 0:
            continue
        cat_pos = dates.searchsorted(cat_dates)        # trading-day index of each catalyst
        j = np.searchsorted(cat_pos, pos, side="left")  # next catalyst at/after each date
        vals = np.full(n, np.nan, dtype=float)
        ahead = j < len(cat_pos)
        vals[ahead] = cat_pos[j[ahead]] - pos[ahead]    # distance in trading days
        cols[tk] = pd.Series(vals, index=dates)
    return pd.DataFrame(cols).reindex(index=bundle.dates)


# ---- external biotech signals (point-in-time panels, three as_of semantics) ----
def external_signal_frame(bundle: FeatureBundle, signal_name: str) -> pd.DataFrame:
    """A dates x tickers point-in-time frame for an external signal.

    Returns an all-NaN frame when the external export is not loaded, so callers
    degrade gracefully (the family then emits no positions).
    """
    if bundle.external is None:
        return pd.DataFrame(index=bundle.dates, columns=bundle.tickers, dtype=float)
    return bundle.external.signal_panel(signal_name, bundle.dates, bundle.tickers)


def external_days_to_catalyst_frame(bundle: FeatureBundle,
                                    catalyst_types: tuple[str, ...] | None = None
                                    ) -> pd.DataFrame:
    """Trading-day distance to the next pinned external catalyst, by ticker."""
    if bundle.external is None:
        return pd.DataFrame(index=bundle.dates, columns=bundle.tickers, dtype=float)
    return bundle.external.days_to_catalyst(bundle.dates, bundle.tickers, catalyst_types)
