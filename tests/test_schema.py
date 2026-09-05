"""The schema must be safe to apply to a cluster that already has data.

`make load` reads as a setup step -- it is the obvious thing to run on a new
deploy, and the README describes it as applying the schema. An earlier version
opened each table with DROP TABLE IF EXISTS, so running it destroyed thirteen
million rows without saying anything. It happened twice before anyone noticed
the loader was the culprit, because the failure surfaces later and elsewhere,
as an empty page.

Destroying data is a real need, and it lives in `walkout-load --reset` where
it announces itself. Here we check the schema itself stays harmless.
"""

from __future__ import annotations

from walkout.clickhouse import split_statements
from walkout.config import SQL_DIR

DESTRUCTIVE = ("DROP ", "TRUNCATE ", "DELETE ", "ALTER ")


def statements() -> list[str]:
    return split_statements((SQL_DIR / "schema.sql").read_text())


def test_schema_has_no_destructive_statements() -> None:
    for statement in statements():
        head = statement.lstrip().upper()
        assert not head.startswith(DESTRUCTIVE), f"schema.sql would destroy data: {statement[:60]}"


def test_every_create_is_conditional() -> None:
    """So a second run is a no-op rather than an error or a rebuild."""
    for statement in statements():
        head = statement.lstrip().upper()
        if head.startswith(("CREATE TABLE", "CREATE DATABASE")):
            assert "IF NOT EXISTS" in head, f"not idempotent: {statement[:60]}"


def test_comments_do_not_leak_into_statements() -> None:
    """The prose above each table mentions DROP; the parser must strip it.

    This is the same bug in miniature that split_statements was written for:
    a comment read as SQL. If stripping ever regresses, the check above would
    start failing on the explanation rather than on a real statement.
    """
    assert not any("--" in s for s in statements())


def test_trailing_comment_with_a_semicolon_does_not_split() -> None:
    """The natural way to write a note next to a column, and a trap.

    `-- see #12; fixed` ends a statement early if comments are stripped after
    splitting rather than before -- the same failure that once made the schema
    unloadable, moved from a whole-line comment to a trailing one.
    """
    sql = "CREATE TABLE t (a String,  -- see #12; fixed\n b String);"
    assert split_statements(sql) == ["CREATE TABLE t (a String,  \n b String)"]


def test_semicolons_and_comment_markers_inside_strings_survive() -> None:
    """A string literal is data, not syntax."""
    sql = "INSERT INTO t VALUES ('a;b', 'c--d'); SELECT 1;"
    assert split_statements(sql) == ["INSERT INTO t VALUES ('a;b', 'c--d')", "SELECT 1"]


def test_a_statement_without_a_trailing_semicolon_is_kept() -> None:
    assert split_statements("SELECT 1") == ["SELECT 1"]
