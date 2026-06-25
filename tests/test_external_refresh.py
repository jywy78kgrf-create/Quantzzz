"""The live extension appends only post-export observations, idempotently."""

from __future__ import annotations

import dataclasses
import json

import pandas as pd
import pytest

from quantzzz.config import load_config
from quantzzz.data.external_refresh import refresh_external_signals
from quantzzz.data.external_signals import load_external_signals


@pytest.fixture
def ext_env(tmp_path):
    snap = tmp_path / "snapshots"
    ext = snap / "external"
    ext.mkdir(parents=True)
    pd.DataFrame({
        "ticker": ["AAA", "AAA"],
        "as_of_date": ["2026-01-02", "2026-01-05"],
        "signal_name": ["iv_atm_30d", "iv_atm_30d"],
        "value": [0.8, 0.9],
        "event_id": [None, None],
    }).to_parquet(ext / "signal_history_export.parquet", index=False)
    pd.DataFrame({
        "event_id": [1], "ticker": ["AAA"], "catalyst_type": ["PDUFA"],
        "catalyst_date": ["2026-03-01"], "indication_text": ["x"],
        "is_cns": [0], "status": ["upcoming"],
    }).to_csv(ext / "catalyst_events_export.csv", index=False)

    (snap / "av_options").mkdir()
    (snap / "av_options" / "AAA.json").write_text(json.dumps([
        # same day as export -> must NOT append; next day -> must append
        {"date": "2026-01-05", "mean_call_iv": 1.0, "mean_put_iv": 0.8,
         "put_call_volume_ratio": 0.5, "total_volume": 100},
        {"date": "2026-01-06", "mean_call_iv": 1.1, "mean_put_iv": 0.9,
         "put_call_volume_ratio": 0.4, "total_volume": 120},
    ]))
    (snap / "edgar").mkdir()
    (snap / "edgar" / "AAA.json").write_text(json.dumps({
        "insider": [{"filed": "2026-01-06", "code": "P", "value": 250000}],
    }))
    (snap / "bpiq").mkdir()
    (snap / "bpiq" / "catalysts.json").write_text(json.dumps([
        {"ticker": "AAA", "catalyst_date": "2026-03-01",     # dup of export event
         "stage_event": {"stage_label": "", "event_label": "PDUFA decision"}},
        {"ticker": "BBB", "catalyst_date": "2026-04-01",     # genuinely new
         "stage_event": {"stage_label": "Phase 3", "event_label": "Data readout"}},
    ]))
    return dataclasses.replace(load_config(), snapshot_dir=snap), ext


def test_appends_only_past_the_export_frontier(ext_env):
    cfg, ext = ext_env
    out = refresh_external_signals(cfg)
    live = pd.read_parquet(ext / "signal_history_live.parquet")
    iv = live[live["signal_name"] == "iv_atm_30d"]
    assert list(iv["as_of_date"]) == ["2026-01-06"]      # 01-05 belongs to the export
    assert {"risk_reversal_25d", "put_call_volume_ratio", "total_volume",
            "insider_net_purchase_value_90d",
            "insider_any_purchase_90d"} <= set(live["signal_name"])
    assert out["events_appended"] == 1                   # AAA event deduped, BBB added
    ev = pd.read_csv(ext / "catalyst_events_live.csv")
    assert ev["event_id"].min() >= 1_000_000 and list(ev["ticker"]) == ["BBB"]


def test_idempotent_rerun_appends_nothing(ext_env):
    cfg, ext = ext_env
    refresh_external_signals(cfg)
    first = len(pd.read_parquet(ext / "signal_history_live.parquet"))
    out2 = refresh_external_signals(cfg)
    assert out2["signal_rows_appended"] == 0
    assert out2["events_appended"] == 0
    assert len(pd.read_parquet(ext / "signal_history_live.parquet")) == first


def test_loader_merges_live_with_export_precedence(ext_env):
    cfg, ext = ext_env
    refresh_external_signals(cfg)
    ext_sig = load_external_signals(cfg.snapshot_dir)
    iv = ext_sig.history[(ext_sig.history["signal_name"] == "iv_atm_30d")
                         & (ext_sig.history["ticker"] == "AAA")].sort_values("as_of_date")
    # export rows intact, live day appended, no duplicate for 01-05
    assert list(iv["as_of_date"].dt.strftime("%Y-%m-%d")) == \
        ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert iv["value"].iloc[1] == 0.9                    # export value wins on 01-05
    assert 1_000_000 in set(ext_sig.events["event_id"])  # live event pinned


def test_backfilled_older_days_still_append(ext_env):
    """Out-of-order (backfilled) observations land as long as they postdate
    the export frontier and aren't already in the live file."""
    cfg, ext = ext_env
    refresh_external_signals(cfg)                      # live now has 2026-01-06
    snap = cfg.snapshot_dir
    import json as _json
    f = snap / "av_options" / "AAA.json"
    recs = _json.loads(f.read_text())
    # a backfilled chain for a day BETWEEN export end and the existing live row,
    # written by the vendor-grade path
    recs.insert(1, {"date": "2026-01-05", "atm_iv_30d": 9.9})   # pre-frontier: ignored
    recs.insert(1, {"date": "2026-01-05T2"})                     # malformed: ignored
    recs.append({"date": "2026-01-07", "atm_iv_30d": 1.23,
                 "rr_25d": 0.05, "total_open_interest": 500})
    f.write_text(_json.dumps(recs))
    out = refresh_external_signals(cfg)
    assert out["signal_rows_appended"] >= 3
    import pandas as pd
    live = pd.read_parquet(ext / "signal_history_live.parquet")
    iv = live[live["signal_name"] == "iv_atm_30d"].sort_values("as_of_date")
    assert "2026-01-07" in set(iv["as_of_date"])
    assert "2026-01-05" not in set(iv["as_of_date"])   # export frontier respected
    assert "total_open_interest" in set(live["signal_name"])
