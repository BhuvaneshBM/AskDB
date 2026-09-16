"""The RESULTS database. A small local SQLite file that stores benchmark scores.

This is NOT one of the databases AskDB answers questions about -- those are
opened directly, per query, by schema.py and execute.py, and this module never
touches them. Keeping the two apart is what §20 (`cli.py results`) relies on:
it points the *same* read path at RESULTS_DB that every other query uses, so
"ask the project about its own results" is not a special case.

Synchronous, one connection -- this is a CLI, one query at a time.
"""

from __future__ import annotations

import sqlite3

from .config import RESULTS_DB

_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL,
    config_name   TEXT    NOT NULL,
    db_id         TEXT    NOT NULL,
    question      TEXT    NOT NULL,
    gold_sql      TEXT    NOT NULL,
    predicted_sql TEXT,
    correct       INTEGER NOT NULL,
    executable    INTEGER NOT NULL,
    blocked       INTEGER NOT NULL DEFAULT 0,
    repairs       INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    latency_ms    INTEGER NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS eval_results_run ON eval_results (run_id);
CREATE INDEX IF NOT EXISTS eval_results_config ON eval_results (config_name);
"""

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        RESULTS_DB.parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit. Each INSERT during a 200-question
        # benchmark run is durable immediately; there is no batch to lose if the
        # run is interrupted at question 143.
        _conn = sqlite3.connect(RESULTS_DB, isolation_level=None)
        _conn.executescript(_SCHEMA)
    return _conn


def close() -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None
