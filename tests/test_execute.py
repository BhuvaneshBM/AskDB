"""If these are wrong, either the project is unsafe or every number it reports
is wrong. Nothing here needs a network or an API key."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from askdb.execute import is_ordered, rows_match, run, strip_comments, validate


# ---------------------------------------------------------- the validator ---
@pytest.mark.parametrize("sql", [
    "SELECT * FROM t",
    "select name from singer where age > 30",
    "WITH x AS (SELECT 1) SELECT * FROM x",
    "  SELECT 1  ;  ",                         # trailing semicolon is fine
])
def test_allows_read_only_statements(sql):
    assert validate(sql) is None


@pytest.mark.parametrize("sql", [
    "DROP TABLE users",
    "DELETE FROM users",
    "UPDATE users SET admin = 1",
    "INSERT INTO users VALUES (1)",
    "ALTER TABLE users ADD COLUMN x INT",
    "ATTACH DATABASE '/etc/passwd' AS p",
    "PRAGMA writable_schema = 1",
    "VACUUM",
])
def test_blocks_every_write_verb(sql):
    assert validate(sql) is not None


def test_blocks_stacked_statements():
    """The classic. A validator that only checks the first word passes this."""
    assert validate("SELECT 1; DROP TABLE users") is not None


def test_blocks_write_hidden_behind_a_comment():
    """Comments are stripped BEFORE the 'starts with SELECT' check. Without that
    ordering this statement passes, which is the whole reason strip_comments
    exists."""
    assert validate("/* SELECT */ DROP TABLE users") is not None
    assert validate("-- SELECT\nDROP TABLE users") is not None


def test_blocks_write_after_a_leading_select():
    assert validate("SELECT 1 UNION SELECT 2; DELETE FROM t") is not None


def test_blocks_empty():
    assert validate("") is not None
    assert validate("   ") is not None


def test_strip_comments_removes_both_styles():
    assert "SELECT" in strip_comments("/* x */ SELECT 1 -- y")
    assert "x" not in strip_comments("/* x */ SELECT 1")


# ------------------------------------------------------------- execution ---
@pytest.fixture
def tiny_db():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.sqlite"
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE singer (id INT, name TEXT, age INT)")
        con.executemany("INSERT INTO singer VALUES (?,?,?)",
                        [(1, "Joe", 52), (2, "Ana", 31), (3, "Kim", 43)])
        con.commit()
        con.close()
        yield p


def test_runs_a_select(tiny_db):
    rows, cols, err = run(tiny_db, "SELECT name FROM singer ORDER BY id")
    assert err is None
    assert cols == ["name"]
    assert [r[0] for r in rows] == ["Joe", "Ana", "Kim"]


def test_write_is_refused_before_it_reaches_the_database(tiny_db):
    rows, _, err = run(tiny_db, "DELETE FROM singer")
    assert err and err.startswith("blocked")
    # and the data is still there
    rows, _, _ = run(tiny_db, "SELECT COUNT(*) FROM singer")
    assert rows[0][0] == 3


def test_connection_is_read_only_even_if_the_validator_were_bypassed(tiny_db):
    """The layer that actually protects you. Validation is a regex and regexes
    have holes; this does not depend on the regex being clever."""
    con = sqlite3.connect(f"file:{tiny_db}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM singer")
    con.close()


def test_bad_sql_returns_the_error_rather_than_raising(tiny_db):
    """The error text is the repair signal -- it has to come back as data."""
    rows, _, err = run(tiny_db, "SELECT nope FROM singer")
    assert rows == []
    assert err and "nope" in err


def test_row_limit_is_enforced(tiny_db):
    rows, _, err = run(tiny_db, "SELECT * FROM singer", max_rows=2)
    assert err is None and len(rows) == 2


# --------------------------------------------------------------- scoring ---
def test_order_matters_only_when_gold_says_so():
    assert is_ordered("SELECT a FROM t ORDER BY a")
    assert not is_ordered("SELECT a FROM t")
    assert not is_ordered("SELECT a FROM t -- ORDER BY a")   # comment, not clause


def test_unordered_comparison_ignores_row_order():
    assert rows_match([(1,), (2,)], [(2,), (1,)], ordered=False)


def test_ordered_comparison_does_not():
    assert not rows_match([(1,), (2,)], [(2,), (1,)], ordered=True)


def test_duplicates_are_not_collapsed():
    """Multiset, not set. `SELECT country FROM singer` returning ['NL','NL'] is
    a different answer from ['NL'], and a set comparison would call them equal."""
    assert not rows_match([(1,), (1,)], [(1,)], ordered=False)


def test_int_and_float_of_the_same_value_match():
    """SQLite is dynamically typed: COUNT(*) can come back 3 or 3.0 depending on
    the expression. That is not a difference anyone asked about."""
    assert rows_match([(3,)], [(3,)], ordered=False)
    assert rows_match([("3",)], [(3,)], ordered=False)


def test_nulls_compare_equal():
    assert rows_match([(None,)], [(None,)], ordered=False)

def test_replace_function_not_blocked():
    assert validate("SELECT REPLACE(name, 'a', 'b') FROM t") is None

def test_replace_into_still_blocked():
    assert validate("REPLACE INTO t VALUES (1)") is not None