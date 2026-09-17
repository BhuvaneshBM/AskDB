"""Reading a SQLite database's shape, and turning it into text a model can read.

This is the file that decides what the model knows about the data, and it is
where most of the achievable accuracy lives -- more than the prompt wording and
more than the model choice.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import N_SAMPLE_ROWS
from .models import Column, Table


def _readonly(db_path: Path) -> sqlite3.Connection:
    """Open read-only. Used even for schema reading, so there is exactly one way
    this project ever opens a database and no path where it is writable."""
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def read_tables(db_path: Path, n_sample_rows: int = N_SAMPLE_ROWS) -> list[Table]:
    con = _readonly(db_path)
    try:
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

        tables: list[Table] = []
        for name in names:
            # PRAGMA returns (cid, name, type, notnull, default, pk)
            cols = [Column(name=r[1], type=r[2] or "TEXT")
                    for r in con.execute(f'PRAGMA table_info("{name}")')]

            # (id, seq, table, from, to, ...) -- the join paths the model needs
            # to write anything involving more than one table.
            fks = [f'{name}.{r[3]} -> {r[2]}.{r[4]}'
                   for r in con.execute(f'PRAGMA foreign_key_list("{name}")')]

            rows: list[tuple] = []
            if n_sample_rows > 0:
                try:
                    rows = con.execute(
                        f'SELECT * FROM "{name}" LIMIT {n_sample_rows}').fetchall()
                except sqlite3.Error:
                    rows = []          # empty or unreadable table; not fatal

            tables.append(Table(name=name, columns=cols,
                                foreign_keys=fks, sample_rows=rows))
        return tables
    finally:
        con.close()


def describe(table: Table, include_samples: bool = True,
             max_chars: int = 60) -> str:
    """One table -> one document, for embedding and for the prompt.

    Sample values are truncated: a table with a column of 4 kB blobs would
    otherwise put a wall of text in front of the model, and the point of a sample
    is the SHAPE of the value, not its contents.
    """
    lines = [f"Table: {table.name}"]
    lines.append("Columns: " + ", ".join(
        f"{c.name} ({c.type})" for c in table.columns))
    if table.foreign_keys:
        lines.append("Foreign keys: " + "; ".join(table.foreign_keys))

    if include_samples and table.sample_rows:
        lines.append("Sample rows:")
        for row in table.sample_rows:
            cells = []
            for v in row:
                s = "NULL" if v is None else str(v)
                cells.append(s if len(s) <= max_chars else s[:max_chars] + "...")
            lines.append("  " + " | ".join(cells))

    return "\n".join(lines)


def list_databases(spider_dir: Path) -> dict[str, Path]:
    """Spider ships as database/<db_id>/<db_id>.sqlite."""
    root = Path(spider_dir) / "database"
    if not root.is_dir():
        return {}
    out = {}
    for d in sorted(root.iterdir()):
        f = d / f"{d.name}.sqlite"
        if f.exists():
            out[d.name] = f
    return out
