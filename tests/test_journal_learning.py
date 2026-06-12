from quantzzz.config import load_config
from quantzzz.db import insert, utcnow
from quantzzz.trading.journal import DecisionJournal
from quantzzz.trading.learning import LearningLoop


def test_journal_record(tmp_db):
    j = DecisionJournal(tmp_db, "equity")
    jid = j.record("entry", "buying because momentum", ticker="AAA", action="buy",
                   inputs={"strength": 0.5})
    row = tmp_db.execute("SELECT * FROM journal_entries WHERE id=?", (jid,)).fetchone()
    assert row["entry_type"] == "entry"
    assert row["ticker"] == "AAA"
    assert "momentum" in row["reasoning"]


def _seed_trades(conn, fund, strategy_id, pnls):
    insert(conn, "strategies", desk=fund, family="momentum", params_json="{}",
           spec_hash=f"h{strategy_id}", status="promoted", origin="random",
           created_ts=utcnow())
    for p in pnls:
        insert(conn, "trades", fund=fund, strategy_id=strategy_id, ticker="AAA",
               entry_ts=utcnow(), exit_ts=utcnow(), entry_px=100, exit_px=100 * (1 + p),
               qty=10, pnl=p * 1000, pnl_pct=p)


def test_learning_winner_increases_multiplier(tmp_db):
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1, [0.1, 0.15, 0.2, -0.05, 0.1] * 4)  # 20 trades
    j = DecisionJournal(tmp_db, "equity")
    loop = LearningLoop(cfg, "equity", tmp_db, j)
    loop.review()
    assert loop.current_multiplier(1) > 1.0
    assert loop.is_active(1)


def test_learning_patient_on_small_samples(tmp_db):
    """Few closed trades must not move the multiplier or retire anything."""
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1, [-0.1, -0.15, -0.2, -0.1, -0.08])
    loop = LearningLoop(cfg, "equity", tmp_db, DecisionJournal(tmp_db, "equity"))
    loop.review()
    assert loop.current_multiplier(1) == 1.0
    assert loop.is_active(1)


def test_learning_retires_persistent_loser(tmp_db):
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1,
                 [-0.1, -0.15, -0.2, 0.02, -0.1, -0.08, -0.05, -0.12, -0.09, -0.07] * 2)
    j = DecisionJournal(tmp_db, "equity")
    loop = LearningLoop(cfg, "equity", tmp_db, j)
    loop.review()
    assert not loop.is_active(1)
    assert loop.current_multiplier(1) <= 1.0
    row = tmp_db.execute("SELECT status FROM strategies WHERE id=1").fetchone()
    assert row["status"] == "retired"


def test_multiplier_clipped(tmp_db):
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1, [5.0] * 20)  # absurd wins
    loop = LearningLoop(cfg, "equity", tmp_db, DecisionJournal(tmp_db, "equity"))
    loop.review()
    assert loop.current_multiplier(1) <= 2.0


def test_learning_early_caution_deweights_clear_bleeders(tmp_db):
    """8-14 closed trades, negative P&L, <30% hits -> partial de-weight."""
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1, [-0.1, -0.12, -0.08, -0.15, -0.1,
                                       -0.09, -0.11, 0.05, -0.07])   # 9 trades
    loop = LearningLoop(cfg, "equity", tmp_db, DecisionJournal(tmp_db, "equity"))
    loop.review()
    assert 0.5 <= loop.current_multiplier(1) < 1.0
    assert loop.is_active(1)            # de-weighted, NOT retired


def test_learning_early_caution_spares_mixed_records(tmp_db):
    """Same small sample but a normal mixed record -> untouched."""
    cfg = load_config()
    _seed_trades(tmp_db, "equity", 1, [0.1, -0.05, 0.08, -0.04, 0.12,
                                       -0.06, 0.05, -0.03, 0.02])
    loop = LearningLoop(cfg, "equity", tmp_db, DecisionJournal(tmp_db, "equity"))
    loop.review()
    assert loop.current_multiplier(1) == 1.0
