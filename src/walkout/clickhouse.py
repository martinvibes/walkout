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

# Column identifiers the agent is allowed to segment by. ClickHouse binds
# {dim:Identifier} safely, but an allow-list keeps a typo from becoming a
# confusing runtime error three tool calls deep.
SEGMENT_DIMENSIONS = (
    "device",
    "platform",
    "region",
    "app_version",
    "subtitle_lang",
    "cdn_pop",
    "is_first_time",
)


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
    if dim not in SEGMENT_DIMENSIONS:
        raise UnknownDimension(
            f"{dim!r} is not a segmentable dimension. choose one of: {', '.join(SEGMENT_DIMENSIONS)}"
        )
    return dim


def run_named(client: Client, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Run one of sql/queries/*.sql and return rows as dicts."""
    result = client.query(queries.load(name), parameters=params)
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
