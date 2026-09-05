"""Tests for the parameter rendering that the MCP path depends on.

The MCP server takes a query string and nothing else, so parameters the driver
would normally bind have to be written into the SQL. That is the one place in
Walkout where a value becomes executable text, so it gets its own tests.
"""

from __future__ import annotations

import pytest

from walkout.warehouse import ParameterError, quote, render


class TestQuote:
    def test_integers_are_rendered_as_numbers(self):
        assert quote(746, "UInt32") == "746"
        assert quote("746", "UInt32") == "746"

    def test_floats_are_rendered_as_numbers(self):
        assert float(quote(1.6, "Float64")) == 1.6

    def test_a_non_numeric_value_never_reaches_the_cluster(self):
        with pytest.raises(ValueError):
            quote("1 OR 1=1", "UInt32")

    def test_infinity_and_nan_are_refused(self):
        for value in (float("inf"), float("nan")):
            with pytest.raises(ParameterError):
                quote(value, "Float64")

    def test_strings_are_quoted_and_escaped(self):
        assert quote("sintel", "String") == "'sintel'"
        assert quote("o'brien", "String") == r"'o\'brien'"
        assert quote("back\\slash", "String") == r"'back\\slash'"

    def test_a_quote_cannot_close_the_literal_early(self):
        """Every quote inside the literal has to be escaped, or the rest of the
        value becomes SQL."""
        rendered = quote("'; DROP TABLE walkout.titles; --", "String")
        assert rendered.startswith("'") and rendered.endswith("'")
        body = rendered[1:-1]
        assert all(
            body[index - 1] == "\\"
            for index, char in enumerate(body)
            if char == "'"
        )

    def test_an_unknown_type_is_refused_rather_than_guessed(self):
        with pytest.raises(ParameterError, match="warehouse.quote"):
            quote("2026-09-05", "Date")


class TestRender:
    def test_placeholders_are_substituted(self):
        sql = "SELECT * FROM t WHERE title_id = {title_id:String} AND p < {end:UInt32}"
        assert render(sql, {"title_id": "sintel", "end": 746}) == (
            "SELECT * FROM t WHERE title_id = 'sintel' AND p < 746"
        )

    def test_a_placeholder_used_twice_is_substituted_twice(self):
        assert render("{a:UInt32}+{a:UInt32}", {"a": 3}) == "3+3"

    def test_a_missing_parameter_is_an_error_not_a_literal_brace(self):
        with pytest.raises(ParameterError, match="warmup_sec"):
            render("SELECT {warmup_sec:UInt32}", {})

    def test_unused_parameters_are_harmless(self):
        assert render("SELECT {a:UInt32}", {"a": 1, "unused": "x"}) == "SELECT 1"
