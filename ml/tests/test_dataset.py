"""Tests for the pandas-shaped glue in dataset.py: NaN sanitizing, the
tabular-only scaler, and assemble_dataset end to end on a tiny
synthetic DataFrame (no database)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from src.dataset import assemble_dataset, sanitize_row, scale_train_test
from src.labels import MIN_BASELINE_VIDEOS

NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


def test_sanitize_row_converts_nan_and_nat_to_none():
    row = {
        "subscriber_count": float("nan"),
        "published_at": pd.NaT,
        "title": "Real Title",
        "tags": None,
        "embedding": [0.1, 0.2],
    }
    cleaned = sanitize_row(row)
    assert cleaned["subscriber_count"] is None
    assert cleaned["published_at"] is None
    assert cleaned["title"] == "Real Title"
    assert cleaned["tags"] is None
    assert cleaned["embedding"] == [0.1, 0.2]


def test_scale_train_test_leaves_embedding_raw_and_scales_tabular():
    rng = np.random.default_rng(0)
    embedding_dim = 4
    n_train, n_test = 20, 5
    embedding_train = rng.normal(size=(n_train, embedding_dim))
    embedding_test = rng.normal(size=(n_test, embedding_dim))
    # A tabular feature with an obvious non-zero mean and non-unit scale.
    tabular_train = (rng.normal(size=(n_train, 1)) * 10) + 50
    tabular_test = (rng.normal(size=(n_test, 1)) * 10) + 50

    X_train = np.hstack([embedding_train, tabular_train])
    X_test = np.hstack([embedding_test, tabular_test])

    X_train_scaled, X_test_scaled, scaler = scale_train_test(X_train, X_test, embedding_dim=embedding_dim)

    # Embedding slice is untouched.
    np.testing.assert_array_equal(X_train_scaled[:, :embedding_dim], embedding_train)
    np.testing.assert_array_equal(X_test_scaled[:, :embedding_dim], embedding_test)

    # Tabular slice is standardized on the train split.
    assert X_train_scaled[:, embedding_dim:].mean() == pytest.approx(0.0, abs=1e-8)
    assert X_train_scaled[:, embedding_dim:].std() == pytest.approx(1.0, abs=1e-8)
    assert scaler.mean_.shape == (1,)


def _video_row(video_id, channel_id, days_old, view_count, category_id="17"):
    return {
        "video_id": video_id,
        "channel_id": channel_id,
        "title": f"Video {video_id}",
        "tags": None,
        "category_id": category_id,
        "published_at": NOW - timedelta(days=days_old),
        "duration_seconds": 300,
        "is_short": False,
        "is_live_vod": False,
        "view_count": view_count,
        "like_count": 10,
        "comment_count": 1,
        "embedding": [0.0] * 384,
        "subscriber_count": 1000,
        "subs_hidden": False,
        "channel_video_count": 20,
    }


def test_assemble_dataset_returns_none_below_baseline_gate():
    rows = [_video_row("v1", "small-channel", days_old=20, view_count=1000)]
    df = pd.DataFrame(rows)
    assert assemble_dataset(df, now=NOW) is None


def test_assemble_dataset_end_to_end_shapes():
    rows = []
    # One more than the minimum so each baseline video also clears its
    # own gate after excluding itself (see the equivalent comment in
    # test_labels.py's end-to-end test).
    for i in range(MIN_BASELINE_VIDEOS + 1):
        rows.append(_video_row(f"c1-baseline-{i}", "c1", days_old=60, view_count=6000))
    rows.append(_video_row("c1-target", "c1", days_old=20, view_count=100000))
    df = pd.DataFrame(rows)

    assembled = assemble_dataset(df, now=NOW)

    assert assembled is not None
    n_rows = len(assembled["video_ids"])
    assert n_rows == MIN_BASELINE_VIDEOS + 2
    assert assembled["X"].shape == (n_rows, len(assembled["feature_names"]))
    assert assembled["y"].shape == (n_rows,)
    assert set(assembled["groups"]) == {"c1"}
    assert "c1-target" in assembled["video_ids"]


def test_assemble_dataset_drops_rows_without_embedding():
    rows = []
    for i in range(MIN_BASELINE_VIDEOS + 1):
        rows.append(_video_row(f"c1-baseline-{i}", "c1", days_old=60, view_count=6000))
    target = _video_row("c1-target", "c1", days_old=20, view_count=100000)
    target["embedding"] = None
    rows.append(target)
    df = pd.DataFrame(rows)

    assembled = assemble_dataset(df, now=NOW)

    assert assembled is not None
    assert "c1-target" not in assembled["video_ids"]
