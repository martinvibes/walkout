"""The proposal rules decide what Gemini is asked to adjudicate.

If they over-claim, the agent recuts a scene that was fine. If they under-claim,
a delivery outage gets blamed on the edit. Both are the product being wrong in
the way it exists to prevent, so the rules are tested directly.
"""

import pytest

from walkout.analysis import Investigation, _describe, _propose
from walkout.models import Cause, Cliff, CohortSignal


def a_cliff(**kw):
    defaults = dict(
        start_sec=240, end_sec=270, reached=13974, exits=773, hazard=0.055,
        baseline_hazard=0.018, lift=3.0, z_score=113.0, excess_exits=6260,
    )
    return Cliff(**{**defaults, **kw})


def signal(dimension, value, concentration, share=0.2):
    return CohortSignal(
        dimension=dimension, value=value, reached=5000, exits_in_window=200,
        hazard_in_window=0.05, cohort_share=share, concentration=concentration,
    )


class TestProposedCause:
    def test_broken_playback_in_one_build_is_technical(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={"app_version": [signal("app_version", "4.2.1", 1.96)]},
            rebuffer_lift=9.0,
        )
        assert _propose(inv) == Cause.TECHNICAL

    def test_broken_playback_across_everyone_is_not_pinned_on_delivery(self):
        # Rebuffering everywhere with no cohort skew is a platform-wide problem,
        # not an explanation for people leaving at this timecode.
        inv = Investigation(cliff=a_cliff(), cohorts={}, rebuffer_lift=9.0)
        assert _propose(inv) == Cause.UNKNOWN

    def test_cohort_skew_with_clean_playback_is_not_technical(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={"app_version": [signal("app_version", "4.2.1", 3.0)]},
            rebuffer_lift=1.1,
        )
        assert _propose(inv) != Cause.TECHNICAL

    def test_language_skew_with_clean_playback_is_localization(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={"subtitle_gap": [signal("subtitle_gap", "no subtitles", 2.09, 0.30)]},
            rebuffer_lift=1.0,
        )
        assert _propose(inv) == Cause.LOCALIZATION

    def test_flat_and_clean_stays_unknown_until_something_watches_the_footage(self):
        # The honest answer. Telemetry can prove a technical failure and it can
        # prove an audience skew, but it cannot tell a scene that drags from a
        # quiet moment the audience earned. Claiming STORY here would be the
        # product asserting something it has no evidence for.
        inv = Investigation(cliff=a_cliff(), cohorts={}, rebuffer_lift=1.0)
        assert _propose(inv) == Cause.UNKNOWN

    def test_technical_outranks_a_coincident_language_skew(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={
                "app_version": [signal("app_version", "4.2.1", 2.5)],
                "region": [signal("region", "IN", 1.9)],
            },
            rebuffer_lift=12.0,
        )
        assert _propose(inv) == Cause.TECHNICAL

    def test_marginal_concentration_does_not_trip_a_verdict(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={"region": [signal("region", "IN", 1.4)]},
            rebuffer_lift=1.0,
        )
        assert _propose(inv) == Cause.UNKNOWN


class TestEvidence:
    def test_flat_cliffs_say_so_in_words(self):
        lines = _describe(Investigation(cliff=a_cliff(), cohorts={}, rebuffer_lift=1.0))
        assert any("No cohort is over-represented" in line for line in lines)
        assert any("not a delivery failure" in line for line in lines)

    def test_every_figure_quoted_comes_from_the_cliff(self):
        inv = Investigation(cliff=a_cliff(excess_exits=6260, lift=3.0), rebuffer_lift=1.0)
        assert "6,260" in _describe(inv)[0]

    def test_broken_playback_is_quantified_against_the_same_build_elsewhere(self):
        inv = Investigation(
            cliff=a_cliff(),
            cohorts={"device": [signal("device", "tv_android", 1.8)]},
            rebuffer_ratio_in_window=0.1296,
            rebuffer_ratio_baseline=0.0149,
            rebuffer_lift=9.0,
        )
        line = next(l for l in _describe(inv) if "Playback broke down" in l)
        assert "0.1296" in line and "0.0149" in line and "9x worse" in line
