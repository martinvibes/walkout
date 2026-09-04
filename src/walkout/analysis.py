"""The deterministic half of a diagnosis.

Everything a cliff can be established from telemetry alone happens here, with
no model involved: where the walk-out is, who it hit, and whether playback was
healthy through it. The result is an evidence packet.

The split matters. This layer *proposes* a cause from the numbers and can never
invent one -- every figure it reports came out of ClickHouse. Gemini then does
the two things telemetry cannot: watch what is actually on screen in that
window, and decide whether the footage agrees with the numbers. A model that is
handed the evidence and asked to adjudicate is doing something it is good at;
a model asked to guess a rebuffer ratio is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clickhouse_connect.driver.client import Client

from .clickhouse import run_named
from .detection import is_concentrated, merge_cliffs, rank_cohorts
from .models import Cause, Cliff, CohortSignal

# Dimensions that describe *how* the video was delivered. Concentration here
# points at the pipeline, not the edit.
DELIVERY_DIMENSIONS = ("device", "platform", "app_version", "cdn_pop")

# Dimensions that describe *who was watching*. Concentration here, with clean
# playback, points at language and availability rather than the edit.
AUDIENCE_DIMENSIONS = ("region", "locale_lang", "subtitle_gap", "is_first_time")

DEFAULT_DIMENSIONS = DELIVERY_DIMENSIONS + AUDIENCE_DIMENSIONS

# A cohort must be this much more likely to leave here than the audience at
# large before it counts as driving the cliff.
CONCENTRATION_FLOOR = 1.5

# Rebuffering inside the window, relative to the same cohort across the whole
# title. Playback that is this much worse here is a delivery failure, full stop.
REBUFFER_LIFT_FLOOR = 5.0


@dataclass
class Investigation:
    """Everything telemetry can say about one cliff."""

    cliff: Cliff
    cohorts: dict[str, list[CohortSignal]] = field(default_factory=dict)
    rebuffer_ratio_in_window: float = 0.0
    rebuffer_ratio_baseline: float = 0.0
    rebuffer_lift: float = 1.0
    worst_delivery_cohort: str = ""
    evidence: list[str] = field(default_factory=list)
    proposed_cause: Cause = Cause.UNKNOWN

    @property
    def delivery_signals(self) -> list[CohortSignal]:
        return [s for d in DELIVERY_DIMENSIONS for s in self.cohorts.get(d, [])]

    @property
    def audience_signals(self) -> list[CohortSignal]:
        return [s for d in AUDIENCE_DIMENSIONS for s in self.cohorts.get(d, [])]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cliff": self.cliff.to_dict(),
            "cohorts": {d: [s.to_dict() for s in v] for d, v in self.cohorts.items() if v},
            "rebuffer_ratio_in_window": self.rebuffer_ratio_in_window,
            "rebuffer_ratio_baseline": self.rebuffer_ratio_baseline,
            "rebuffer_lift": round(self.rebuffer_lift, 1),
            "worst_delivery_cohort": self.worst_delivery_cohort,
            "evidence": self.evidence,
            "proposed_cause": self.proposed_cause.value,
        }


def find_cliffs(
    client: Client,
    title_id: str,
    bucket_sec: int = 10,
    warmup_sec: int = 60,
    min_lift: float = 1.6,
    min_z: float = 5.0,
    min_exits: int = 150,
    max_gap_sec: int = 10,
) -> list[Cliff]:
    """Significant abandonment cliffs for a title, worst first."""
    rows = run_named(
        client,
        "detect_cliffs",
        dict(
            title_id=title_id,
            bucket_sec=bucket_sec,
            warmup_sec=warmup_sec,
            min_lift=min_lift,
            min_z=min_z,
            min_exits=min_exits,
        ),
    )
    return merge_cliffs(rows, bucket_sec=bucket_sec, max_gap_sec=max_gap_sec)


def investigate(
    client: Client,
    title_id: str,
    cliff: Cliff,
    dimensions: tuple[str, ...] = DEFAULT_DIMENSIONS,
    bucket_sec: int = 10,
    min_cohort: int = 500,
) -> Investigation:
    """Slice one cliff every way that matters and weigh the playback evidence."""
    result = Investigation(cliff=cliff)

    for dim in dimensions:
        rows = run_named(
            client,
            "segment_cliff",
            dict(
                title_id=title_id,
                dim=dim,
                start_sec=cliff.start_sec,
                end_sec=cliff.end_sec,
                min_cohort=min_cohort,
            ),
        )
        result.cohorts[dim] = rank_cohorts(
            rows, dim, overall_hazard=cliff.hazard, min_concentration=CONCENTRATION_FLOOR
        )

    _measure_playback(client, title_id, cliff, bucket_sec, result)
    result.evidence = _describe(result)
    result.proposed_cause = _propose(result)
    return result


def _measure_playback(
    client: Client, title_id: str, cliff: Cliff, bucket_sec: int, result: Investigation
) -> None:
    """Compare rebuffering inside the window against the same cohorts' own
    behaviour across the whole title.

    The comparison is what makes this meaningful. A cohort that rebuffers
    everywhere has a platform problem, not a cliff; only a cohort that
    rebuffers *here specifically* explains people leaving here specifically.
    """
    window = run_named(
        client,
        "qoe_at_window",
        dict(
            title_id=title_id,
            dim="app_version",
            start_sec=cliff.start_sec,
            end_sec=cliff.end_sec,
            bucket_sec=bucket_sec,
        ),
    )
    if not window:
        return

    baseline = {
        row["cohort"]: float(row["rebuffer_event_rate"])
        for row in run_named(client, "qoe_baseline", dict(title_id=title_id, dim="app_version"))
    }

    worst = max(window, key=lambda r: float(r["rebuffer_ratio"]))
    result.worst_delivery_cohort = str(worst["cohort"])
    result.rebuffer_ratio_in_window = float(worst["rebuffer_ratio"])

    everywhere = baseline.get(result.worst_delivery_cohort, 0.0)
    result.rebuffer_ratio_baseline = everywhere
    result.rebuffer_lift = (
        result.rebuffer_ratio_in_window / everywhere if everywhere > 0 else float("inf")
    )


def _describe(result: Investigation) -> list[str]:
    """Plain sentences an editor or an ops lead can read without a stats course."""
    cliff = result.cliff
    lines = [
        f"{cliff.excess_exits:,} viewers left at {cliff.timecode_range} beyond what "
        f"this title normally loses in {cliff.duration_sec} seconds "
        f"({cliff.lift:.1f}x the baseline rate, z={cliff.z_score:.0f}).",
    ]

    delivery = result.delivery_signals
    audience = result.audience_signals

    if delivery:
        top = delivery[0]
        lines.append(
            f"Concentrated in {top.dimension}={top.value}: {top.concentration:.1f}x more "
            f"likely to leave here than the audience as a whole, on {top.cohort_share:.0%} "
            f"of sessions."
        )
    if audience:
        top = audience[0]
        lines.append(
            f"Audience skew: {top.dimension}={top.value} at {top.concentration:.1f}x."
        )
    if not delivery and not audience:
        lines.append(
            "No cohort is over-represented -- every device, build, region and language "
            "left at the same rate. Whatever happened, it happened to everyone."
        )

    if result.rebuffer_lift >= REBUFFER_LIFT_FLOOR:
        lines.append(
            f"Playback broke down here: rebuffer ratio {result.rebuffer_ratio_in_window:.4f} "
            f"against {result.rebuffer_ratio_baseline:.4f} for the same build across the "
            f"rest of the title ({result.rebuffer_lift:.0f}x worse)."
        )
    else:
        lines.append(
            f"Playback was healthy through the window (rebuffer ratio "
            f"{result.rebuffer_ratio_in_window:.4f}), so this is not a delivery failure."
        )
    return lines


def _propose(result: Investigation) -> Cause:
    """A prior from the numbers alone, for Gemini to confirm or overturn.

    Deliberately conservative: when playback is clean and the walk-out is flat
    across the audience, this returns UNKNOWN rather than STORY. Telemetry can
    prove a technical failure and it can prove an audience skew, but it cannot
    tell a boring scene from a well-earned quiet moment. That call needs eyes on
    the footage, and pretending otherwise would be the whole product lying.
    """
    if result.rebuffer_lift >= REBUFFER_LIFT_FLOOR and is_concentrated(
        result.delivery_signals, CONCENTRATION_FLOOR
    ):
        return Cause.TECHNICAL

    language_signals = [
        s for s in result.audience_signals if s.dimension in ("subtitle_gap", "locale_lang", "region")
    ]
    if is_concentrated(language_signals, CONCENTRATION_FLOOR):
        return Cause.LOCALIZATION

    return Cause.UNKNOWN
