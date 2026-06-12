"""External biotech signal export → point-in-time feature panels.

The desk ingests three committed artifacts under ``data/snapshots/external/``:

* ``signal_history_export.parquet`` — long-format signal observations with the
  columns ``ticker, as_of_date, signal_name, value, event_id``. The export mixes
  **three different ``as_of`` semantics** that must each be handled point-in-time
  to avoid look-ahead:

  1. **Pre-catalyst candle days** — the equity/price-derived signals
     (``equity_return_vs_t180``, ``rsi_14d``, ``atr_14d``, ``equity_volume_ratio``).
     Every row carries an ``event_id`` and ``as_of_date`` is a trading day inside
     that catalyst's ~180-day run-up window. The same (ticker, day) recurs under
     overlapping events, so we de-duplicate to the last observation.
  2. **Options market days** — IV / skew / risk-reversal / open-interest signals.
     ``event_id`` is null; each is a per-ticker time series stamped on the day the
     options market printed it. Available from that day forward, with staleness.
  3. **SEC filing dates** — the insider signals (``insider_*_90d``). ``event_id``
     is null; each value becomes known on its Form-4 filing date and stays valid
     across the trailing-90-day window it summarizes.

* ``catalyst_events_export.csv`` — the pinned catalyst calendar
  (``event_id, ticker, catalyst_type, catalyst_date, indication_text, is_cns,
  status``). The ``event_id`` values here are the anchors the candle signals were
  pinned to; the event-anchored strategy family trades off this calendar.

* ``signal_spec_extract.csv`` — the research provenance / reconciliation spec.
  Its flags are encoded as the deny-list and transforms below; see
  ``RECONCILIATION_NOTES``.

Reconciliation flags from the spec (encoded, not re-litigated here):

* ``short_float`` and ``insider_own`` — P1 look-ahead FAIL (bpiq snapshot has no
  temporal filter). Excluded entirely; never surfaced as a feature.
* ``rc_*`` resolved-catalyst signals — P1 look-ahead UNCERTAIN, pending a
  temporal audit of the ``pre_resolution_*`` computation. Excluded until cleared.
* Risk-reversal — bimodal; the signed form's edge (9.75pp) is an artifact of the
  unsigned magnitude (|RR| 15.49pp). Exposed in **unsigned ``abs`` form only**.
* Correlated clusters — only one member counts. Cluster 1 is the ATM-IV tenor
  ladder (t5/t30/t60/t90/t180, pairwise rho up to 0.88); we expose a single
  canonical tenor (``iv_atm_30d``) as the rankable IV signal. Cluster 2 is the
  ``rc_*`` family, already excluded.

Every panel returned is strictly point-in-time: a value at ``date`` reflects only
observations with ``as_of_date <= date`` (subject to a per-class staleness
tolerance), and the backtester additionally lags weights one bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

EXTERNAL_DIR = "external"
_HISTORY_FILE = "signal_history_export.parquet"
_EVENTS_FILE = "catalyst_events_export.csv"

# ---- signal classes (drive the as_of handling + staleness tolerance) ----
CANDLE_SIGNALS = (
    "equity_return_vs_t180", "equity_volume_ratio", "rsi_14d", "atr_14d",
)
OPTIONS_SIGNALS = (
    "iv_atm_30d", "iv_atm_60d", "iv_atm_90d", "iv_atm_180d",
    "iv_skew_25d", "iv_term_structure_30_180",
    "risk_reversal_25d", "risk_reversal_10d",
    "put_call_oi_ratio", "put_call_volume_ratio",
    "total_open_interest", "total_volume",
)
INSIDER_SIGNALS = (
    "insider_net_purchase_value_90d", "insider_any_purchase_90d",
)

# Point-in-time staleness tolerance (calendar days) by signal class. A carried
# value older than this is treated as unknown (NaN) rather than stale-but-live.
_TOL_CANDLE = 4         # daily series; bridge weekends/holidays only
_TOL_OPTIONS = 10       # options prints gap when a name is thinly optioned
_TOL_INSIDER = 100      # the 90d net-purchase window stays meaningful that long

# ---- reconciliation deny-list (spec-driven; see module docstring) ----
EXCLUDED_SIGNALS = frozenset({
    "short_float",            # P1 look-ahead FAIL (bpiq snapshot, no temporal filter)
    "insider_own",            # P1 look-ahead FAIL (same snapshot issue)
    "rc_vol_ratio",           # P1 UNCERTAIN — temporal audit pending
    "rc_vol_ratio_180d",
    "rc_vol_ratio_cat",
    "risk_reversal_25d",      # signed form excluded; use abs_risk_reversal_25d
    "risk_reversal_10d",
})

# Correlated-cluster representatives: only the canonical member is rankable.
IV_CLUSTER = ("iv_atm_30d", "iv_atm_60d", "iv_atm_90d", "iv_atm_180d")
IV_CLUSTER_REPRESENTATIVE = "iv_atm_30d"

# Signals a strategy family is allowed to rank/score on. Unsigned |RR| is the
# only risk-reversal exposure; only the canonical IV tenor is offered.
RANKABLE_SIGNALS = (
    "iv_atm_30d",                 # Cluster-1 representative (one member counts)
    "abs_risk_reversal_25d",      # unsigned |RR| only
    "put_call_oi_ratio",          # bullish-positioning (low = call-heavy)
    "total_open_interest",        # options interest / event attention
    "insider_net_purchase_value_90d",
)

RECONCILIATION_NOTES = {
    "short_float": "excluded — P1 look-ahead FAIL (bpiq snapshot)",
    "insider_own": "excluded — P1 look-ahead FAIL (bpiq snapshot)",
    "rc_*": "excluded — P1 look-ahead UNCERTAIN, temporal audit pending",
    "risk_reversal": "unsigned |RR| only (bimodal; signed edge is a magnitude artifact)",
    "iv_cluster": f"only {IV_CLUSTER_REPRESENTATIVE} counts among {IV_CLUSTER}",
}

# Catalyst-type groupings for the event-anchored family.
PIVOTAL_TYPES = ("PDUFA", "Phase3", "Phase2/3")
TRADEABLE_STATUS = ("occurred", "upcoming")


@dataclass
class ExternalSignals:
    """Point-in-time access to the external signal export.

    Panels are built lazily and cached against a fixed price calendar (the
    research bundle's full date index), so each signal is computed once and
    sliced per walk-forward window downstream.
    """

    history: pd.DataFrame                 # ticker, as_of_date(ts), signal_name, value, event_id
    events: pd.DataFrame                  # event_id, ticker, catalyst_type, catalyst_date(ts), ...
    _cache: dict = field(default_factory=dict, repr=False)

    # ---- point-in-time panel for one signal ----
    def signal_panel(self, signal_name: str, dates: pd.DatetimeIndex,
                     tickers: list[str]) -> pd.DataFrame:
        """A dates x tickers point-in-time frame for ``signal_name``.

        ``abs_risk_reversal_25d`` is a derived feature: the unsigned magnitude of
        the (excluded) signed ``risk_reversal_25d`` series. All other names map
        straight to the export.
        """
        key = (signal_name, id(dates))
        if key in self._cache:
            return self._cache[key]

        if signal_name == "abs_risk_reversal_25d":
            base = self._raw_panel("risk_reversal_25d", dates, tickers, _TOL_OPTIONS)
            panel = base.abs()
        else:
            tol = self._tolerance(signal_name)
            panel = self._raw_panel(signal_name, dates, tickers, tol)
        self._cache[key] = panel
        return panel

    @staticmethod
    def _tolerance(signal_name: str) -> int:
        if signal_name in CANDLE_SIGNALS:
            return _TOL_CANDLE
        if signal_name in INSIDER_SIGNALS:
            return _TOL_INSIDER
        return _TOL_OPTIONS

    def _raw_panel(self, signal_name: str, dates: pd.DatetimeIndex,
                   tickers: list[str], tol_days: int) -> pd.DataFrame:
        sub = self.history[self.history["signal_name"] == signal_name]
        if sub.empty:
            return pd.DataFrame(index=dates, columns=tickers, dtype=float)
        tol = pd.Timedelta(days=tol_days)
        left = pd.DataFrame({"as_of_date": dates})
        cols: dict[str, pd.Series] = {}
        wanted = set(tickers)
        for tk, g in sub.groupby("ticker", sort=False):
            if tk not in wanted:
                continue
            # collapse duplicate as_of (overlapping pre-catalyst windows) to last
            g = (g.dropna(subset=["value"])
                   .sort_values("as_of_date")
                   .drop_duplicates("as_of_date", keep="last"))
            if g.empty:
                continue
            merged = pd.merge_asof(
                left, g[["as_of_date", "value"]], on="as_of_date",
                direction="backward", tolerance=tol)
            cols[tk] = merged["value"].to_numpy()
        if not cols:
            return pd.DataFrame(index=dates, columns=tickers, dtype=float)
        out = pd.DataFrame(cols, index=dates)
        return out.reindex(columns=tickers)

    # ---- event calendar → days-to-next-catalyst (pinned event_ids) ----
    def days_to_catalyst(self, dates: pd.DatetimeIndex, tickers: list[str],
                         catalyst_types: tuple[str, ...] | None = None) -> pd.DataFrame:
        """Trading-day distance to each ticker's next pinned catalyst.

        Uses the export's pinned ``event_id`` calendar (richer than the BPIQ
        bundle). ``catalyst_types`` optionally restricts to e.g. pivotal events.
        Past/cancelled rows without a usable date are dropped.
        """
        ev = self.events
        ev = ev[ev["status"].isin(TRADEABLE_STATUS)]
        ev = ev[ev["catalyst_date"].notna()]
        if catalyst_types:
            ev = ev[ev["catalyst_type"].isin(catalyst_types)]
        cols: dict[str, pd.Series] = {}
        date_vals = dates.to_numpy(dtype="datetime64[ns]")
        wanted = set(tickers)
        for tk, g in ev.groupby("ticker", sort=False):
            if tk not in wanted:
                continue
            cat = np.sort(g["catalyst_date"].to_numpy(dtype="datetime64[ns]"))
            idx = np.searchsorted(cat, date_vals, side="left")
            vals = np.full(len(date_vals), np.nan)
            has_next = idx < len(cat)
            vals[has_next] = (cat[idx[has_next]] - date_vals[has_next]) / np.timedelta64(1, "D")
            cols[tk] = pd.Series(vals, index=dates)
        if not cols:
            return pd.DataFrame(index=dates, columns=tickers, dtype=float)
        return pd.DataFrame(cols).reindex(columns=tickers)


def load_external_signals(snapshot_dir: Path) -> ExternalSignals | None:
    """Load the committed external export plus the live extension, if any.

    The frozen discovery export never changes; ``signal_history_live.parquet``
    and ``catalyst_events_live.csv`` (written by ``external_refresh``) extend it
    forward with post-discovery observations. On any overlapping
    (ticker, signal, day) the export wins.
    """
    base = Path(snapshot_dir) / EXTERNAL_DIR
    hist_path = base / _HISTORY_FILE
    ev_path = base / _EVENTS_FILE
    if not hist_path.exists() or not ev_path.exists():
        return None

    history = pd.read_parquet(hist_path)
    live_path = base / "signal_history_live.parquet"
    if live_path.exists():
        live = pd.read_parquet(live_path)
        history = pd.concat([history, live], ignore_index=True)
        history = history.drop_duplicates(
            ["ticker", "signal_name", "as_of_date"], keep="first")
    history["as_of_date"] = pd.to_datetime(history["as_of_date"])
    # drop any deny-listed raw signal up front (defence in depth; the rankable
    # set already excludes them, but this keeps panels from ever materializing).
    drop = EXCLUDED_SIGNALS - {"risk_reversal_25d"}  # keep signed RR for |RR| derivation
    history = history[~history["signal_name"].isin(drop)]

    events = pd.read_csv(ev_path)
    live_ev_path = base / "catalyst_events_live.csv"
    if live_ev_path.exists():
        events = pd.concat([events, pd.read_csv(live_ev_path)], ignore_index=True)
        events = events.drop_duplicates("event_id", keep="first")
    events["catalyst_date"] = pd.to_datetime(events["catalyst_date"], errors="coerce")
    return ExternalSignals(history=history, events=events)
