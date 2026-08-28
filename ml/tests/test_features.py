"""Tests for the pure, single-value feature functions in features.py.

No pandas, no DB - every function here takes plain values.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.features import (
    build_feature_vector,
    category_one_hot,
    day_of_week_one_hot,
    feature_names,
    log1p_baseline_velocity,
    log1p_subscribers,
    publish_hour_sin_cos,
    subs_missing_indicator,
    tag_count,
    title_has_number,
    title_has_question_or_exclaim,
    title_length,
    top_category_ids,
    uploads_per_week,
)

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_log1p_subscribers_normal_and_hidden():
    assert log1p_subscribers(1000, False) == pytest.approx(math.log1p(1000))
    # Hidden or missing is treated as 0 (post-log1p), never a fabricated number.
    assert log1p_subscribers(1000, True) == 0.0
    assert log1p_subscribers(None, False) == 0.0


def test_subs_missing_indicator():
    assert subs_missing_indicator(True) == 1
    assert subs_missing_indicator(False) == 0


def test_log1p_baseline_velocity():
    assert log1p_baseline_velocity(None) == 0.0
    assert log1p_baseline_velocity(2.0) == pytest.approx(math.log1p(2.0))


def test_uploads_per_week_matches_scoring_py_definition():
    # Mirrors backend/tests/test_scoring.py's
    # test_uploads_per_week_counts_only_the_recent_window exactly, so a
    # drift between the two implementations would be caught here too.
    dates = [
        NOW - timedelta(days=10),
        NOW - timedelta(days=50),
        NOW - timedelta(days=200),
        None,
    ]
    assert uploads_per_week(dates, NOW, window_days=90) == pytest.approx(2 / (90 / 7))


def test_title_length_number_and_punctuation():
    assert title_length("Top 10 Goals!") == len("Top 10 Goals!")
    assert title_length(None) == 0
    assert title_has_number("Top 10 Goals") == 1
    assert title_has_number("No digits here") == 0
    assert title_has_question_or_exclaim("Is this real?") == 1
    assert title_has_question_or_exclaim("Wow!") == 1
    assert title_has_question_or_exclaim("Plain title") == 0


def test_tag_count_handles_missing():
    assert tag_count(["soccer", "highlights"]) == 2
    assert tag_count(None) == 0
    assert tag_count([]) == 0


def test_publish_hour_sin_cos_known_values():
    midnight = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    sin_val, cos_val = publish_hour_sin_cos(midnight)
    assert sin_val == pytest.approx(0.0, abs=1e-9)
    assert cos_val == pytest.approx(1.0, abs=1e-9)

    six_am = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
    sin_val, cos_val = publish_hour_sin_cos(six_am)
    assert sin_val == pytest.approx(1.0, abs=1e-9)
    assert cos_val == pytest.approx(0.0, abs=1e-9)


def test_day_of_week_one_hot():
    monday = datetime(2026, 8, 24, tzinfo=timezone.utc)  # a Monday
    assert monday.weekday() == 0
    one_hot = day_of_week_one_hot(monday)
    assert one_hot == [1, 0, 0, 0, 0, 0, 0]

    sunday = datetime(2026, 8, 30, tzinfo=timezone.utc)
    assert sunday.weekday() == 6
    assert day_of_week_one_hot(sunday) == [0, 0, 0, 0, 0, 0, 1]


def test_top_category_ids_ranks_by_frequency_then_id():
    category_ids = ["17", "17", "10", "10", "10", "20", None]
    top = top_category_ids(category_ids, top_n=2)
    assert top == ["10", "17"]
    # Ties broken by id ascending.
    tied = top_category_ids(["1", "2"], top_n=1)
    assert tied == ["1"]


def test_category_one_hot_known_and_other():
    top_categories = ["10", "17", "20"]
    assert category_one_hot("17", top_categories) == [0, 1, 0, 0]
    assert category_one_hot("99", top_categories) == [0, 0, 0, 1]
    assert category_one_hot(None, top_categories) == [0, 0, 0, 1]


def test_feature_names_length_matches_build_feature_vector():
    top_categories = ["10", "17"]
    names = feature_names(top_categories)
    row = {
        "embedding": [0.1] * 384,
        "subscriber_count": 500,
        "subs_hidden": False,
        "title": "Top 5 Goals?",
        "duration_seconds": 120,
        "is_short": False,
        "tags": ["a", "b"],
        "published_at": NOW,
        "category_id": "17",
    }
    vector = build_feature_vector(
        row,
        baseline=1.5,
        channel_published_dates=[NOW - timedelta(days=5)],
        now=NOW,
        top_categories=top_categories,
    )
    assert len(vector) == len(names)
    # 384 embedding dims + 12 scalar tabular features + 7 weekday + (2
    # top categories + 1 other).
    assert len(names) == 384 + 12 + 7 + 3
