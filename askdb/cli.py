"""Command line.

    uv run python -m askdb.cli index                       # index every Spider database
    uv run python -m askdb.cli ask concert_singer "how many singers are there?"
    uv run python -m askdb.cli ask --sqlite path/to.db "..."    # any SQLite file
    uv run python -m askdb.cli results "which db did I score worst on?"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import index
from .config import INCLUDE_SAMPLE_ROWS, RESULTS_DB, SPIDER_DIR, TOP_K_TABLES
from .graph import ask as ask_graph
from .schema import list_databases, read_tables


def cmd_index(a):
    dbs = list_databases(SPIDER_DIR)
    if not dbs:
        print(f"no databases under {SPIDER_DIR}/database -- run "
              f"`uv run python -m bench.spider` first", file=sys.stderr)
        return 1
    index.load_model()
    total = 0
    for i, (db_id, path) in enumerate(dbs.items(), 1):
        for with_rows in ({True, False} if a.both else {INCLUDE_SAMPLE_ROWS}):
            if index.is_indexed(db_id, with_rows):
                continue
            tables = read_tables(path)
            total += index.index_database(db_id, tables, include_samples=with_rows)
        if i % 25 == 0:
            print(f"  {i}/{len(dbs)} databases")
    print(f"indexed {total} tables across {len(dbs)} databases")
    return 0


def cmd_ask(a):
    if a.sqlite:
        path = Path(a.sqlite)
        db_id = path.stem
        if not index.is_indexed(db_id):
            index.index_database(db_id, read_tables(path))
    else:
        dbs = list_databases(SPIDER_DIR)
        if a.db_id not in dbs:
            print(f"unknown database {a.db_id!r}", file=sys.stderr)
            return 1
        path, db_id = dbs[a.db_id], a.db_id

    r = ask_graph(a.question, db_id, str(path), top_k=a.top_k,
                  use_retrieval=not a.all_tables)

    print(f"\nSQL:\n  {r.sql}\n")
    if r.blocked:
        print(f"BLOCKED: {r.error}")
        return 1
    if r.error:
        print(f"ERROR after {r.repairs} repair(s): {r.error}")
        return 1
    if r.repairs:
        print(f"(repaired {r.repairs}x)\n")
    if r.columns:
        print(" | ".join(r.columns))
        print("-" * 60)
    for row in r.rows[:50]:
        print(" | ".join("NULL" if v is None else str(v) for v in row))
    print(f"\n{len(r.rows)} row(s) in {r.latency_ms} ms")
    return 0


def cmd_results(a):
    """Point AskDB at its OWN benchmark results.

    The project answers questions about SQLite databases; its results live in a
    SQLite database (§14). So this is not a special case -- it is the exact same
    schema.read_tables + execute.run path every other query in this file takes,
    just pointed at RESULTS_DB instead of a Spider database. One dialect,
    everywhere, is what dropping Postgres bought here.
    """
    from .execute import run
    from .generate import get_generator

    if not RESULTS_DB.exists():
        print("no results database -- run the benchmark first", file=sys.stderr)
        return 1

    tables = read_tables(RESULTS_DB)
    eval_table = next((t for t in tables if t.name == "eval_results"), None)
    if eval_table is None:
        print("no eval_results table -- run the benchmark first", file=sys.stderr)
        return 1

    from .schema import describe
    doc = describe(eval_table, include_samples=False)
    sql = get_generator().generate(a.question, [doc])
    print(f"\nSQL:\n  {sql}\n")

    rows, cols, err = run(RESULTS_DB, sql)
    if err:
        print(err)
        return 1
    print(" | ".join(cols))
    print("-" * 60)
    for r in rows[:50]:
        print(" | ".join("NULL" if v is None else str(v) for v in r))
    return 0


def main():
    ap = argparse.ArgumentParser(prog="askdb")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="embed every database's tables")
    p.add_argument("--both", action="store_true",
                   help="index with AND without sample rows (for the ablation)")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("ask")
    p.add_argument("db_id", nargs="?", default=None)
    p.add_argument("question")
    p.add_argument("--sqlite", default=None, help="path to any SQLite file")
    p.add_argument("--top-k", type=int, default=TOP_K_TABLES)
    p.add_argument("--all-tables", action="store_true",
                   help="skip retrieval, use the whole schema")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("results", help="ask questions about your own benchmark run")
    p.add_argument("question")
    p.set_defaults(fn=cmd_results)

    args = ap.parse_args()
    raise SystemExit(args.fn(args))


if __name__ == "__main__":
    main()
