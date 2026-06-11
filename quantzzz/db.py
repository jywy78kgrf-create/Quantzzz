"""SQLite persistence layer: schema, connections, and query helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SCHEMA = """
-- data layer
CREATE TABLE IF NOT EXISTS api_cache (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    ttl_s INTEGER NOT NULL,
    payload BLOB
);
CREATE TABLE IF NOT EXISTS api_budget (
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    calls_used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, date)
);
CREATE TABLE IF NOT EXISTS data_health (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    ticker TEXT,
    status TEXT NOT NULL,           -- ok | stale | error | budget_exhausted
    detail TEXT
);

-- research
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY,
    desk TEXT NOT NULL,
    family TEXT NOT NULL,
    params_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'candidate',   -- candidate | promoted | retired
    origin TEXT NOT NULL,                       -- random | mutation | crossover | heuristic | llm
    created_ts TEXT NOT NULL,
    promoted_ts TEXT,
    retired_ts TEXT,
    parent_id INTEGER
);
CREATE TABLE IF NOT EXISTS research_runs (
    id INTEGER PRIMARY KEY,
    desk TEXT NOT NULL,
    started_ts TEXT NOT NULL,
    ended_ts TEXT,
    iterations INTEGER NOT NULL DEFAULT 0,
    promotions INTEGER NOT NULL DEFAULT 0,
    config_json TEXT
);
CREATE TABLE IF NOT EXISTS research_iterations (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    desk TEXT NOT NULL,
    iter_num INTEGER NOT NULL,
    strategy_id INTEGER,
    ts TEXT NOT NULL,
    is_sharpe REAL,
    oos_sharpe REAL,
    oos_alpha REAL,
    max_dd REAL,
    n_trades INTEGER,
    hit_rate REAL,
    fitness REAL,
    promoted INTEGER NOT NULL DEFAULT 0,
    fail_reasons TEXT,
    equity_curve_json TEXT
);

-- trading
CREATE TABLE IF NOT EXISTS accounts (
    fund TEXT PRIMARY KEY,
    cash REAL NOT NULL,
    starting_cash REAL NOT NULL,
    updated_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    fund TEXT NOT NULL,
    ts TEXT NOT NULL,
    strategy_id INTEGER,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                 -- buy | sell
    qty REAL NOT NULL,
    order_type TEXT NOT NULL DEFAULT 'market',
    status TEXT NOT NULL DEFAULT 'new', -- new | filled | rejected
    reject_reason TEXT,
    journal_id INTEGER
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    slippage_bps REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS positions (
    fund TEXT NOT NULL,
    ticker TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_ts TEXT NOT NULL,
    strategy_id INTEGER,
    stop_px REAL,
    PRIMARY KEY (fund, ticker)
);
CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY,
    fund TEXT NOT NULL,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    gross_exposure REAL NOT NULL,
    net_exposure REAL NOT NULL,
    drawdown REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY,
    fund TEXT NOT NULL,
    ts TEXT NOT NULL,
    strategy_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,            -- long | exit
    strength REAL NOT NULL,
    target_weight REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | taken | rejected | expired
    journal_id INTEGER
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    fund TEXT NOT NULL,
    strategy_id INTEGER,
    ticker TEXT NOT NULL,
    entry_ts TEXT NOT NULL,
    exit_ts TEXT,
    entry_px REAL NOT NULL,
    exit_px REAL,
    qty REAL NOT NULL,
    pnl REAL,
    pnl_pct REAL,
    exit_reason TEXT,
    reviewed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS fund_state (
    fund TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'normal',     -- normal | liquidate_only
    hwm REAL NOT NULL,
    halted_since TEXT,
    detail TEXT
);

-- journal & learning
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY,
    fund TEXT NOT NULL,
    ts TEXT NOT NULL,
    entry_type TEXT NOT NULL,   -- entry|exit|reject|resize|halt|skip|learning|promotion|llm_review
    ticker TEXT,
    action TEXT,
    inputs_json TEXT,
    reasoning TEXT,
    ref_table TEXT,
    ref_id INTEGER
);
CREATE TABLE IF NOT EXISTS strategy_performance (
    strategy_id INTEGER NOT NULL,
    fund TEXT NOT NULL,
    as_of_ts TEXT NOT NULL,
    n_closed INTEGER NOT NULL,
    hit_rate REAL,
    payoff REAL,
    realized_pnl REAL,
    avg_slippage_bps REAL,
    weight_multiplier REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (strategy_id, as_of_ts)
);

CREATE INDEX IF NOT EXISTS idx_iter_run ON research_iterations(run_id, iter_num);
CREATE INDEX IF NOT EXISTS idx_iter_desk ON research_iterations(desk, ts);
CREATE INDEX IF NOT EXISTS idx_journal_fund ON journal_entries(fund, ts);
CREATE INDEX IF NOT EXISTS idx_orders_fund ON orders(fund, ts);
CREATE INDEX IF NOT EXISTS idx_trades_fund ON trades(fund, exit_ts);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def insert(conn: sqlite3.Connection, table: str, **cols) -> int:
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    cur = conn.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", tuple(cols.values()))
    conn.commit()
    return cur.lastrowid


def query_df(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
