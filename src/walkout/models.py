"""The vocabulary of the system.

These types are what the agent's tools return, what the API serves, and what
the evaluation harness scores. Keeping them in one place stops the agent and
the analytics layer drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


def timecode(seconds: int) -> str:
    """Seconds -> HH:MM:SS. Every position the agent reports is a timecode,
    because that is the unit an editor can act on."""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class Cause(str, Enum):
    """Why an audience walked out. The whole product turns on this call."""

    STORY = "story"                  # the scene isn't holding -- recut
    PACING = "pacing"                # the scene works but runs long
    TECHNICAL = "technical"          # rebuffering / bitrate / player bug -- do NOT recut
    LOCALIZATION = "localization"    # missing subtitles or dub for the audience present
    AD_BREAK = "ad_break"            # the interruption, not the content
    UNKNOWN = "unknown"              # evidence was inconclusive; say so rather than guess


@dataclass
class Cliff:
    """A statistically significant abandonment window."""

    start_sec: int
    end_sec: int
    reached: int
    exits: int
    hazard: float
    baseline_hazard: float
    lift: float
    z_score: float
    excess_exits: int

    @property
    def timecode_range(self) -> str:
        return f"{timecode(self.start_sec)}-{timecode(self.end_sec)}"

    @property
    def duration_sec(self) -> int:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "timecode_range": self.timecode_range}


@dataclass
class CohortSignal:
    """One audience slice's behaviour inside a cliff window.

    `concentration` is the number that matters: how much more likely this
    cohort was to leave here than the title's audience as a whole. A cliff that
    is flat across every cohort is editorial; one that spikes in a single
    player build is not.
    """

    dimension: str
    value: str
    reached: int
    exits_in_window: int
    hazard_in_window: float
    cohort_share: float
    concentration: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Diagnosis:
    """The agent's verdict on one cliff, with the evidence that produced it."""

    cliff: Cliff
    cause: Cause
    confidence: float
    headline: str
    what_is_on_screen: str = ""
    telemetry_evidence: list[str] = field(default_factory=list)
    driving_cohorts: list[CohortSignal] = field(default_factory=list)
    recommended_action: str = ""
    recoverable_watch_hours: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cliff": self.cliff.to_dict(),
            "cause": self.cause.value,
            "confidence": round(self.confidence, 3),
            "headline": self.headline,
            "what_is_on_screen": self.what_is_on_screen,
            "telemetry_evidence": self.telemetry_evidence,
            "driving_cohorts": [c.to_dict() for c in self.driving_cohorts],
            "recommended_action": self.recommended_action,
            "recoverable_watch_hours": round(self.recoverable_watch_hours, 1),
        }
