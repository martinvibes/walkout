"""Scoring the agent against planted ground truth.

A diagnosis that sounds convincing and a diagnosis that is correct are not the
same thing, and nothing about reading the output tells you which one you have.
The simulator plants cliffs with known causes precisely so that question can be
answered with a number instead of a vibe.

Two failure modes are graded separately, because they cost different things:

* a **miss** -- a real cliff the detector never surfaced. Silent, and the worst
  kind: the product simply fails to do its job and no one knows.
* a **false positive** -- a finding with nothing behind it. Louder and cheaper
  to catch, but it is what destroys trust in a tool like this. The decoy exists
  to make sure ordinary noise never gets promoted into a recommendation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from clickhouse_connect.driver.client import Client

from .analysis import find_cliffs, investigate
from .config import DATA_DIR
from .models import Cause, Cliff

DECOY = "decoy"


@dataclass
class Grade:
    """One planted cliff, and what the pipeline did about it."""

    cliff_id: str
    expected_cause: str
    window: str
    should_report: bool
    reported: bool
    found_window: str = ""
    proposed_cause: str = ""
    cause_correct: bool | None = None

    @property
    def passed(self) -> bool:
        if not self.should_report:
            return not self.reported
        # A cause the telemetry cannot establish alone is left to Gemini, so an
        # UNKNOWN proposal on a story cliff is the pipeline behaving correctly,
        # not failing. What must never happen is a *confident wrong* cause.
        return self.reported and self.cause_correct is not False


@dataclass
class Report:
    grades: list[Grade] = field(default_factory=list)
    unexplained: list[Cliff] = field(default_factory=list)
    detect_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.grades) and not self.unexplained

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "detect_ms": round(self.detect_ms, 1),
            "grades": [g.__dict__ for g in self.grades],
            "unexplained": [c.timecode_range for c in self.unexplained],
        }


# Which proposed causes count as correct for each planted cause. Telemetry
# alone cannot prove a story problem, so UNKNOWN is an acceptable proposal
# there -- that is the handoff to the model, by design.
ACCEPTABLE = {
    "story": {Cause.UNKNOWN, Cause.STORY, Cause.PACING},
    "technical": {Cause.TECHNICAL},
    "localization": {Cause.LOCALIZATION},
}


def evaluate(client: Client, title_id: str = "sintel") -> Report:
    """Run detection and investigation, then grade both against ground truth."""
    import time

    truth = json.loads((DATA_DIR / "ground_truth.json").read_text())
    planted = truth["cliffs"]

    started = time.perf_counter()
    cliffs = find_cliffs(client, title_id)
    report = Report(detect_ms=(time.perf_counter() - started) * 1000)

    matched: set[int] = set()
    for spec in planted:
        overlap = [
            (i, c) for i, c in enumerate(cliffs)
            if c.start_sec < spec["end"] and c.end_sec > spec["start"]
        ]
        grade = Grade(
            cliff_id=spec["id"],
            expected_cause=spec["cause"],
            window=f"{spec['start']}-{spec['end']}",
            should_report=spec["cause"] != DECOY,
            reported=bool(overlap),
        )
        if overlap:
            index, cliff = overlap[0]
            matched.add(index)
            grade.found_window = cliff.timecode_range
            if grade.should_report:
                proposed = investigate(client, title_id, cliff).proposed_cause
                grade.proposed_cause = proposed.value
                grade.cause_correct = proposed in ACCEPTABLE[spec["cause"]]
        report.grades.append(grade)

    # Anything reported that was never planted is a false positive, and the
    # decoy is not the only way to produce one.
    report.unexplained = [c for i, c in enumerate(cliffs) if i not in matched]
    return report


def render(report: Report) -> str:
    lines = [
        f"detection: {report.detect_ms:.0f} ms",
        "",
        f"{'':<6}{'cause':<14}{'planted':<12}{'found':<22}{'proposed':<14}{'':<6}",
    ]
    for g in report.grades:
        verdict = "PASS" if g.passed else "FAIL"
        expectation = g.found_window or ("(correctly ignored)" if not g.should_report else "MISSED")
        lines.append(
            f"{g.cliff_id:<6}{g.expected_cause:<14}{g.window:<12}{expectation:<22}"
            f"{g.proposed_cause or '-':<14}{verdict:<6}"
        )
    for cliff in report.unexplained:
        lines.append(f"{'!':<6}{'unplanted':<14}{'-':<12}{cliff.timecode_range:<22}{'-':<14}{'FAIL':<6}")
    lines.append("")
    lines.append("ALL PASS" if report.passed else "FAILURES ABOVE")
    return "\n".join(lines)
