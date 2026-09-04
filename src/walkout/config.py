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


@dataclass(frozen=True)
class GoogleConfig:
    project: str
    location: str
    model: str

    @classmethod
    def from_env(cls) -> "GoogleConfig":
        hint = "Run `gcloud config set project YOUR_PROJECT` or set GOOGLE_CLOUD_PROJECT in .env."
        return cls(
            project=_require("GOOGLE_CLOUD_PROJECT", hint),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            model=os.environ.get("WALKOUT_MODEL", "gemini-flash-latest"),
        )


@lru_cache(maxsize=1)
def clickhouse() -> ClickHouseConfig:
    return ClickHouseConfig.from_env()


@lru_cache(maxsize=1)
def google() -> GoogleConfig:
    return GoogleConfig.from_env()
