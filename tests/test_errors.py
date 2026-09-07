"""Failures have to arrive as something a visitor can read.

The most likely failure in this demo is not a bug. It is the free-tier request
quota running out because several people pressed the same button on the same
day, and the difference between `429 RESOURCE_EXHAUSTED {...}` and a sentence
explaining the daily budget is the difference between a broken product and a
product with a documented limit.
"""

from __future__ import annotations

import pytest

from walkout.config import ConfigError
from walkout.errors import describe

# Text taken from the shapes these libraries actually raise, not invented.
REAL_WORLD = [
    (
        "ClientError: 429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
        "'You exceeded your current quota', 'status': 'RESOURCE_EXHAUSTED'}}",
        "quota",
        429,
    ),
    ("ServerError: 503 UNAVAILABLE. The model is overloaded.", "upstream", 503),
    ("ValueError: response was blocked for SAFETY", "blocked", 502),
    ("TimeoutError: deadline exceeded after 180s", "timeout", 504),
    ("OperationalError: clickhouse connection refused", "warehouse", 503),
    ("RuntimeError: the mcp server exited before answering", "warehouse", 503),
    ("KeyError: 'title_name'", "unknown", 500),
]


@pytest.mark.parametrize("text, kind, status", REAL_WORLD, ids=[k for _, k, _ in REAL_WORLD])
def test_classification(text: str, kind: str, status: int) -> None:
    failure = describe(Exception(text))
    assert failure.kind == kind
    assert failure.status == status


def test_config_errors_are_their_own_kind() -> None:
    """A missing credential is the deployer's problem, not the visitor's."""
    failure = describe(ConfigError("GOOGLE_API_KEY is not set"))
    assert failure.kind == "config"
    assert failure.status == 500


def test_every_failure_says_what_to_do() -> None:
    """A message with no way forward is only a nicer-looking dead end."""
    for text, _, _ in REAL_WORLD:
        failure = describe(Exception(text))
        assert failure.title and not failure.title.endswith(".")
        assert len(failure.message) > 40
        assert len(failure.hint) > 20


def test_the_quota_message_says_what_still_works() -> None:
    """The whole point of the quota card: most of the page is unaffected."""
    failure = describe(Exception("429 RESOURCE_EXHAUSTED"))
    hint = failure.hint.lower()
    assert "clickhouse" in hint
    assert "stored" in hint or "replay" in hint


def test_the_original_text_survives_for_whoever_wants_it() -> None:
    """Plain language for the visitor, the real exception for the developer."""
    failure = describe(Exception("429 RESOURCE_EXHAUSTED. quota exceeded"))
    assert "RESOURCE_EXHAUSTED" in failure.detail


def test_payload_is_json_shaped() -> None:
    """The client reads these keys by name; they are an interface."""
    payload = describe(Exception("boom")).payload()
    assert set(payload) == {"kind", "title", "message", "hint", "status", "detail"}
    assert all(isinstance(v, (str, int)) for v in payload.values())


# --- the whole path, not just the classifier -------------------------------
#
# The classifier being right is worth nothing if the endpoint drops the shape
# on the way out. These drive the real app with a warehouse and a video model
# that fail the way the real ones do, so what a browser receives is asserted
# rather than assumed.


class _FakeWarehouse:
    """Answers the one query the watch endpoint needs, nothing else."""

    def run_named(self, name: str, params: dict) -> list[dict]:
        assert name == "title"
        return [{
            "title_id": params["title_id"],
            "title_name": "Sintel",
            "duration_sec": 888,
            "credits_start_sec": 746,
            "video_uri": "https://www.youtube.com/watch?v=eRsGyueVLvQ",
        }]

    def close(self) -> None:
        pass


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from walkout.web import app as web

    monkeypatch.setattr(web, "warehouse", lambda: _FakeWarehouse())
    return TestClient(web.app, raise_server_exceptions=False)


QUOTA = (
    "429 RESOURCE_EXHAUSTED. {'error': {'message': 'You exceeded your current quota'}}"
)


def test_a_quota_failure_reaches_the_browser_readable(client, monkeypatch) -> None:
    from walkout import vision

    def out_of_quota(*_args, **_kwargs):
        raise RuntimeError(QUOTA)

    monkeypatch.setattr(vision, "watch_window", out_of_quota)

    response = client.get("/api/watch/sintel", params={"start": 220, "end": 250})
    assert response.status_code == 429

    failure = response.json()["detail"]
    assert failure["kind"] == "quota"
    assert "20 requests" in failure["message"]
    # The card has to say the rest of the page still works, or a judge who
    # meets it will assume the whole demo is down.
    assert "ClickHouse" in failure["hint"]


def test_a_refused_window_explains_the_cap(client) -> None:
    response = client.get("/api/watch/sintel", params={"start": 0, "end": 300})
    assert response.status_code == 422
    failure = response.json()["detail"]
    assert failure["kind"] == "window"
    assert "60 seconds" in failure["message"]


def test_a_window_past_the_end_is_refused(client) -> None:
    response = client.get("/api/watch/sintel", params={"start": 880, "end": 910})
    assert response.status_code == 422
    assert response.json()["detail"]["kind"] == "window"


def test_a_valid_window_is_not_refused(client, monkeypatch) -> None:
    """The guard has to let real windows through, which is easy to break."""
    from walkout import vision

    class _Reading:
        def to_dict(self) -> dict:
            return {"synopsis": "a quiet scene"}

    monkeypatch.setattr(vision, "watch_window", lambda *a, **k: _Reading())
    response = client.get("/api/watch/sintel", params={"start": 220, "end": 250})
    assert response.status_code == 200
    assert response.json()["synopsis"] == "a quiet scene"
