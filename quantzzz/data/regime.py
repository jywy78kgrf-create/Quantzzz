"""Market-level volatility-regime signal from the CBOE index complex.

The core is the VIX term structure: VIX (30-day implied vol) vs VIX3M (3-month).
In calm markets the curve is in contango (VIX < VIX3M, ratio < 1); as stress
builds the front end spikes and the curve inverts into backwardation (ratio > 1).
That ratio, scored against its own recent history alongside the VIX level, is a
daily, long-only-compatible read on whether to lean into or out of risk.

Phase 1 is observe-only: this computes and surfaces the regime; it does NOT yet
scale exposure. The series are read from the snapshot store (populated by
refresh_vol_indices via INDEX_DATA), so if that data isn't present yet the whole
thing returns None and the cockpit simply shows no regime — never an error.
"""

from __future__ import annotations


def _close(store, symbol):
    df = store.load_prices(symbol)
    if df is None or df.empty or "close" not in df:
        return None
    s = df["close"].dropna()
    return s if not s.empty else None


def _pctile(s, lookback: int) -> float:
    """Where the latest value sits within its trailing window, in [0, 1]."""
    tail = s.iloc[-lookback:]
    return float((tail <= tail.iloc[-1]).mean())


def vol_regime(store, lookback: int = 252) -> dict | None:
    """Term-structure regime read, or None if VIX/VIX3M aren't available yet.

    score in [0, 1]: 0 = calm (deep contango, low VIX), 1 = stress (backwardation,
    high VIX). Weighted toward the term-structure slope, which leads the level.
    """
    vix, vix3m = _close(store, "VIX"), _close(store, "VIX3M")
    if vix is None or vix3m is None:
        return None
    idx = vix.index.intersection(vix3m.index)
    if len(idx) < 30:
        return None
    vix, vix3m = vix.reindex(idx), vix3m.reindex(idx)
    ratio = vix / vix3m
    ratio_pct, vix_pct = _pctile(ratio, lookback), _pctile(vix, lookback)
    score = round(0.6 * ratio_pct + 0.4 * vix_pct, 3)
    label = "stress" if score >= 0.8 else "elevated" if score >= 0.6 else "calm"
    out = {
        "asof": str(idx[-1].date()),
        "vix": round(float(vix.iloc[-1]), 2),
        "vix3m": round(float(vix3m.iloc[-1]), 2),
        "ratio": round(float(ratio.iloc[-1]), 3),     # <1 contango, >1 backwardation
        "ratio_pctile": round(ratio_pct, 2),
        "vix_pctile": round(vix_pct, 2),
        "score": score,
        "label": label,
    }
    for extra in ("VIX9D", "VVIX", "SKEW"):
        s = _close(store, extra)
        if s is not None:
            out[extra.lower()] = round(float(s.iloc[-1]), 2)
    return out
