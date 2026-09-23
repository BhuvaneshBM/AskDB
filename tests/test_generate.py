from askdb.generate import MockGenerator, build_repair_prompt, clean


def test_strips_markdown_fences():
    assert clean("```sql\nSELECT 1\n```") == "SELECT 1"
    assert clean("```\nSELECT 1\n```") == "SELECT 1"


def test_strips_leading_labels():
    assert clean("SQL: SELECT 1") == "SELECT 1"
    assert clean("Query:\nSELECT 1") == "SELECT 1"


def test_strips_trailing_semicolon():
    assert clean("SELECT 1;") == "SELECT 1"


def test_mock_writes_valid_sql_against_the_first_table():
    """The mock is the FLOOR, not a stub: it produces runnable SQL that ignores
    the question, so you know what 'valid but useless' scores."""
    from askdb.execute import validate
    sql = MockGenerator().generate("anything", ["Table: singer\nColumns: id (INT)"])
    assert validate(sql) is None
    assert "singer" in sql


def test_repair_prompt_shows_the_model_its_own_sql_and_the_error():
    p = build_repair_prompt("q", ["Table: t"], "SELECT nope FROM t",
                            "no such column: nope")
    assert "SELECT nope FROM t" in p
    assert "no such column: nope" in p
