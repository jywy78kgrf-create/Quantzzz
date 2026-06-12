"""Extend the external signal history forward from live snapshot sources.

The committed export (``signal_history_export.parquet``) is a frozen discovery
artifact — it ends where the external scan ended. The contaminated-discovery
verdict, however, depends on *uncontaminated* data accruing after that point:
the event-anchored bench promotes (or decays) only as post-discovery history
arrives. This module is that supply line.

Each refresh appends new observations to ``signal_history_live.parquet`` /
``catalyst_events_live.csv`` (the frozen export is never touched), using the
same long schema. The loader concatenates both, with the export taking
precedence on any overlapping (ticker, signal, day).

Methodology honesty — the live values are *approximations* of the export's
definitions, derived from the daily Alpha Vantage options summaries:

* ``iv_atm_30d``      ≈ mean of chain-wide call/put mean IV (the export used a
  true ATM 30d tenor). Level differences are absorbed by the cross-sectional
  ranking the strategies apply; a level jump at the export/live boundary is
  possible and tolerated.
* ``risk_reversal_25d`` ≈ mean call IV − mean put IV (export: 25-delta RR).
  Only consumed downstream in unsigned |RR| form.
* ``put_call_volume_ratio`` / ``total_volume`` — same definition as export.
* insider signals — recomputed from EDGAR Form-4 extracts with the same
  trailing-90-day window, stamped on filing dates (point-in-time by
  construction).

Signals that cannot be honestly extended from current sources (per-strike OI,
term structure, skew) are simply not extended; their panels go stale past the
export horizon and strategies ranking on them see NaN — which is the truthful
representation of not having the data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import Config
from .external_signals import EXTERNAL_DIR, _EVENTS_FILE, _HISTORY_FILE
from .snapshots import SnapshotStore

LIVE_HISTORY_FILE = "signal_history_live.parquet"
LIVE_EVENTS_FILE = "catalyst_events_live.csv"
_LIVE_EVENT_ID_BASE = 1_000_000     # never collides with the export's ids

_HISTORY_COLS = ["ticker", "as_of_date", "signal_name", "value", "event_id"]


# ---- candidate observations from snapshot sources ----
def _options_rows(snapshot_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for f in sorted((snapshot_dir / "av_options").glob("*.json")):
        try:
            recs = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if not isinstance(recs, list):
            recs = [recs]
        for r in recs:
            d = r.get("date")
            if not d:
                continue
            ci, pi = r.get("mean_call_iv"), r.get("mean_put_iv")
            if ci is not None and pi is not None:
                rows.append({"ticker": f.stem, "as_of_date": d,
                             "signal_name": "iv_atm_30d",
                             "value": (float(ci) + float(pi)) / 2, "event_id": None})
                rows.append({"ticker": f.stem, "as_of_date": d,
                             "signal_name": "risk_reversal_25d",
                             "value": float(ci) - float(pi), "event_id": None})
            for src, name in (("put_call_volume_ratio", "put_call_volume_ratio"),
                              ("total_volume", "total_volume")):
                if r.get(src) is not None:
                    rows.append({"ticker": f.stem, "as_of_date": d,
                                 "signal_name": name,
                                 "value": float(r[src]), "event_id": None})
    return rows


def _insider_rows(snapshot_dir: Path) -> list[dict]:
    """Trailing-90d insider net purchase value / any-purchase flag, one
    observation per Form-4 filing date (the day the value became knowable)."""
    rows: list[dict] = []
    for f in sorted((snapshot_dir / "edgar").glob("*.json")):
        try:
            series = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        txns = series.get("insider") or []
        events = []
        for t in txns:
            filed, code, value = t.get("filed"), t.get("code"), t.get("value")
            if not filed or value is None:
                continue
            sign = 1.0 if code == "P" else -1.0
            events.append((pd.Timestamp(filed), sign * float(value), code))
        events.sort()
        for i, (filed, _, _) in enumerate(events):
            lo = filed - pd.Timedelta(days=90)
            window = [(v, c) for d, v, c in events[:i + 1] if d > lo]
            net = sum(v for v, _ in window)
            any_buy = float(any(c == "P" for _, c in window))
            d = filed.strftime("%Y-%m-%d")
            rows.append({"ticker": f.stem, "as_of_date": d,
                         "signal_name": "insider_net_purchase_value_90d",
                         "value": net, "event_id": None})
            rows.append({"ticker": f.stem, "as_of_date": d,
                         "signal_name": "insider_any_purchase_90d",
                         "value": any_buy, "event_id": None})
    return rows


_STAGE_TO_TYPE = {
    "phase 3": "Phase3", "phase 2/3": "Phase2/3", "phase 2": "Phase2",
    "phase 1/2": "Phase1/2", "phase 1": "Phase1",
}


def _event_rows(store: SnapshotStore) -> list[dict]:
    cats = store.load_json("bpiq/catalysts.json") or []
    out = []
    for c in cats:
        tk, cd = c.get("ticker"), c.get("catalyst_date")
        if not tk or not cd:
            continue
        se = c.get("stage_event") or {}
        label = f"{se.get('stage_label') or ''} {se.get('event_label') or ''}".lower()
        if "pdufa" in label:
            ctype = "PDUFA"
        else:
            ctype = next((v for k, v in _STAGE_TO_TYPE.items()
                          if k in (se.get("stage_label") or "").lower()), "Other")
        out.append({"ticker": tk, "catalyst_type": ctype, "catalyst_date": cd,
                    "indication_text": c.get("drug_name") or "",
                    "is_cns": 0, "status": "upcoming"})
    return out


# ---- the refresh ----
def refresh_external_signals(cfg: Config) -> dict:
    """Append post-export observations to the live extension files."""
    base = Path(cfg.snapshot_dir) / EXTERNAL_DIR
    export_path = base / _HISTORY_FILE
    if not export_path.exists():
        return {"skipped": "no external export present"}
    store = SnapshotStore(cfg.snapshot_dir)

    live_path = base / LIVE_HISTORY_FILE
    existing_live = (pd.read_parquet(live_path) if live_path.exists()
                     else pd.DataFrame(columns=_HISTORY_COLS))

    cand = pd.DataFrame(
        _options_rows(Path(cfg.snapshot_dir)) + _insider_rows(Path(cfg.snapshot_dir)),
        columns=_HISTORY_COLS)
    appended = 0
    if not cand.empty:
        cand["as_of_date"] = pd.to_datetime(cand["as_of_date"]).dt.strftime("%Y-%m-%d")
        # frontier: last as_of per (ticker, signal) across export + live. Only
        # strictly newer observations are appended — the frozen export always
        # wins on overlap, and re-runs are idempotent.
        export_max = (pd.read_parquet(export_path,
                                      columns=["ticker", "as_of_date", "signal_name"])
                      .groupby(["ticker", "signal_name"])["as_of_date"].max())
        live_max = (existing_live.groupby(["ticker", "signal_name"])["as_of_date"].max()
                    if not existing_live.empty else pd.Series(dtype=object))
        frontier = pd.concat([export_max, live_max]).groupby(level=[0, 1]).max()
        keyed = cand.set_index(["ticker", "signal_name"])
        cutoff = frontier.reindex(keyed.index).fillna("")
        new = keyed[keyed["as_of_date"] > cutoff.to_numpy()].reset_index()
        new = new.drop_duplicates(["ticker", "signal_name", "as_of_date"], keep="last")
        if not new.empty:
            merged = pd.concat([existing_live, new[_HISTORY_COLS]], ignore_index=True)
            merged = merged.drop_duplicates(["ticker", "signal_name", "as_of_date"],
                                            keep="first")
            base.mkdir(parents=True, exist_ok=True)
            merged.to_parquet(live_path, index=False)
            appended = len(new)

    # ---- pinned-event calendar extension ----
    ev_export = pd.read_csv(base / _EVENTS_FILE)
    live_ev_path = base / LIVE_EVENTS_FILE
    ev_live = (pd.read_csv(live_ev_path) if live_ev_path.exists()
               else pd.DataFrame(columns=ev_export.columns))
    known = set(map(tuple, pd.concat([ev_export, ev_live])[
        ["ticker", "catalyst_date", "catalyst_type"]].astype(str).to_numpy()))
    fresh = [r for r in _event_rows(store)
             if (str(r["ticker"]), str(r["catalyst_date"]), str(r["catalyst_type"]))
             not in known]
    if fresh:
        next_id = int(max([_LIVE_EVENT_ID_BASE - 1] + ev_live["event_id"].tolist())) + 1
        for i, r in enumerate(fresh):
            r["event_id"] = next_id + i
        ev_live = pd.concat([ev_live, pd.DataFrame(fresh)[ev_export.columns]],
                            ignore_index=True)
        ev_live.to_csv(live_ev_path, index=False)

    return {"signal_rows_appended": appended,
            "live_rows_total": int(len(existing_live) + appended),
            "events_appended": len(fresh)}
