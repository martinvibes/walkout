"""Watches one window of the film and reports what is on screen.

This is the half of Walkout that telemetry cannot do. ClickHouse knows that
9,000 people left between 09:20 and 10:00; only the footage knows whether that
window is a slow scene or a subtitled scene or an action beat that should have
held them.

The reading is deliberately blind to the numbers. If the model were told "these
viewers left because of buffering" it would find evidence for buffering, so it
is asked to describe the window and name the risks it can see, and the agent
does the correlating. A confident eye and a confident calculator that never
spoke to each other are worth more than one witness told what to say.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from .config import DATA_DIR
from .config import google as google_config
from .gemini import client as shared_client
from .models import timecode

# Video is sent as a URI with an offset window, so a 40-second look at a
# 15-minute film costs a 40-second read rather than a whole-film read.
READING_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    required=["synopsis", "beats", "pacing", "dialogue", "narrative_role",
              "attention_risks", "visual_artifacts", "on_screen_text"],
    properties={
        "synopsis": types.Schema(
            type=types.Type.STRING,
            description="What happens in this window, in one or two sentences.",
        ),
        "beats": types.Schema(
            type=types.Type.ARRAY,
            description="The moments in the window, in order.",
            items=types.Schema(
                type=types.Type.OBJECT,
                required=["timecode", "description"],
                properties={
                    "timecode": types.Schema(type=types.Type.STRING, description="MM:SS"),
                    "description": types.Schema(type=types.Type.STRING),
                },
            ),
        ),
        "pacing": types.Schema(
            type=types.Type.STRING,
            enum=["static", "slow", "steady", "brisk", "frantic"],
        ),
        "dialogue": types.Schema(
            type=types.Type.STRING,
            enum=["none", "sparse", "steady", "dense"],
        ),
        "narrative_role": types.Schema(
            type=types.Type.STRING,
            description="What this window is doing for the story: setup, exposition, "
                        "turning point, action, resolution, transition.",
        ),
        "attention_risks": types.Schema(
            type=types.Type.ARRAY,
            description="Reasons a viewer might stop watching here, judged only from "
                        "what is on screen. Empty if the window is compelling.",
            items=types.Schema(type=types.Type.STRING),
        ),
        "visual_artifacts": types.Schema(
            type=types.Type.ARRAY,
            description="Anything in the picture suggesting a delivery or encode "
                        "problem: macroblocking, frozen frames, audio drift, black "
                        "frames. Empty if the picture is clean.",
            items=types.Schema(type=types.Type.STRING),
        ),
        "on_screen_text": types.Schema(
            type=types.Type.ARRAY,
            description="Subtitles, signs, or titles that carry meaning in this window.",
            items=types.Schema(type=types.Type.STRING),
        ),
    },
)

PROMPT = """You are watching one window of a film for a retention analyst.

Window: {start} to {end}.

Describe only what is in this window. Do not guess at audience numbers, and do
not assume anything went wrong -- many windows are simply good scenes. Judge
pacing and dialogue against the film's own rhythm, not against a target.

Two things matter especially:
- If the scene carries meaning that a viewer would miss without dialogue they
  can understand -- a language they may not speak, a sign, a whispered line --
  say so in attention_risks.
- If the picture itself looks degraded, say so in visual_artifacts. A dark or
  grainy shot that is clearly an artistic choice is not a delivery problem."""


@dataclass
class SceneReading:
    """What the model saw in one window."""

    start_sec: int
    end_sec: int
    synopsis: str = ""
    beats: list[dict[str, str]] = field(default_factory=list)
    pacing: str = ""
    dialogue: str = ""
    narrative_role: str = ""
    attention_risks: list[str] = field(default_factory=list)
    visual_artifacts: list[str] = field(default_factory=list)
    on_screen_text: list[str] = field(default_factory=list)

    @property
    def window(self) -> str:
        return f"{timecode(self.start_sec)}-{timecode(self.end_sec)}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "synopsis": self.synopsis,
            "beats": self.beats,
            "pacing": self.pacing,
            "dialogue": self.dialogue,
            "narrative_role": self.narrative_role,
            "attention_risks": self.attention_risks,
            "visual_artifacts": self.visual_artifacts,
            "on_screen_text": self.on_screen_text,
        }


CACHE_DIR = DATA_DIR / "scene_readings"


def _cache_path(video_uri: str, start_sec: int, end_sec: int, model: str) -> Path:
    """Where a reading of this exact window by this exact model is kept."""
    key = f"{video_uri}|{start_sec}|{end_sec}|{model}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{digest}.json"


def _cache_enabled() -> bool:
    return os.environ.get("WALKOUT_SCENE_CACHE", "1") != "0"


def _offset(seconds: int) -> str:
    """Protobuf Duration wants a string like '560s'."""
    return f"{max(0, int(seconds))}s"


def watch_window(
    video_uri: str,
    start_sec: int,
    end_sec: int,
    client: genai.Client | None = None,
    model: str | None = None,
    pad_sec: int = 5,
) -> SceneReading:
    """Read one window of the film.

    A few seconds of lead-in are included: a viewer who left at 09:20 was
    reacting to something that started before 09:20.
    """
    config = google_config()
    model = model or config.vision_model
    start = max(0, start_sec - pad_sec)

    # The same window read twice is the same answer, and video reads are the
    # expensive call in the system -- in tokens, in seconds, and against a
    # daily quota. Rehearsing a demo should not spend the budget for it.
    cached = _cache_path(video_uri, start, end_sec, model)
    if _cache_enabled() and cached.exists():
        return _from_body(json.loads(cached.read_text()), start, end_sec)

    client = client or shared_client()

    part = types.Part(
        file_data=types.FileData(file_uri=video_uri),
        video_metadata=types.VideoMetadata(
            start_offset=_offset(start), end_offset=_offset(end_sec)
        ),
    )
    response = client.models.generate_content(
        model=model,
        contents=types.Content(
            role="user",
            parts=[part, types.Part(text=PROMPT.format(
                start=timecode(start), end=timecode(end_sec)
            ))],
        ),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=READING_SCHEMA,
            temperature=0.2,
        ),
    )
    body = json.loads(response.text)
    if _cache_enabled():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(body, indent=2))
    return _from_body(body, start, end_sec)


def _from_body(body: dict[str, Any], start_sec: int, end_sec: int) -> SceneReading:
    """Build a reading from the model's JSON, whether fresh or cached."""
    return SceneReading(
        start_sec=start_sec,
        end_sec=end_sec,
        synopsis=body.get("synopsis", ""),
        beats=body.get("beats", []),
        pacing=body.get("pacing", ""),
        dialogue=body.get("dialogue", ""),
        narrative_role=body.get("narrative_role", ""),
        attention_risks=body.get("attention_risks", []),
        visual_artifacts=body.get("visual_artifacts", []),
        on_screen_text=body.get("on_screen_text", []),
    )
