"""The agent's tools.

Each one does a job the model should not be doing by hand. Cliff detection is a
survival-analysis query with a significance test; cohort ranking is arithmetic;
neither is improved by a language model improvising SQL. What the model is good
at -- weighing two independent kinds of evidence and writing the answer -- is
what the instruction leaves to it.

Detected cliffs are kept in session state and addressed by id, so the model
never retypes a timecode it might get wrong.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from .. import analysis
from ..mcp_warehouse import McpWarehouse
from ..models import Cliff
from ..detection import recoverable_watch_hours
from ..vision import watch_window

_warehouse: McpWarehouse | None = None

CLIFF_STATE_KEY = "walkout:cliffs"
TITLE_STATE_KEY = "walkout:title"


def warehouse() -> McpWarehouse:
    """The shared MCP session. Started on first use, reused after that."""
    global _warehouse
    if _warehouse is None:
        _warehouse = McpWarehouse()
        _warehouse.start()
    return _warehouse


def _remember(context: ToolContext, title_id: str, cliffs: list[Cliff]) -> None:
    context.state[TITLE_STATE_KEY] = title_id
    context.state[CLIFF_STATE_KEY] = {
        str(index): cliff.to_dict() for index, cliff in enumerate(cliffs, start=1)
    }


def _recall(context: ToolContext, cliff_id: str) -> Cliff:
    stored = context.state.get(CLIFF_STATE_KEY) or {}
    row = stored.get(str(cliff_id))
    if row is None:
        known = ", ".join(sorted(stored)) or "none"
        raise ValueError(
            f"no cliff {cliff_id!r} in this session (known: {known}). "
            f"call find_walkouts first."
        )
    fields = {k: v for k, v in row.items() if k != "timecode_range"}
    return Cliff(**fields)


def find_walkouts(title_id: str, tool_context: ToolContext) -> dict[str, Any]:
    """Find the windows where an audience abandons a title, worst first.

    Compares each ten-second bucket's hazard rate -- the share of viewers still
    watching who leave in that bucket -- against the title's own post-warmup
    baseline, keeps only windows that clear a significance test, and merges
    consecutive ones into a single cliff. Viewers who reach the end credits are
    finishing, not abandoning, and are excluded.

    Args:
        title_id: The title to analyse, e.g. "sintel".

    Returns:
        The title's runtime and the cliffs found, each with an id, timecodes,
        how many viewers left beyond the expected rate, and the recoverable
        watch hours if it were fixed.
    """
    house = warehouse()
    rows = house.run_named("title", {"title_id": title_id})
    if not rows:
        available = house.run_sql("SELECT title_id, title_name FROM walkout.titles")
        return {"error": f"no title {title_id!r}", "available": available}
    title = rows[0]

    cliffs = analysis.find_cliffs(house, title_id, credits_sec=title["credits_start_sec"])
    _remember(tool_context, title_id, cliffs)

    return {
        "title": title["title_name"],
        "runtime": title["duration_sec"],
        "credits_start_sec": title["credits_start_sec"],
        "cliffs_found": len(cliffs),
        "cliffs": [
            {
                "cliff_id": str(index),
                "window": cliff.timecode_range,
                "start_sec": cliff.start_sec,
                "end_sec": cliff.end_sec,
                "viewers_reaching_it": cliff.reached,
                "viewers_leaving": cliff.exits,
                "excess_exits": cliff.excess_exits,
                "times_the_normal_rate": round(cliff.lift, 2),
                "recoverable_watch_hours": round(
                    recoverable_watch_hours(cliff, title["duration_sec"]), 1
                ),
            }
            for index, cliff in enumerate(cliffs, start=1)
        ],
    }


def investigate_walkout(
    title_id: str, cliff_id: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Slice one cliff by every cohort that matters and weigh the playback data.

    Answers the question the retention chart cannot: was this the whole
    audience, or one device, one app build, one CDN, one language? Also
    compares rebuffering inside the window against the same viewers' own
    baseline across the rest of the title, so a title that buffers everywhere
    does not read as a cliff.

    Args:
        title_id: The title being analysed.
        cliff_id: The id of a cliff returned by find_walkouts.

    Returns:
        Cohort concentrations by dimension, the rebuffering comparison, and the
        cause the telemetry alone supports. That proposal is deliberately
        conservative: telemetry cannot see the film, so it will not claim a
        story problem, only rule delivery and localization in or out.
    """
    cliff = _recall(tool_context, cliff_id)
    result = analysis.investigate(warehouse(), title_id, cliff)
    return {"cliff_id": str(cliff_id), **result.to_dict()}


def watch_scene(
    title_id: str, cliff_id: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Watch the film across a cliff window and describe what is on screen.

    Gemini reads the video itself, with a few seconds of lead-in, because a
    viewer who left at 09:20 was reacting to something that began before 09:20.
    The reading is taken blind to the telemetry so that agreement between the
    two means something.

    Args:
        title_id: The title being analysed.
        cliff_id: The id of a cliff returned by find_walkouts.

    Returns:
        A synopsis of the window, its beats with timecodes, its pacing and
        dialogue density, anything on screen that might cost attention, and
        any visible sign of a delivery problem.
    """
    cliff = _recall(tool_context, cliff_id)
    rows = warehouse().run_named("title", {"title_id": title_id})
    if not rows or not rows[0].get("video_uri"):
        return {"error": f"no video URI on record for {title_id!r}"}

    reading = watch_window(rows[0]["video_uri"], cliff.start_sec, cliff.end_sec)
    return {"cliff_id": str(cliff_id), **reading.to_dict()}
