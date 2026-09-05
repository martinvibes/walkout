"""The interface every part of Walkout uses to read the warehouse.

There are two implementations. `DirectWarehouse` speaks to ClickHouse over the
native HTTP driver and is what the loader and the batch evaluator use, because
loading data is not agent work. `McpWarehouse` speaks to the same cluster
through the official ClickHouse MCP server, and is what the agent uses at
runtime -- so every number the agent reports has come back through MCP.

Both accept the same named queries with the same parameters, which is the point:
the evaluation harness grades the same SQL the agent runs.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

Row = dict[str, Any]

# ClickHouse's own parameter syntax, e.g. {title_id:String}.
PARAM_PATTERN = re.compile(r"\{([a-z_]+):([A-Za-z0-9]+)\}")


class ParameterError(ValueError):
    """Raised when a query parameter cannot be safely rendered."""


@runtime_checkable
class Warehouse(Protocol):
    """Anything that can run one of sql/queries/*.sql and hand back rows."""

    def run_named(self, name: str, params: dict[str, Any]) -> list[Row]:
        ...


def quote(value: Any, sql_type: str) -> str:
    """Render one parameter as a ClickHouse literal.

    The MCP server takes a query string and nothing else, so parameters that
    the driver would normally bind have to be written into the SQL. Numbers go
    through int()/float() -- a value that is not a number raises rather than
    reaching the cluster -- and strings are escaped. Only these two shapes are
    accepted; a new type has to be added here deliberately.
    """
    if sql_type.startswith(("UInt", "Int")):
        return str(int(value))
    if sql_type.startswith(("Float", "Decimal")):
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ParameterError(f"{number!r} is not a finite number")
        return repr(number)
    if sql_type == "String":
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    raise ParameterError(
        f"no literal rendering for type {sql_type!r}; add one in warehouse.quote"
    )


DIM_SLOT = "$DIM$"
DIMS_SLOT = "$DIMS$"


def prepare(name: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Load a named query and fill its dimension slots.

    A dimension can be a derived expression rather than a bindable identifier,
    so it is resolved through the allow-list and substituted as text. Both
    warehouse implementations go through here, or the two would drift.
    """
    from .clickhouse import SEGMENT_EXPRESSIONS, check_dimension
    from .queries import load

    sql = load(name)
    params = dict(params)
    dim = params.pop("dim", None)

    if DIM_SLOT in sql:
        if dim is None:
            raise ValueError(f"query {name!r} needs a `dim` parameter")
        sql = sql.replace(DIM_SLOT, check_dimension(dim))

    if DIMS_SLOT in sql:
        pairs = ", ".join(
            f"('{key}', toString({expression}))"
            for key, expression in SEGMENT_EXPRESSIONS.items()
        )
        sql = sql.replace(DIMS_SLOT, pairs)

    return sql, params


def render(sql: str, params: dict[str, Any]) -> str:
    """Substitute {name:Type} placeholders with escaped literals."""
    missing = []

    def substitute(match: re.Match[str]) -> str:
        name, sql_type = match.group(1), match.group(2)
        if name not in params:
            missing.append(name)
            return match.group(0)
        return quote(params[name], sql_type)

    rendered = PARAM_PATTERN.sub(substitute, sql)
    if missing:
        raise ParameterError(f"query is missing parameters: {', '.join(sorted(set(missing)))}")
    return rendered
