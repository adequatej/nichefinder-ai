"""Tests for the opportunity-scoring math: pure functions and plain dicts.

No database, no clustering. score_niches is exercised with raw_stats
dicts built by hand, mirroring how compute_niche_raw_stats would shape
them.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.scoring import (
    MIN_ELIGIBLE_CHANNELS,
    MIN_ELIGIBLE_VIDEOS,
    SHRINKAGE_VIDEO_THRESHOLD,
    engagement_ratio,
    is_eligible,
    median,
    score_niches,
    shrink_toward_global,
    shrinkage_weight,
    sigmoid,
    uploads_per_week,
    view_velocity,
    zscore_map,
)

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_view_velocity_basic_and_floor():
    assert view_velocity(100, NOW - timedelta(days=2), NOW) == 50.0
    # Same-day publish floors at 1 day rather than dividing by zero.
    assert view_velocity(100, NOW, NOW) == 100.0
    assert view_velocity(None, NOW, NOW) is None
    assert view_velocity(100, None, NOW) is None


def test_engagement_ratio_guards_zero_views():
    assert engagement_ratio(100, 10, 5) == pytest.approx(0.15)
    assert engagement_ratio(0, 10, 5) is None
    assert engagement_ratio(None, 10, 5) is None
    assert engagement_ratio(100, None, None) == 0.0


def test_median_handles_empty():
    assert median([1, 2, 3]) == 2
    assert median([]) == 0.0


def test_uploads_per_week_counts_only_the_recent_window():
    dates = [
        NOW - timedelta(days=10),
        NOW - timedelta(days=50),
        NOW - timedelta(days=200),
        None,
    ]
    # 2 of the 4 fall inside the 90-day window; 90/7 weeks in it.
    assert uploads_per_week(dates, NOW, window_days=90) == pytest.approx(2 / (90 / 7))


def test_eligibility_floor():
    assert is_eligible(MIN_ELIGIBLE_VIDEOS, MIN_ELIGIBLE_CHANNELS) is True
    assert is_eligible(MIN_ELIGIBLE_VIDEOS - 1, MIN_ELIGIBLE_CHANNELS) is False
    assert is_eligible(MIN_ELIGIBLE_VIDEOS, MIN_ELIGIBLE_CHANNELS - 1) is False


def test_shrinkage_weight_ramps_and_caps():
    assert shrinkage_weight(0) == 0.0
    assert shrinkage_weight(SHRINKAGE_VIDEO_THRESHOLD / 2) == pytest.approx(0.5)
    assert shrinkage_weight(SHRINKAGE_VIDEO_THRESHOLD) == 1.0
    assert shrinkage_weight(SHRINKAGE_VIDEO_THRESHOLD * 10) == 1.0
    # The threshold must sit above the eligibility floor, or every
    # eligible niche would already get full weight.
    assert SHRINKAGE_VIDEO_THRESHOLD > MIN_ELIGIBLE_VIDEOS


def test_shrink_toward_global():
    assert shrink_toward_global(10.0, 0.0, weight=1.0) == 10.0
    assert shrink_toward_global(10.0, 0.0, weight=0.0) == 0.0
    assert shrink_toward_global(10.0, 0.0, weight=0.5) == 5.0


def test_sigmoid_midpoint_and_symmetry():
    assert sigmoid(0.0) == pytest.approx(0.5)
    assert sigmoid(2.0) + sigmoid(-2.0) == pytest.approx(1.0)


def test_zscore_map_single_value_and_zero_variance():
    assert zscore_map({1: 5.0}) == {1: 0.0}
    assert zscore_map({1: 5.0, 2: 5.0}) == {1: 0.0, 2: 0.0}
    assert zscore_map({}) == {}


def test_zscore_map_two_values_are_plus_minus_one():
    result = zscore_map({1: 10.0, 2: 20.0})
    assert result[1] == pytest.approx(-1.0)
    assert result[2] == pytest.approx(1.0)


def _stats(video_count, channel_count, views, velocity, engagement, uploads):
    return {
        "video_count": video_count,
        "channel_count": channel_count,
        "active_channel_count": channel_count,
        "median_views": views,
        "median_velocity": velocity,
        "median_engagement": engagement,
        "uploads_per_week": uploads,
    }


def test_score_niches_hand_computed_two_niches():
    # Niche 1: high demand, low supply. Niche 2: low demand, high
    # supply. With exactly two eligible niches every z-score is
    # exactly +-1.0 (the two-point z-score identity), and both niches
    # sit at or above SHRINKAGE_VIDEO_THRESHOLD so shrinkage weight is
    # 1.0 and does not perturb the numbers.
    raw_stats = {
        1: _stats(
            video_count=50, channel_count=3, views=5000, velocity=200,
            engagement=0.08, uploads=1.0,
        ),
        2: _stats(
            video_count=60, channel_count=10, views=1000, velocity=50,
            engagement=0.02, uploads=5.0,
        ),
    }
    result = score_niches(raw_stats)

    assert result[1]["demand_score"] == pytest.approx(1.0)
    assert result[1]["supply_score"] == pytest.approx(-1.0)
    assert result[2]["demand_score"] == pytest.approx(-1.0)
    assert result[2]["supply_score"] == pytest.approx(1.0)

    expected_opportunity_1 = 100 / (1 + math.exp(-2.0))
    expected_opportunity_2 = 100 / (1 + math.exp(2.0))
    assert result[1]["opportunity_score"] == pytest.approx(expected_opportunity_1)
    assert result[2]["opportunity_score"] == pytest.approx(expected_opportunity_2)
    assert result[1]["opportunity_score"] > 50 > result[2]["opportunity_score"]

    assert result[1]["score_components"]["shrinkage_weight"] == 1.0
    assert result[2]["score_components"]["shrinkage_weight"] == 1.0
    assert result[1]["score_components"]["median_views"] == 5000


def test_score_niches_excludes_ineligible_niches():
    raw_stats = {
        1: _stats(
            video_count=50, channel_count=3, views=5000, velocity=200,
            engagement=0.08, uploads=1.0,
        ),
        # Below the video floor: excluded from scoring entirely, and
        # does not pollute the eligible set's z-scores.
        2: _stats(
            video_count=10, channel_count=1, views=999999, velocity=999999,
            engagement=1.0, uploads=50.0,
        ),
    }
    result = score_niches(raw_stats)
    assert set(result.keys()) == {1}


def test_score_niches_single_eligible_niche_scores_fifty():
    raw_stats = {
        1: _stats(
            video_count=50, channel_count=3, views=5000, velocity=200,
            engagement=0.08, uploads=1.0,
        ),
    }
    result = score_niches(raw_stats)
    assert result[1]["demand_score"] == 0.0
    assert result[1]["supply_score"] == 0.0
    assert result[1]["opportunity_score"] == pytest.approx(50.0)


def test_score_niches_no_eligible_niches_returns_empty():
    raw_stats = {
        1: _stats(video_count=5, channel_count=1, views=100, velocity=10, engagement=0.1, uploads=1.0),
    }
    assert score_niches(raw_stats) == {}


def test_shrinkage_pulls_small_eligible_niche_toward_global_median():
    # Same view/velocity/engagement stats for niche 1 in both runs;
    # only its video_count changes. One version sits well under
    # SHRINKAGE_VIDEO_THRESHOLD (partial shrinkage weight), the other
    # is safely over it (full weight, no shrinkage). Niches 2-4 anchor
    # a "normal" range so niche 1's huge view count is a real outlier.
    def _raw_stats(niche_1_video_count):
        return {
            1: _stats(
                video_count=niche_1_video_count, channel_count=3,
                views=1_000_000, velocity=1.0, engagement=0.01, uploads=1.0,
            ),
            2: _stats(video_count=200, channel_count=3, views=2000, velocity=1.0, engagement=0.01, uploads=1.0),
            3: _stats(video_count=200, channel_count=3, views=1000, velocity=1.0, engagement=0.01, uploads=1.0),
            4: _stats(video_count=200, channel_count=3, views=1500, velocity=1.0, engagement=0.01, uploads=1.0),
        }

    shrunk = score_niches(_raw_stats(MIN_ELIGIBLE_VIDEOS))
    full_weight = score_niches(_raw_stats(SHRINKAGE_VIDEO_THRESHOLD * 4))

    weight_shrunk = shrunk[1]["score_components"]["shrinkage_weight"]
    weight_full = full_weight[1]["score_components"]["shrinkage_weight"]
    assert 0 < weight_shrunk < 1
    assert weight_full == 1.0
    # Shrinking niche 1's outlier view count toward the pack pulls its
    # demand score down relative to letting the raw number stand.
    assert shrunk[1]["demand_score"] < full_weight[1]["demand_score"]
