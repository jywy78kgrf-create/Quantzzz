#!/usr/bin/env python3
"""Distill raw historical option chains (with greeks) into compact daily signals.

The raw chains (~7 GB: data/historical/options/{TICKER}/{YYYY-MM-DD}.json.gz,
each a JSON array of per-contract objects) are FAR too big to commit. This
collapses each chain into a handful of point-in-time daily signals and writes
ONE small long-format parquet the research engine reads directly:

    data/snapshots/external/options_signals.parquet
    columns: ticker, as_of_date, signal_name, value, event_id   (event_id = NaN)

Signals produced per ticker/day (greeks used to do it right):
    iv_atm_30d/60d/90d/180d   ATM implied vol at each tenor (|delta|~0.5 contract)
    iv_term_structure_30_180  iv_atm_30d / iv_atm_180d
    iv_skew_25d               IV(25d put) - IV(25d call)  (signed; <0 = put skew)
    put_call_oi_ratio         sum(put OI) / sum(call OI)
    put_call_volume_ratio     sum(put vol) / sum(call vol)
    gamma_tilt                (call gamma*OI - put gamma*OI) / (call+put gamma*OI)
    total_vega                sum(vega * OI)            (vega-weighted positioning)
    iv_rank_252               percentile of iv_atm_30d in trailing 252 trading days

Run it on the machine that holds the raw data, then commit the parquet:
    python scripts/distill_options.py
    git add data/snapshots/external/options_signals.parquet && git commit && push
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os

import numpy as np
import pandas as pd

RAW_ROOT = "data/historical/options"
OUT_PATH = "data/snapshots/external/options_signals.parquet"
TENORS = (30, 60, 90, 180)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def _is_call(cp) -> bool:
    return str(cp).strip().lower() in ("c", "call")


def _add_iv_signals(df: pd.DataFrame, out: dict) -> dict:
    # the chain's own as-of date is implied by dte; compute dte per contract
    # using the file date passed via attribute on df
    asof = df.attrs["asof"]
    df = df.assign(dte=(df["expiry"] - asof).dt.days)
    df = df[df["dte"] > 0]
    if df.empty:
        return out

    atm = {}
    for T in TENORS:
        # nearest available expiry bucket to the tenor, then the |delta|~0.5 strike
        near = df.iloc[(df["dte"] - T).abs().argsort()[:200]]
        if near.empty:
            continue
        exp = near.iloc[(near["dte"] - T).abs().argsort()[0]]["expiry"]
        slab = df[df["expiry"] == exp]
        atm_iv = slab.iloc[(slab["delta"].abs() - 0.5).abs().argsort()[:2]]["iv"].mean()
        if np.isfinite(atm_iv):
            atm[T] = atm_iv
            out[f"iv_atm_{T}d"] = float(atm_iv)
    if 30 in atm and 180 in atm and atm[180] > 0:
        out["iv_term_structure_30_180"] = atm[30] / atm[180]

    # true 25-delta risk reversal at the ~30d expiry
    near30 = df.iloc[(df["dte"] - 30).abs().argsort()[:200]]
    if not near30.empty:
        exp = near30.iloc[(near30["dte"] - 30).abs().argsort()[0]]["expiry"]
        slab = df[df["expiry"] == exp]
        calls, puts = slab[slab.call], slab[~slab.call]
        if not calls.empty and not puts.empty:
            civ = calls.iloc[(calls["delta"] - 0.25).abs().argsort()[:1]]["iv"].mean()
            piv = puts.iloc[(puts["delta"] + 0.25).abs().argsort()[:1]]["iv"].mean()
            if np.isfinite(civ) and np.isfinite(piv):
                out["iv_skew_25d"] = float(piv - civ)
    return out


def distill(raw_root: str, out_path: str) -> None:
    recs = []
    tickers = sorted(d for d in os.listdir(raw_root)
                     if os.path.isdir(os.path.join(raw_root, d)))
    print(f"{len(tickers)} tickers under {raw_root}")
    for i, tk in enumerate(tickers, 1):
        per_day = []
        for fp in sorted(glob.glob(os.path.join(raw_root, tk, "*.json.gz"))):
            day = os.path.basename(fp)[:10]
            try:
                with gzip.open(fp, "rt") as fh:
                    contracts = json.load(fh)
            except Exception as e:  # noqa: BLE001
                print(f"  skip {tk}/{day}: {e}")
                continue
            sig = _signals_for_day(contracts, pd.Timestamp(day))
            for name, val in sig.items():
                recs.append((tk, day, name, float(val)))
                per_day.append((day, name, val))
        # second pass: IV rank of the 30d ATM IV over trailing 252 days
        _append_iv_rank(recs, tk, per_day)
        if i % 10 == 0 or i == len(tickers):
            print(f"  [{i}/{len(tickers)}] {tk}: {len(per_day)} day-signals")

    out = pd.DataFrame(recs, columns=["ticker", "as_of_date", "signal_name", "value"])
    out["event_id"] = np.nan
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    out.to_parquet(out_path, index=False)
    sz = os.path.getsize(out_path) / 1e6
    print(f"\nwrote {len(out):,} rows for {out['ticker'].nunique()} tickers "
          f"-> {out_path}  ({sz:.1f} MB)")


def _signals_for_day(contracts: list[dict], asof: pd.Timestamp) -> dict:
    rows = []
    for c in contracts:
        exp = c.get("expiry") or c.get("expiration")
        rows.append((
            _is_call(c.get("cp") or c.get("type") or c.get("option_type")),
            pd.Timestamp(exp) if exp else pd.NaT,
            _f(c.get("strike")), _f(c.get("iv") or c.get("implied_volatility")),
            _f(c.get("delta")), _f(c.get("gamma")), _f(c.get("vega")),
            _f(c.get("open_interest")), _f(c.get("volume")),
        ))
    df = pd.DataFrame(rows, columns=[
        "call", "expiry", "strike", "iv", "delta", "gamma", "vega", "oi", "vol"])
    df = df.dropna(subset=["expiry", "iv", "delta"])
    if df.empty:
        return {}
    df.attrs["asof"] = asof
    out: dict = {}
    coi, poi = df.loc[df.call, "oi"].sum(), df.loc[~df.call, "oi"].sum()
    cvol, pvol = df.loc[df.call, "vol"].sum(), df.loc[~df.call, "vol"].sum()
    if coi > 0:
        out["put_call_oi_ratio"] = poi / coi
    if cvol > 0:
        out["put_call_volume_ratio"] = pvol / cvol
    cg = (df.loc[df.call, "gamma"] * df.loc[df.call, "oi"]).sum()
    pg = (df.loc[~df.call, "gamma"] * df.loc[~df.call, "oi"]).sum()
    if (cg + pg) > 0:
        out["gamma_tilt"] = (cg - pg) / (cg + pg)
    out["total_vega"] = float((df["vega"] * df["oi"]).sum())
    return _add_iv_signals(df, out)


def _append_iv_rank(recs: list, ticker: str, per_day: list) -> None:
    s = pd.Series(
        {pd.Timestamp(d): v for d, n, v in per_day if n == "iv_atm_30d"}).sort_index()
    if len(s) < 30:
        return
    rank = s.rolling(252, min_periods=30).apply(
        lambda w: (w.iloc[-1] >= w).mean(), raw=False)
    for d, v in rank.dropna().items():
        recs.append((ticker, d.strftime("%Y-%m-%d"), "iv_rank_252", float(v)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=RAW_ROOT)
    ap.add_argument("--out", default=OUT_PATH)
    args = ap.parse_args()
    distill(args.raw, args.out)


if __name__ == "__main__":
    main()
