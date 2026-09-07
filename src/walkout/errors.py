"""Turn an exception into something a visitor can read.

A demo fails in front of an audience or it does not fail at all, and the most
likely failure here is not a bug: it is the free-tier request quota running out
because several people pressed the same button on the same day. A raw
`ClientError: 429 RESOURCE_EXHAUSTED {...}` reads as a broken product. The same
condition, described as "today's model quota is spent, here is what still
works", reads as a product with a known limit.

So every failure that can reach the browser is classified here once, and both
the JSON endpoints and the SSE stream report the same shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .config import ConfigError


@dataclass(frozen=True)
class Failure:
    """A failure, described for the person looking at the screen."""

    kind: str        # a class the client can style and decide about
    title: str       # the headline, six words or so
    message: str     # what actually happened, in plain words
    hint: str        # what this person can do about it right now
    status: int      # the HTTP status to answer with
    detail: str      # the original exception text, for the curious

    def payload(self) -> dict[str, Any]:
        return asdict(self)


# Matched against the lower-cased exception text. Order matters: the first
# rule that matches wins, so the specific ones come before the general ones.
_QUOTA = ("429", "resource_exhausted", "quota", "rate limit", "too many requests")
_BLOCKED = ("safety", "blocked", "prohibited_content", "recitation")
_TIMEOUT = ("timeout", "timed out", "deadline exceeded", "504")
_UPSTREAM = ("503", "unavailable", "overloaded", "500 internal")
_WAREHOUSE = ("clickhouse", "connection refused", "getaddrinfo", "ssl", "mcp")


def describe(exc: BaseException) -> Failure:
    """Classify `exc` into something worth showing."""
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    detail = text[:400]

    if isinstance(exc, ConfigError):
        return Failure(
            kind="config",
            title="This deployment is missing a setting",
            message=(
                "The server started, but one of the credentials it needs for this "
                "particular action was never set."
            ),
            hint="Everything that reads from ClickHouse still works.",
            status=500,
            detail=detail,
        )

    if any(mark in low for mark in _QUOTA):
        return Failure(
            kind="quota",
            title="Today's model quota is spent",
            message=(
                "Walkout runs on a free Gemini key, which allows 20 requests per "
                "model per day. A full investigation costs about seven of them, so "
                "the daily budget is roughly two complete runs shared by everyone "
                "who visits."
            ),
            hint=(
                "Nothing on this page is faked while you wait: the retention curve, "
                "the cliffs and the cohort evidence are all live ClickHouse queries "
                "and none of them touch the quota. The investigation already on the "
                "page is a real run by the same agent, stored and replayed. Fresh "
                "runs resume when the quota resets at midnight Pacific."
            ),
            status=429,
            detail=detail,
        )

    if any(mark in low for mark in _BLOCKED):
        return Failure(
            kind="blocked",
            title="The model declined to answer",
            message=(
                "Gemini returned a safety or recitation block for this window "
                "rather than a reading of it."
            ),
            hint="Pick a different moment in the film and try again.",
            status=502,
            detail=detail,
        )

    if any(mark in low for mark in _TIMEOUT):
        return Failure(
            kind="timeout",
            title="That took longer than the limit",
            message=(
                "Reading video is the slow call in the system, and this one ran past "
                "the time the server is willing to hold a request open."
            ),
            hint="Try again, or choose a shorter window.",
            status=504,
            detail=detail,
        )

    if any(mark in low for mark in _UPSTREAM):
        return Failure(
            kind="upstream",
            title="The model is busy",
            message=(
                "A shared model under load answers 503 to whichever request happens "
                "to arrive during the spike. This is transient and not a fault in "
                "the data."
            ),
            hint="Press the button again; retries usually land within a few seconds.",
            status=503,
            detail=detail,
        )

    if any(mark in low for mark in _WAREHOUSE):
        return Failure(
            kind="warehouse",
            title="The warehouse did not answer",
            message=(
                "ClickHouse Cloud idles a service that has not been queried for a "
                "while and takes about thirty seconds to wake up."
            ),
            hint="Give it half a minute and reload the page.",
            status=503,
            detail=detail,
        )

    return Failure(
        kind="unknown",
        title="Something went wrong on the server",
        message="The action failed for a reason the server did not recognise.",
        hint="The rest of the page is unaffected. Reloading is safe.",
        status=500,
        detail=detail,
    )
