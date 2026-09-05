"""One Gemini client, configured once.

Retries live here rather than at each call site because an investigation is a
dozen model calls deep -- three of them video reads issued at the same moment --
and a shared model under load answers 503 to whichever call happens to arrive
during the spike. Losing an entire run to one transient refusal is unacceptable
in front of an audience, and worse in production.
"""

from __future__ import annotations

from functools import lru_cache

from google import genai
from google.genai import types

# 429 is quota, 5xx is capacity. Both are worth waiting out; a 400 is not.
RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=5,
    initial_delay=1.0,
    max_delay=20.0,
    exp_base=2.0,
    jitter=1.0,
    http_status_codes=[429, 500, 502, 503, 504],
)

# A video read of a 40-second window takes ten seconds or so; the default
# timeout is generous enough, but a retried one needs room for the backoff.
HTTP_OPTIONS = types.HttpOptions(retry_options=RETRY_OPTIONS, timeout=180_000)


@lru_cache(maxsize=1)
def client() -> genai.Client:
    """The shared client. Credentials come from the environment via config."""
    return genai.Client(http_options=HTTP_OPTIONS)
