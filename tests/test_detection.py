"""Detection logic is the part that must not be wrong.

If merging is broken the agent reports the same scene three times; if the
composed statistics are wrong it ranks a small cliff above a large one and
recommends the wrong cut. None of that needs a cluster to catch.
"""

import math

import pytest

from walkout.detection import (
    is_concentrated,
    merge_cliffs,
    rank_cohorts,
    recoverable_watch_hours,
)
from walkout.models import timecode


def bucket(position, *, reached, exits, hazard, baseline=0.006):
    return {
        "position_sec": position,
        "reached": reached,
        "exits": exits,
        "hazard": hazard,
        "baseline_hazard": baseline,
    }


class TestMergeCliffs:
    def test_consecutive_buckets_become_one_cliff(self):
        rows = [
            bucket(240, reached=13974, exits=255, hazard=0.01825),
            bucket(250, reached=13719, exits=261, hazard=0.01902),
            bucket(260, reached=13458, exits=257, hazard=0.01910),
        ]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        assert cliff.start_sec == 240
        assert cliff.end_sec == 270
        assert cliff.exits == 773
        assert cliff.reached == 13974  # the risk set entering the window

    def test_separate_events_stay_separate(self):
        rows = [
            bucket(240, reached=13974, exits=255, hazard=0.01825),
            bucket(560, reached=11128, exits=154, hazard=0.01384),
        ]
        assert len(merge_cliffs(rows, bucket_sec=10)) == 2

    def test_gap_tolerance_bridges_a_dip_below_the_floor(self):
        rows = [
            bucket(560, reached=11128, exits=154, hazard=0.01384),
            bucket(580, reached=10834, exits=157, hazard=0.01449),
        ]
        assert len(merge_cliffs(rows, bucket_sec=10, max_gap_sec=0)) == 2
        (merged,) = merge_cliffs(rows, bucket_sec=10, max_gap_sec=10)
        assert (merged.start_sec, merged.end_sec) == (560, 590)

    def test_window_hazard_compounds_rather_than_averaging(self):
        rows = [bucket(100, reached=1000, exits=100, hazard=0.10) for _ in range(2)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        # 1 - 0.9*0.9, not the mean of 0.10 and 0.10
        assert cliff.hazard == pytest.approx(0.19, abs=1e-4)

    def test_baseline_compounds_over_the_same_window(self):
        rows = [bucket(100, reached=1000, exits=100, hazard=0.10, baseline=0.01) for _ in range(3)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        assert cliff.baseline_hazard == pytest.approx(1 - 0.99**3, abs=1e-5)

    def test_ranked_by_excess_not_by_lift(self):
        # A short violent spike among few remaining viewers costs less audience
        # than a milder cliff hit by everyone. Ranking must follow the damage.
        small_but_sharp = [bucket(800, reached=500, exits=100, hazard=0.20)]
        large_but_mild = [bucket(200, reached=20000, exits=800, hazard=0.04)]
        cliffs = merge_cliffs(small_but_sharp + large_but_mild, bucket_sec=10)
        assert cliffs[0].start_sec == 200

    def test_no_rows_is_not_an_error(self):
        assert merge_cliffs([], bucket_sec=10) == []

    def test_unordered_input_is_sorted_first(self):
        rows = [
            bucket(260, reached=13458, exits=257, hazard=0.01910),
            bucket(240, reached=13974, exits=255, hazard=0.01825),
            bucket(250, reached=13719, exits=261, hazard=0.01902),
        ]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        assert (cliff.start_sec, cliff.end_sec) == (240, 270)

    def test_z_score_is_a_binomial_test_over_the_whole_window(self):
        rows = [bucket(100, reached=10000, exits=200, hazard=0.02, baseline=0.01)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        expected = 10000 * 0.01
        z = (200 - expected) / math.sqrt(10000 * 0.01 * 0.99)
        assert cliff.z_score == pytest.approx(round(z, 2), abs=0.01)


def cohort(value, *, hazard, reached=5000, exits=200, share=0.2):
    return {
        "cohort": value,
        "reached": reached,
        "exits_in_window": exits,
        "hazard_in_window": hazard,
        "cohort_share": share,
    }


class TestRankCohorts:
    def test_flat_across_cohorts_yields_no_signal(self):
        # This is the shape of an editorial problem: everybody reacted alike.
        rows = [cohort(v, hazard=0.019) for v in ("mobile_android", "tv_roku", "web_desktop")]
        assert rank_cohorts(rows, "device", overall_hazard=0.019) == []

    def test_one_build_spiking_is_surfaced(self):
        rows = [
            cohort("4.2.1", hazard=0.085),
            cohort("4.3.0", hazard=0.006),
            cohort("4.1.7", hazard=0.007),
        ]
        signals = rank_cohorts(rows, "app_version", overall_hazard=0.019)
        assert [s.value for s in signals] == ["4.2.1"]
        assert signals[0].concentration == pytest.approx(4.47, abs=0.01)
        assert is_concentrated(signals)

    def test_editorial_cliff_is_not_concentrated(self):
        rows = [cohort(v, hazard=0.020) for v in ("US", "IN", "DE")]
        assert not is_concentrated(rank_cohorts(rows, "region", overall_hazard=0.019))


class TestRecoverableWatchHours:
    def test_a_cliff_at_the_credits_costs_nothing(self):
        rows = [bucket(880, reached=1000, exits=500, hazard=0.5)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        assert recoverable_watch_hours(cliff, duration_sec=888) == 0.0

    def test_early_cliffs_cost_the_whole_remaining_runtime(self):
        rows = [bucket(240, reached=13974, exits=255, hazard=0.01825)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        hours = recoverable_watch_hours(cliff, duration_sec=888)
        assert hours == pytest.approx(cliff.excess_exits * (888 - 250) / 3600, abs=1e-6)

    def test_completion_rate_scales_the_estimate_down(self):
        rows = [bucket(240, reached=13974, exits=255, hazard=0.01825)]
        (cliff,) = merge_cliffs(rows, bucket_sec=10)
        full = recoverable_watch_hours(cliff, 888)
        assert recoverable_watch_hours(cliff, 888, 0.5) == pytest.approx(full / 2)


def test_timecode_is_what_an_editor_can_type():
    assert timecode(0) == "00:00:00"
    assert timecode(248) == "00:04:08"
    assert timecode(3661) == "01:01:01"
