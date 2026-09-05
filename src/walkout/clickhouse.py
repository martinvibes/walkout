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

import time
from typing import Any, Iterable, Sequence

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import OperationalError

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


# A full load is millions of rows over the public internet, and a single
# dropped connection three minutes in should not cost the whole run.
INSERT_ATTEMPTS = 4
INSERT_BACKOFF_SEC = 3.0


def connect(config: ClickHouseConfig | None = None) -> Client:
    config = config or clickhouse_config()
    return clickhouse_connect.get_client(
        host=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        secure=config.secure,
        # Generous, because insert batches are large and the alternative is a
        # timeout that leaves the table half-populated.
        send_receive_timeout=600,
        connect_timeout=30,
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


class DirectWarehouse:
    """A Warehouse backed by the ClickHouse HTTP driver.

    Used by the loader and by the evaluation harness. The agent uses
    McpWarehouse instead -- same queries, same parameters, routed through the
    official ClickHouse MCP server.
    """

    def __init__(self, client: Client | None = None) -> None:
        self.client = client if client is not None else connect()

    def run_named(self, name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        return run_named(self.client, name, params)


def split_statements(sql: str) -> list[str]:
    """Split a script into executable statements.

    Comments are stripped *before* splitting on semicolons, not after. A prose
    comment containing a semicolon would otherwise be cut in half, and its tail
    parsed as SQL -- which is exactly what happened, with the error pointing at
    a sentence fragment rather than at the comment it came from.

    Statement-terminating semicolons inside string literals would still fool
    this; the schema has none, and a real migration tool is the answer if that
    ever changes.
    """
    stripped = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [chunk.strip() for chunk in stripped.split(";") if chunk.strip()]


def expand_events(client: Client, title_id: str, bucket_sec: int,
                  degraded_start: int, degraded_end: int) -> int:
    """Turn uploaded session descriptors into playback heartbeats, server-side.

    One statement, so the events table is either fully populated for this title
    or not at all -- there is no partial state for a query to quietly succeed
    against.
    """
    sql = (SQL_DIR / "expand_events.sql").read_text()
    client.command(sql, parameters=dict(
        title_id=title_id, bucket_sec=bucket_sec,
        degraded_start=degraded_start, degraded_end=degraded_end,
    ))
    return int(client.command(
        "SELECT count() FROM walkout.playback_events WHERE title_id = {t:String}",
        parameters={"t": title_id},
    ))


def list_tables(client: Client) -> list[str]:
    """Names of the tables that actually exist, so the CLI reports the cluster
    rather than a hardcoded list that drifts every time the schema grows."""
    rows = client.query(
        "SELECT name FROM system.tables WHERE database = 'walkout' ORDER BY name"
    ).result_rows
    return [f"walkout.{name}" for (name,) in rows]


def apply_schema(client: Client) -> None:
    """Create the database and tables."""
    for statement in split_statements((SQL_DIR / "schema.sql").read_text()):
        client.command(statement)


def insert_columns(client: Client, table: str, cols: dict[str, Any], names: Sequence[str]) -> int:
    """Insert one chunk, retrying transient network failures.

    Without this a single dropped connection aborts a ten-minute load and
    leaves a partially populated table -- which is far more dangerous than an
    empty one, because every query still returns plausible-looking numbers.
    """
    rows = list(zip(*[_tolist(cols[n]) for n in names]))
    for attempt in range(1, INSERT_ATTEMPTS + 1):
        try:
            client.insert(table, rows, column_names=list(names))
            return len(rows)
        except OperationalError as exc:
            if attempt == INSERT_ATTEMPTS:
                raise
            wait = INSERT_BACKOFF_SEC * attempt
            print(f"    insert failed ({exc.__class__.__name__}), retrying in {wait:.0f}s "
                  f"[{attempt}/{INSERT_ATTEMPTS}]", flush=True)
            time.sleep(wait)
    return len(rows)


def _tolist(value: Any) -> Iterable[Any]:
    return value.tolist() if hasattr(value, "tolist") else list(value)
