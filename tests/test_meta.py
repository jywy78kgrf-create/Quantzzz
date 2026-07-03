"""Meta-learning: per-family forward-survival scoring is sample-aware (neutral
until evidence), and only ever tightens the gate for chronic forward-failers."""

from quantzzz.db import insert
from quantzzz.research import meta


def _strategy(conn, sid, family, desk="equity"):
    conn.execute(
        "INSERT INTO strategies (id,desk,family,params_json,spec_hash,status,origin,created_ts)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (sid, desk, family, "{}", f"h{sid}", "promoted", "random", "2026-01-01"))


def _live_trades(conn, sid, n, pnl_each):
    for k in range(n):
        insert(conn, "trades", fund="equity", strategy_id=sid, ticker="X",
               entry_ts="2026-01-01", exit_ts="2026-02-01", entry_px=10.0, exit_px=10.0,
               qty=1.0, pnl=pnl_each, source="live")


def test_forward_scores_are_sample_aware(tmp_db):
    # momentum: two strategies, both LOSING forward with a real sample -> low score
    _strategy(tmp_db, 1, "momentum"); _live_trades(tmp_db, 1, 15, -50.0)
    _strategy(tmp_db, 2, "momentum"); _live_trades(tmp_db, 2, 15, -30.0)
    # beat_and_raise: a winner with a real sample -> high score
    _strategy(tmp_db, 3, "beat_and_raise"); _live_trades(tmp_db, 3, 15, +40.0)
    # earnings_surprise: only a thin sample (< MIN_LIVE_CLOSED) -> excluded entirely
    _strategy(tmp_db, 4, "earnings_surprise"); _live_trades(tmp_db, 4, 5, +40.0)
    tmp_db.commit()

    scores = meta.family_forward_scores(tmp_db, "equity")
    assert scores["momentum"] < meta.NEUTRAL          # chronic forward failer
    assert scores["beat_and_raise"] > meta.NEUTRAL    # survives forward
    assert "earnings_surprise" not in scores          # too thin to count


def test_gate_only_tightens_and_is_capped():
    assert meta.gate_factor(None) == 1.0              # no data -> no change
    assert meta.gate_factor(meta.NEUTRAL) == 1.0      # neutral -> no change
    assert meta.gate_factor(0.7) == 1.0               # better than neutral -> never loosens
    f_bad = meta.gate_factor(0.1)                      # chronic failer -> tighten
    assert 1.0 < f_bad <= meta.MAX_TIGHTEN
    assert meta.gate_factor(0.0) == meta.MAX_TIGHTEN  # worst case hits the cap


def test_search_weight_favors_survivors_with_a_floor():
    assert meta.search_weight(0.9) > meta.search_weight(0.2)   # favor what survives
    assert meta.search_weight(0.0) >= 0.3                       # never fully abandoned
    assert meta.search_weight(None) == 1.0                      # neutral default
