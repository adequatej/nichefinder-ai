"""Glue between export_dataset.py's parquet file and the pure label
and feature logic in labels.py / features.py. Everything pandas-shaped
lives here so those two modules stay unit-testable with plain values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from src import features, labels

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATASET_PATH = DATA_DIR / "dataset.parquet"
FOLDS_PATH = DATA_DIR / "folds.json"

EMBEDDING_DIM = features.EMBEDDING_DIM


def load_export(path: str | Path = DATASET_PATH) -> pd.DataFrame:
    return pd.read_parquet(path)


def _is_na(value) -> bool:
    """pd.isna, guarded against list/array values (embedding, tags),
    which raise or return an array rather than a single bool."""
    if isinstance(value, (list, np.ndarray)):
        return False
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def sanitize_row(row: dict) -> dict:
    """NaN/NaT -> None. Postgres NULLs round-trip through pandas as NaN
    or NaT depending on column dtype; labels.py and features.py only
    know about None, matching how the rest of this repo represents a
    missing value."""
    return {key: (None if _is_na(value) else value) for key, value in row.items()}


def assemble_dataset(df: pd.DataFrame, now: datetime | None = None) -> dict | None:
    """DataFrame from export_dataset.py -> arrays ready for training.

    Returns None when no video in `df` clears both labels.py's
    eligibility window and its channel-baseline gate — an expected
    outcome on a small or thin corpus (see labels.py's docstring), not
    an error.

    Returns {X, y, video_ids, groups, feature_names, top_categories}.
    `groups` is channel_id per row, for folds.make_folds. A video only
    becomes a row here if it also has an embedding — a video can be
    English-detected and counted toward channel-level aggregates
    (uploads_per_week, the baseline pool) before it's been embedded,
    but it can't itself become a training example without one.
    """
    now = now or datetime.now(timezone.utc)
    rows = [sanitize_row(row) for row in df.to_dict("records")]

    label_by_video = labels.compute_labels(rows, now)
    if not label_by_video:
        return None

    top_categories = features.top_category_ids(row.get("category_id") for row in rows)

    channel_published_dates: dict[str, list] = {}
    for row in rows:
        channel_published_dates.setdefault(row["channel_id"], []).append(row.get("published_at"))

    feature_rows: list[list[float]] = []
    video_ids: list[str] = []
    y: list[int] = []
    groups: list[str] = []
    for row in rows:
        video_id = row["video_id"]
        label_info = label_by_video.get(video_id)
        if label_info is None or row.get("embedding") is None:
            continue
        vector = features.build_feature_vector(
            row,
            baseline=label_info["channel_baseline"],
            channel_published_dates=channel_published_dates[row["channel_id"]],
            now=now,
            top_categories=top_categories,
        )
        feature_rows.append(vector)
        video_ids.append(video_id)
        y.append(label_info["label"])
        groups.append(row["channel_id"])

    if not feature_rows:
        return None

    return {
        "X": np.array(feature_rows, dtype=np.float32),
        "y": np.array(y, dtype=np.int64),
        "video_ids": video_ids,
        "groups": groups,
        "feature_names": features.feature_names(top_categories),
        "top_categories": top_categories,
    }


def scale_train_test(
    X_train: np.ndarray, X_test: np.ndarray, embedding_dim: int = EMBEDDING_DIM
):
    """Fit a StandardScaler on the train fold's tabular slice only (no
    leakage), and apply it to both train and test. The embedding slice
    is left raw in both — per the plan, the baselines must see the
    *raw* 384-dim embedding, not a rescaled one, so the embedding's own
    signal isn't dampened or distorted; only the tabular features (very
    different native scales: seconds, counts, log-subscribers, 0/1
    flags) need standardizing for LogisticRegression to behave.
    """
    from sklearn.preprocessing import StandardScaler

    emb_train, tab_train = X_train[:, :embedding_dim], X_train[:, embedding_dim:]
    emb_test, tab_test = X_test[:, :embedding_dim], X_test[:, embedding_dim:]
    scaler = StandardScaler().fit(tab_train)
    X_train_scaled = np.hstack([emb_train, scaler.transform(tab_train)])
    X_test_scaled = np.hstack([emb_test, scaler.transform(tab_test)])
    return X_train_scaled, X_test_scaled, scaler
