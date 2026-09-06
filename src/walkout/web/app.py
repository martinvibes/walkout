"""The Walkout web application.

Two layers, deliberately separated.

The deterministic layer -- retention curve, cliffs, cohort breakdown -- is pure
ClickHouse and answers in a couple of seconds. The page is alive before the
agent has said a word.

The agent layer streams. An investigation takes about a minute because it is
really reading the film, and hiding that behind a spinner would waste the most
interesting thing the product does. So every tool call is sent to the browser
as it happens.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import analysis, reports
from ..config import ConfigError, google
from ..detection import recoverable_watch_hours
from ..mcp_warehouse import McpWarehouse
from ..models import timecode

STATIC_DIR = Path(__file__).parent / "static"
BUCKET_SEC = 10

_warehouse: McpWarehouse | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """The MCP server is a subprocess; it gets shut down with us."""
    yield
    if _warehouse is not None:
        _warehouse.close()


app = FastAPI(
    title="Walkout", docs_url="/api/docs", redoc_url=None, lifespan=lifespan
)


def warehouse() -> McpWarehouse:
    """The shared MCP session, started on first request rather than at import
    so the server still boots (and reports the problem) with bad credentials."""
    global _warehouse
    if _warehouse is None:
        house = McpWarehouse()
        house.start()
        _warehouse = house
    return _warehouse


# Cliff detection is the same query for every request against the same data,
# and it is the slowest thing on the page. The loader is the only writer, so a
# plain memo is correct here; a title reloaded needs a restart, which is what a
# demo does anyway.
_cliff_cache: dict[str, list[Any]] = {}


def _cliffs_for(title: dict[str, Any]) -> list[Any]:
    title_id = title["title_id"]
    if title_id not in _cliff_cache:
        _cliff_cache[title_id] = analysis.find_cliffs(
            warehouse(), title_id, credits_sec=title["credits_start_sec"]
        )
    return _cliff_cache[title_id]


def _title_or_404(title_id: str) -> dict[str, Any]:
    try:
        rows = warehouse().run_named("title", {"title_id": title_id})
    except ConfigError as exc:
        raise HTTPException(500, f"configuration: {exc}") from exc
    if not rows:
        raise HTTPException(404, f"no title {title_id!r}")
    return rows[0]


@app.get("/api/titles")
def titles() -> list[dict[str, Any]]:
    """Everything in the warehouse, for the title picker."""
    return warehouse().run_sql(
        "SELECT title_id, title_name, duration_sec, credits_start_sec, video_uri, "
        "license FROM walkout.titles ORDER BY title_name"
    )


@app.get("/api/retention/{title_id}")
def retention(title_id: str) -> dict[str, Any]:
    """The survival curve, the cliffs on it, and what each one costs.

    One call, because the chart is meaningless without the cliffs marked and
    the client should not have to stitch two responses together to draw it.
    """
    title = _title_or_404(title_id)
    house = warehouse()

    curve = house.run_named(
        "retention_curve", {"title_id": title_id, "bucket_sec": BUCKET_SEC}
    )
    cliffs = _cliffs_for(title)
    return {
        "title": title,
        "credits_start_sec": title["credits_start_sec"],
        "sessions": curve[0]["reached"] if curve else 0,
        "curve": curve,
        "cliffs": [
            {
                "cliff_id": str(index),
                **cliff.to_dict(),
                "start_timecode": timecode(cliff.start_sec),
                "end_timecode": timecode(cliff.end_sec),
                "recoverable_watch_hours": round(
                    recoverable_watch_hours(cliff, title["duration_sec"]), 1
                ),
            }
            for index, cliff in enumerate(cliffs, start=1)
        ],
    }


@app.get("/api/investigate/{title_id}")
def investigate_all(title_id: str) -> list[dict[str, Any]]:
    """The telemetry evidence for every cliff, in one request.

    Deliberately one call rather than one per cliff. Each investigation is a
    dozen queries, and firing them concurrently down a single MCP pipe just
    queues them behind each other until the server's query timeout fires --
    which is exactly how this endpoint was first written, and exactly what the
    browser then reported as a 500.
    """
    title = _title_or_404(title_id)
    house = warehouse()
    baseline = analysis.playback_baseline(house, title_id)
    return [
        {
            "cliff_id": str(index),
            **analysis.investigate(
                house, title_id, cliff, playback_baseline=baseline
            ).to_dict(),
        }
        for index, cliff in enumerate(_cliffs_for(title), start=1)
    ]


@app.get("/api/investigate/{title_id}/{cliff_id}")
def investigate_one(title_id: str, cliff_id: str) -> dict[str, Any]:
    """The telemetry evidence for one cliff, without spending a model call.

    This is what the agent sees before it looks at the film, and it is worth
    showing on its own: the cohort concentrations are the discriminator.
    """
    title = _title_or_404(title_id)
    cliffs = _cliffs_for(title)
    try:
        cliff = cliffs[int(cliff_id) - 1]
    except (ValueError, IndexError):
        raise HTTPException(404, f"no cliff {cliff_id!r}") from None
    return analysis.investigate(warehouse(), title_id, cliff).to_dict()


async def _agent_events(title_id: str, question: str | None) -> AsyncIterator[str]:
    """Run the agent, yielding server-sent events as it works."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from ..agent import root_agent

    def event(kind: str, **payload: Any) -> str:
        return f"data: {json.dumps({'type': kind, **payload})}\n\n"

    # Kept so the run can be replayed later without spending a model call.
    written: list[str] = []
    trace: list[dict[str, Any]] = []
    started_at = time.monotonic()
    complete = False

    yield event("started", title_id=title_id)
    try:
        runner = InMemoryRunner(agent=root_agent, app_name="walkout")
        session = await runner.session_service.create_session(
            app_name="walkout", user_id="web"
        )
        prompt = question or (
            f"Analyse {title_id}. Work through every cliff and tell me what to fix."
        )
        async for item in runner.run_async(
            user_id="web",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            for part in item.content.parts if item.content else []:
                if part.function_call:
                    call = {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args or {}),
                    }
                    trace.append(call)
                    yield event("tool_call", **call)
                elif part.function_response:
                    yield event("tool_result", name=part.function_response.name)
                elif part.text and item.author != "user":
                    written.append(part.text)
                    yield event("text", text=part.text)
            await asyncio.sleep(0)
        complete = True
        yield event("done")
    except Exception as exc:  # noqa: BLE001 -- the browser deserves the reason
        yield event("error", message=f"{type(exc).__name__}: {exc}")
    finally:
        # Also on the failure path, and also when the browser goes away. A run
        # that died on the last cliff still found the first two, and throwing
        # that out would mean spending the whole quota again to learn the same
        # thing. It is stored flagged, and the page says it was cut short.
        report = "".join(written).strip()
        if report:
            reports.save(
                title_id=title_id,
                model=google().model,
                report=report,
                trace=trace,
                complete=complete,
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )


