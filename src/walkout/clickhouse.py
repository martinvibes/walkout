"""ClickHouse access.

Two paths reach the same cluster, deliberately:

* this module, for deterministic work the agent should not be improvising --
  loading data, applying the schema, running the named analytical queries;
* the official `mcp-clickhouse` MCP server, wired into the agent as an ADK
  toolset, for the open-ended follow-up questions a diagnosis actually needs
  ("which CDN pops served that cohort?").

The named queries are parameter-bound. The model supplies values, never SQL.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from . import queries
from .config import SQL_DIR, ClickHouseConfig, clickhouse as clickhouse_config

# The dimensions the agent may slice a cliff by, mapped to the SQL that
# produces them. Most are plain columns; `subtitle_gap` is derived, because the
# raw subtitle_lang column cannot express the thing that actually matters.
#
# Segmenting on subtitle_lang alone is useless: '' covers both an English
# viewer watching English audio (who needs nothing) and a Hindi viewer who was
# never offered a subtitle track (who is about to leave). Around 70% of the
# audience lands in one bucket and the signal disappears. What matters is the
# *gap* -- a viewer whose locale does not match the audio and who has no
# subtitles running.
#
# Values here are ours, never the model's: the agent picks a key from this
# fixed set and the expression is looked up, so no model output ever reaches
# the SQL text. Every other parameter is bound by ClickHouse as usual.
SEGMENT_EXPRESSIONS = {
    "device": "device",
    "platform": "platform",
    "region": "region",
    "app_version": "app_version",
    "cdn_pop": "cdn_pop",
    "subtitle_lang": "subtitle_lang",
    "locale_lang": "locale_lang",
    "is_first_time": "toString(is_first_time)",
    "subtitle_gap": (
        "if(locale_lang != audio_lang AND subtitle_lang = '', "
        "'no subtitles in a foreign-language locale', 'subtitled or native')"
    ),
}

SEGMENT_DIMENSIONS = tuple(SEGMENT_EXPRESSIONS)

DIM_SLOT = "$DIM$"


class UnknownDimension(ValueError):
    pass


def connect(config: ClickHouseConfig | None = None) -> Client:
    config = config or clickhouse_config()
    return clickhouse_connect.get_client(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        secure=config.secure,
    )


def check_dimension(dim: str) -> str:
    """Resolve an allow-listed dimension name to its SQL expression."""
    try:
        return SEGMENT_EXPRESSIONS[dim]
    except KeyError:
        raise UnknownDimension(
            f"{dim!r} is not a segmentable dimension. choose one of: {', '.join(SEGMENT_DIMENSIONS)}"
        ) from None


def run_named(client: Client, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one of sql/queries/*.sql and return rows as dicts.

    A `dim` parameter is resolved through the allow-list and substituted into
    the statement, since a dimension can be a derived expression rather than a
    bindable identifier. Everything else is bound by the driver.
    """
    sql = queries.load(name)
    params = dict(params)
    dim = params.pop("dim", None)
    if DIM_SLOT in sql:
        if dim is None:
            raise ValueError(f"query {name!r} needs a `dim` parameter")
        sql = sql.replace(DIM_SLOT, check_dimension(dim))
    result = client.query(sql, parameters=params)
    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def split_statements(sql: str) -> list[str]:
    """Split a script into executable statements, dropping comment-only ones.

    The driver takes one statement per call. Leading `--` lines have to be
    stripped rather than used to skip the statement, or a documented statement
    silently never runs -- which is exactly how CREATE DATABASE went missing.
    """
    statements = []
    for chunk in sql.split(";"):
        body = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if body:
            statements.append(body)
    return statements


def apply_schema(client: Client) -> None:
    """Create the database and tables."""
    for statement in split_statements((SQL_DIR / "schema.sql").read_text()):
        client.command(statement)


def insert_columns(client: Client, table: str, cols: dict[str, Any], names: Sequence[str]) -> int:
    rows = list(zip(*[_tolist(cols[n]) for n in names]))
    client.insert(table, rows, column_names=list(names))
    return len(rows)


def _tolist(value: Any) -> Iterable[Any]:
    return value.tolist() if hasattr(value, "tolist") else list(value)
