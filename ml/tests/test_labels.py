"""Tests for the breakout-label math: pure functions and plain dicts.

No database, no pandas. Every test builds its inputs by hand so the
expected output can be hand-computed and checked exactly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.labels import (
    BASELINE_MAX_AGE_DAYS,
    BASELINE_MIN_AGE_DAYS,
    BREAKOUT_MULTIPLIER,
    MAX_LABEL_AGE_DAYS,
    MIN_BASELINE_VIDEOS,
    MIN_LABEL_AGE_DAYS,
    age_days,
    channel_baseline,
    compute_labels,
    expected_views_per_day,
    fit_view_curve,
    normalized_velocity,
    views_per_day,
)

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_age_days_and_views_per_day():
    assert age_days(NOW - timedelta(days=10), NOW) == 10
    assert views_per_day(1000, 10) == 100.0
    # Same-day publish floors at 1 day rather than dividing by zero.
    assert views_per_day(1000, 0) == 1000.0


def test_fit_view_curve_buckets_by_week_and_takes_median():
    # Two videos in bucket 0 (age 0-6), one in bucket 1 (age 7-13).
    observations = [(0, 100.0), (5, 200.0), (10, 10.0)]
    curve = fit_view_curve(observations, bucket_days=7)
    assert curve == {0: 150.0, 1: 10.0}


def test_expected_views_per_day_falls_back_to_nearest_bucket():
    curve = {0: 100.0, 5: 20.0}
    # Exact bucket present.
    assert expected_views_per_day(3, curve, bucket_days=7) == 100.0
    # Bucket 2 (age 14-20) is missing; nearest of {0, 5} is 0.
    assert expected_views_per_day(15, curve, bucket_days=7) == 100.0
    # Empty curve: no signal at all.
    assert expected_views_per_day(15, {}, bucket_days=7) == 0.0


def test_normalized_velocity_divides_by_expected_and_guards_zero():
    curve = {1: 50.0}
    assert normalized_velocity(100.0, 10, curve, bucket_days=7) == pytest.approx(2.0)
    # Expected is 0 (empty curve): no usable signal, not a ZeroDivisionError.
    assert normalized_velocity(100.0, 10, {}, bucket_days=7) is None


def test_channel_baseline_requires_min_count():
    pool = [(f"v{i}", 1.0) for i in range(MIN_BASELINE_VIDEOS - 1)]
    assert channel_baseline(pool) is None

    pool_enough = [(f"v{i}", float(i)) for i in range(MIN_BASELINE_VIDEOS)]
    # median of 0,1,2,3,4 == 2.0
    assert channel_baseline(pool_enough) == 2.0


def test_channel_baseline_excludes_the_target_video():
    pool = [(f"v{i}", 10.0) for i in range(MIN_BASELINE_VIDEOS)] + [("target", 0.0)]
    # With "target" included, count is 6 (still enough), but it must be
    # excluded from its own baseline.
    baseline = channel_baseline(pool, exclude_video_id="target")
    assert baseline == 10.0

    # Excluding a video that drops the pool below min_count returns None.
    small_pool = [(f"v{i}", 10.0) for i in range(MIN_BASELINE_VIDEOS - 1)] + [("target", 0.0)]
    assert channel_baseline(small_pool, exclude_video_id="target") is None


def _row(video_id, channel_id, days_old, view_count, is_live_vod=False):
    return {
        "video_id": video_id,
        "channel_id": channel_id,
        "view_count": view_count,
        "published_at": NOW - timedelta(days=days_old),
        "is_live_vod": is_live_vod,
    }


def test_compute_labels_end_to_end_breakout_and_normal():
    rows = []
    # Channel "c1": MIN_BASELINE_VIDEOS + 1 baseline videos (aged 30-180)
    # with steady velocity (vpd=100) - one more than the minimum, so that
    # each baseline video, when excluding *itself* from its own baseline
    # pool (per the "OTHER videos" rule), still has exactly
    # MIN_BASELINE_VIDEOS peers left and clears its own gate. Plus a
    # handful of same-age (20-day) filler videos also at the typical
    # vpd=100 so the V(t) curve's age-20 bucket reflects what's typical
    # at that age rather than being dragged around by a single outlier's
    # median contribution.
    for i in range(MIN_BASELINE_VIDEOS + 1):
        rows.append(_row(f"c1-baseline-{i}", "c1", days_old=60, view_count=6000))  # vpd 100
    for i in range(4):
        rows.append(_row(f"c1-filler-{i}", "c1", days_old=20, view_count=2000))  # vpd 100
    # Massively outpaces the age-20 typical rate (vpd 5000 vs ~100).
    rows.append(_row("c1-breakout", "c1", days_old=20, view_count=100000))
    # Close to the age-20 typical rate.
    rows.append(_row("c1-normal", "c1", days_old=20, view_count=2200))  # vpd 110

    result = compute_labels(rows, NOW)

    assert result["c1-breakout"]["label"] == 1
    assert result["c1-normal"]["label"] == 0
    # Baseline videos themselves are inside the 7-180 window too (60
    # days), so they get evaluated against the *other* baseline videos.
    assert "c1-baseline-0" in result


def test_compute_labels_skips_channel_below_baseline_gate():
    rows = [_row("only-video", "small-channel", days_old=20, view_count=5000)]
    result = compute_labels(rows, NOW)
    assert result == {}


def test_compute_labels_skips_out_of_window_and_live_vod():
    rows = [
        _row("too-young", "c1", days_old=MIN_LABEL_AGE_DAYS - 1, view_count=1000),
        _row("too-old", "c1", days_old=MAX_LABEL_AGE_DAYS + 1, view_count=1000),
        _row("live-vod", "c1", days_old=20, view_count=1000, is_live_vod=True),
    ]
    for i in range(MIN_BASELINE_VIDEOS):
        rows.append(_row(f"c1-baseline-{i}", "c1", days_old=60, view_count=1000))

    result = compute_labels(rows, NOW)
    assert "too-young" not in result
    assert "too-old" not in result
    assert "live-vod" not in result


def test_compute_labels_ignores_missing_view_count_or_published_at():
    rows = [
        {
            "video_id": "no-views",
            "channel_id": "c1",
            "view_count": None,
            "published_at": NOW - timedelta(days=20),
            "is_live_vod": False,
        },
        {
            "video_id": "no-date",
            "channel_id": "c1",
            "view_count": 1000,
            "published_at": None,
            "is_live_vod": False,
        },
    ]
    result = compute_labels(rows, NOW)
    assert result == {}


def test_breakout_multiplier_and_baseline_window_constants():
    # Sanity check the constants documented in labels.py's module
    # docstring haven't drifted silently.
    assert BREAKOUT_MULTIPLIER == 3.0
    assert BASELINE_MIN_AGE_DAYS == 30
    assert BASELINE_MAX_AGE_DAYS == 180
