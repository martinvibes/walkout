"""Turning flagged buckets into cliffs a human can act on.

The SQL flags individual ten-second buckets. A real walk-out is rarely one
bucket -- a scene that loses the room loses it over twenty or thirty seconds --
so consecutive flags belong to the same event and have to be merged before any
of them reach the model. Without this the agent investigates the same scene
three times and reports it three times.

Everything here is pure: rows in, dataclasses out, no I/O. That is what makes
it testable without a cluster.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from .models import Cliff, CohortSignal


def merge_cliffs(
    rows: Iterable[dict[str, Any]],
    bucket_sec: int,
    max_gap_sec: int = 0,
) -> list[Cliff]:
    """Collapse runs of flagged buckets into single cliffs, strongest first.

    `max_gap_sec` tolerates a bucket that dipped just under the significance
    floor in the middle of an otherwise continuous walk-out. Default 0 keeps
    separate events separate.

    Combined statistics are composed properly rather than averaged:

    * hazard over the merged window is the chance a viewer present at the start
      leaves before the end -- ``1 - prod(1 - h_i)`` -- not the mean of the
      per-bucket hazards, which would understate a long cliff.
    * significance is a binomial z-test over the summed window, since the sum
      of independent binomials is what we actually observed.
    """
    ordered = sorted(rows, key=lambda r: int(r["position_sec"]))
    if not ordered:
        return []

    groups: list[list[dict[str, Any]]] = [[ordered[0]]]
    for row in ordered[1:]:
        previous_end = int(groups[-1][-1]["position_sec"]) + bucket_sec
        if int(row["position_sec"]) - previous_end <= max_gap_sec:
            groups[-1].append(row)
        else:
            groups.append([row])

    return sorted(
        (_compose(g, bucket_sec) for g in groups),
        key=lambda c: c.excess_exits,
        reverse=True,
    )


def _compose(group: Sequence[dict[str, Any]], bucket_sec: int) -> Cliff:
    h0 = float(group[0]["baseline_hazard"])
    start = int(group[0]["position_sec"])
    end = int(group[-1]["position_sec"]) + bucket_sec

    survival = 1.0
    for row in group:
        survival *= 1.0 - float(row["hazard"])
    hazard = 1.0 - survival
    baseline = 1.0 - (1.0 - h0) ** len(group)

    exits = sum(int(r["exits"]) for r in group)
    expected = sum(int(r["reached"]) * h0 for r in group)
    variance = sum(int(r["reached"]) * h0 * (1.0 - h0) for r in group)

    return Cliff(
        start_sec=start,
        end_sec=end,
        reached=int(group[0]["reached"]),
        exits=exits,
        hazard=round(hazard, 5),
        baseline_hazard=round(baseline, 5),
        lift=round(hazard / baseline, 2) if baseline else 0.0,
        z_score=round((exits - expected) / math.sqrt(variance), 2) if variance > 0 else 0.0,
        excess_exits=max(int(round(exits - expected)), 0),
    )


def rank_cohorts(
    rows: Iterable[dict[str, Any]],
    dimension: str,
    overall_hazard: float,
    min_concentration: float = 1.3,
) -> list[CohortSignal]:
    """Which slices of the audience actually drove this cliff.

    Concentration compares a cohort's hazard inside the window against the
    hazard for the title's audience as a whole. Around 1.0 everywhere means the
    cliff is editorial: everyone reacted the same way. A single cohort at 4x
    means it is not the scene, it is that cohort's playback, build, or language.
    """
    signals = []
    for row in rows:
        hazard = float(row["hazard_in_window"])
        concentration = hazard / overall_hazard if overall_hazard else 0.0
        if concentration < min_concentration:
            continue
        signals.append(
            CohortSignal(
                dimension=dimension,
                value=str(row["cohort"]),
                reached=int(row["reached"]),
                exits_in_window=int(row["exits_in_window"]),
                hazard_in_window=round(hazard, 5),
                cohort_share=float(row["cohort_share"]),
                concentration=round(concentration, 2),
            )
        )
    return sorted(signals, key=lambda s: s.concentration, reverse=True)


def is_concentrated(signals: Sequence[CohortSignal], threshold: float = 2.0) -> bool:
    """True when the walk-out is confined to specific cohorts rather than the
    whole audience -- the first fork in the story-versus-technical decision."""
    return bool(signals) and signals[0].concentration >= threshold


def recoverable_watch_hours(
    cliff: Cliff,
    duration_sec: int,
    completion_rate_after: float = 1.0,
) -> float:
    """Watch-hours the cliff is costing, if it were fixed.

    Deliberately conservative: it credits the excess walk-outs only with the
    runtime they would have gone on to watch at the rate viewers who *survived*
    the cliff actually watched. Pass the observed rate; the 1.0 default assumes
    they would have finished, which is the optimistic bound.
    """
    remaining = max(duration_sec - cliff.end_sec, 0)
    return cliff.excess_exits * remaining * completion_rate_after / 3600.0
