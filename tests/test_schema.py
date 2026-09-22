import sqlite3
import tempfile
from pathlib import Path

import pytest

from askdb.schema import describe, read_tables


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE stadium (id INT PRIMARY KEY, name TEXT)")
        con.execute("CREATE TABLE concert (id INT, stadium_id INT, "
                    "FOREIGN KEY (stadium_id) REFERENCES stadium(id))")
        con.execute("INSERT INTO stadium VALUES (1, 'Wembley')")
        con.commit()
        con.close()
        yield p


def test_reads_tables_and_columns(db):
    tables = {t.name: t for t in read_tables(db)}
    assert set(tables) == {"stadium", "concert"}
    assert [c.name for c in tables["stadium"].columns] == ["id", "name"]


def test_reads_foreign_keys(db):
    """Without these the model cannot know how to join, and every multi-table
    question fails. The single most important thing in the schema after the
    column names."""
    concert = next(t for t in read_tables(db) if t.name == "concert")
    assert concert.foreign_keys == ["concert.stadium_id -> stadium.id"]


def test_sample_rows_are_included(db):
    stadium = next(t for t in read_tables(db) if t.name == "stadium")
    assert stadium.sample_rows == [(1, "Wembley")]


def test_empty_table_does_not_break_reading(db):
    concert = next(t for t in read_tables(db) if t.name == "concert")
    assert concert.sample_rows == []


def test_describe_contains_what_the_model_needs(db):
    t = next(x for x in read_tables(db) if x.name == "concert")
    text = describe(t, include_samples=True)
    assert "Table: concert" in text
    assert "stadium_id" in text
    assert "-> stadium.id" in text


def test_describe_can_omit_samples(db):
    t = next(x for x in read_tables(db) if x.name == "stadium")
    assert "Wembley" in describe(t, include_samples=True)
    assert "Wembley" not in describe(t, include_samples=False)


def test_long_values_are_truncated(db):
    from askdb.models import Column, Table
    t = Table(name="t", columns=[Column("blob", "TEXT")],
              sample_rows=[("x" * 500,)])
    assert len(describe(t, max_chars=20)) < 200
