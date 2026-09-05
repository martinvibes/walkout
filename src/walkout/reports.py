"""Storage for the agent's findings.

An investigation costs about ten model calls, and a free-tier key is capped per
day. Without somewhere to keep the result, the second person to open the page
gets a quota error instead of a product -- so every run is written back to
ClickHouse and replayed until someone asks for a fresh one.

Reads go through whatever warehouse the caller has, which for the agent means
the MCP server. Writes use the driver, because the MCP server is read-only by
design and that is a property worth keeping.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .warehouse import Warehouse


@dataclass
class Report:
    """One run of the agent over one title."""

    title_id: str
    model: str
    report: str
    trace: list[dict[str, Any]]
    complete: bool
    duration_ms: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "title_id": self.title_id,
            "model": self.model,
            "report": self.report,
            "trace": self.trace,
            "complete": self.complete,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
        }


def latest(warehouse: Warehouse, title_id: str) -> Report | None:
    """The most recent report for a title, or None if it has never been run."""
    rows = warehouse.run_named("agent_report", {"title_id": title_id})
    if not rows:
        return None
    row = rows[0]
    try:
        trace = json.loads(row["trace"] or "[]")
    except json.JSONDecodeError:
        trace = []
    return Report(
        title_id=str(row["title_id"]),
        model=str(row["model"]),
        report=str(row["report"]),
        trace=trace,
        complete=bool(row["complete"]),
        duration_ms=int(row["duration_ms"]),
        created_at=str(row["created_at"]),
    )


def save(title_id: str, model: str, report: str, trace: list[dict[str, Any]],
         complete: bool, duration_ms: int) -> None:
    """Write a run back to the warehouse.

    A run that died partway is still worth keeping -- the cliffs it did reach
    are real findings -- but it is stored with `complete = 0` and the page says
    so. A truncated report presented as a finished one would be worse than an
    empty panel.

    Never raises. A cache that takes the page down when it fails is worse than
    no cache, so a failure here costs the next visitor a re-run and nothing more.
    """
    from . import clickhouse as ch

    try:
        client = ch.connect()
        client.insert(
            "walkout.agent_reports",
            [[title_id, model, report, json.dumps(trace), int(complete),
              duration_ms, datetime.now(timezone.utc)]],
            column_names=["title_id", "model", "report", "trace", "complete",
                          "duration_ms", "created_at"],
        )
    except Exception:  # noqa: BLE001 -- the run already succeeded; this is a cache
        pass