@app.get("/api/agent/{title_id}")
async def agent_stream(title_id: str, q: str | None = None) -> StreamingResponse:
    """Stream the agent's investigation as server-sent events."""
    _title_or_404(title_id)
    return StreamingResponse(
        _agent_events(title_id, q),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Reading video is the expensive call on the page, so the window someone can
# ask for is bounded. Sixty seconds is longer than any cliff we detect and short
# enough that a curious visitor cannot spend the daily quota in one click.
MAX_WATCH_SEC = 60


@app.get("/api/watch/{title_id}")
def watch(title_id: str, start: int, end: int) -> dict[str, Any]:
    """Have Gemini read one window of the film, blind to the telemetry.

    This is the half of the product that telemetry cannot do, and until now it
    was only reachable through the agent. On its own it is worth showing: give
    it any thirty seconds and it comes back with what is on screen, how the
    scene is paced, and whether anything is visibly broken -- without ever being
    told that viewers left there.
    """
    from ..vision import watch_window

    title = _title_or_404(title_id)
    duration = int(title["duration_sec"])

    if end <= start:
        raise HTTPException(422, "end must be after start")
    if end - start > MAX_WATCH_SEC:
        raise HTTPException(422, f"window must be {MAX_WATCH_SEC} seconds or shorter")
    if start < 0 or end > duration:
        raise HTTPException(422, f"window must sit inside the runtime (0-{duration}s)")

    try:
        reading = watch_window(str(title["video_uri"]), start, end)
    except Exception as exc:  # noqa: BLE001 -- quota and safety blocks both land here
        raise HTTPException(502, f"{type(exc).__name__}: {exc}") from exc
    return reading.to_dict()


@app.get("/api/agent/{title_id}/last")
def agent_last(title_id: str) -> dict[str, Any]:
    """The most recent investigation, replayed from ClickHouse.

    A full run costs about ten model calls against a per-day quota, so the page
    opens with the last one already on screen and asks before spending another.
    Nothing here is stale in a way that matters: the telemetry it was drawn from
    is a fixed dataset.
    """
    _title_or_404(title_id)
    found = reports.latest(warehouse(), title_id)
    return found.to_dict() if found else {}


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Enough to tell a deploy whether it is actually wired up."""
    rows = warehouse().run_sql("SELECT count() AS events FROM walkout.playback_events")
    return {"ok": True, "events": rows[0]["events"] if rows else 0}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def serve() -> int:
    """`walkout-serve` -- run the app.

    Host and port come from the environment so the same command works locally
    and on a platform that hands you a $PORT and expects you to listen on it.
    """
    import os

    import uvicorn

    uvicorn.run(
        "walkout.web.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )
    return 0
