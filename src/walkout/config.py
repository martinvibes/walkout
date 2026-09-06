"""Runtime configuration, resolved once from the environment.

Every credential lives here so nothing else in the codebase reads os.environ
directly -- which keeps secrets out of tool signatures and out of prompts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = PROJECT_ROOT / "sql"
DATA_DIR = PROJECT_ROOT / "data"

load_dotenv(PROJECT_ROOT / ".env")


class ConfigError(RuntimeError):
    """Raised when a required setting is missing, with a fix in the message."""


def _require(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. {hint}")
    return value


@dataclass(frozen=True)
class ClickHouseConfig:
    host: str
    port: int
    username: str
    password: str
    secure: bool
    database: str

    @classmethod
    def from_env(cls) -> "ClickHouseConfig":
        hint = "Copy .env.example to .env and paste the credentials from ClickHouse Cloud -> Connect -> HTTPS."
        return cls(
            host=_require("CLICKHOUSE_HOST", hint),
            port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
            username=os.environ.get("CLICKHOUSE_USER", "default"),
            password=_require("CLICKHOUSE_PASSWORD", hint),
            secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
            database=os.environ.get("CLICKHOUSE_DATABASE", "walkout"),
        )


# Orchestration and video understanding run on separate models on purpose.
# They want different things -- one is a fast reasoner making a dozen short
# calls, the other reads video once and carefully -- and on the free tier the
# request quota is counted per model, so separating them also stops a long
# investigation from starving its own video reads.
DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_VISION_MODEL = "gemini-3.6-flash"


@dataclass(frozen=True)
class GoogleConfig:
    """Which models to use, and -- in Vertex mode only -- where to reach them.

    There are two backends. With an API key, a project is neither needed nor
    read; with Vertex, the SDK picks `GOOGLE_CLOUD_PROJECT` up from the
    environment itself. Requiring it in both modes is how a deploy that was
    correctly configured for API-key mode came up healthy and then failed the
    moment anyone pressed a button that touched a model.
    """

    use_vertex: bool
    project: str
    location: str
    model: str
    vision_model: str

    @classmethod
    def from_env(cls) -> "GoogleConfig":
        use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
            "1", "true", "yes"
        )
        if use_vertex:
            hint = "Run `gcloud config set project YOUR_PROJECT`, or set GOOGLE_GENAI_USE_VERTEXAI=false to use an API key."
            project = _require("GOOGLE_CLOUD_PROJECT", hint)
        else:
            hint = "Create one at https://aistudio.google.com/apikey and put it in .env."
            _require("GOOGLE_API_KEY", hint)
            project = ""
        return cls(
            use_vertex=use_vertex,
            project=project,
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=os.environ.get("WALKOUT_MODEL", DEFAULT_MODEL),
            vision_model=os.environ.get("WALKOUT_VISION_MODEL", DEFAULT_VISION_MODEL),
        )


@lru_cache(maxsize=1)
def clickhouse() -> ClickHouseConfig:
    return ClickHouseConfig.from_env()


@lru_cache(maxsize=1)
def google() -> GoogleConfig:
    return GoogleConfig.from_env()
