"""Feature matrix for the breakout model: the 384-dim embedding plus a
fixed set of tabular features, in a fixed column order (see
feature_names). No feature here is a disguised form of the outcome:
current view_count, like_count, and comment_count never appear — only
their derived, age-normalized/baseline forms computed in labels.py
(log_baseline_velocity) are used as inputs.

The pure, single-value functions below (title parsing, the hour
sin/cos transform, one-hot encoders, the log1p + missing-indicator
subscriber handling) take plain values and are unit-tested with plain
values — no pandas, no DB. build_feature_vector and feature_names are
the pandas/dict-shaped glue that assembles them into one row/column
list in a fixed order.

Design notes on choices the task left open:
  - uploads_per_week reimplements backend/app/services/scoring.py's
    uploads_per_week (recent-90-day window / (90/7)) rather than
    importing it: ml/ is a separate package with its own venv, so
    importing the "app" package would mean depending on the backend's
    full dependency set (FastAPI, asyncpg, etc.) just for one pure
    function. The formula must stay identical to scoring.py's — see
    the test that checks both against the same hand-computed value.
  - Top-8 category one-hot: the 8 most frequent category_id values
    *in the exported dataset* (not a fixed global YouTube category
    list) get their own column; everything else, including a missing
    category_id, falls into a single "other" column. This keeps the
    encoding meaningful for whatever categories the corpus actually
    contains, at the cost of the encoding being corpus-dependent (a
    different export could pick a different top-8) — acceptable for a
    per-training-run feature set that is rebuilt from scratch anyway.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Iterable

EMBEDDING_DIM = 384

TOP_CATEGORY_COUNT = 8

# Recent-window definition for uploads_per_week, matching
# RECENT_WINDOW_DAYS in backend/app/services/scoring.py.
UPLOADS_WINDOW_DAYS = 90

WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_DIGIT_RE = re.compile(r"\d")
_QUESTION_OR_EXCLAIM_RE = re.compile(r"[?!]")


def log1p_subscribers(subscriber_count: int | None, subs_hidden: bool) -> float:
    """log1p(subscriber_count), or 0.0 when hidden/missing.

    A hidden or missing subscriber count is treated as 0 (post-log1p)
    rather than left as a sentinel that could poison the feature,
    matching the honesty pattern already used for subs_hidden in
    backend/app/ingest/persist.py's channel_row (stored as None, never
    0, "so it cannot poison averages") — here the model needs a real
    number, so it gets 0.0 plus the separate missing-indicator feature
    below, rather than a fabricated subscriber count.
    """
    if subs_hidden or subscriber_count is None:
        return 0.0
    return math.log1p(max(subscriber_count, 0))


def subs_missing_indicator(subs_hidden: bool) -> int:
    return 1 if subs_hidden else 0


def log1p_baseline_velocity(baseline: float | None) -> float:
    """log1p(channel baseline normalized velocity), or 0.0 when absent.

    A video without a channel baseline never reaches this function in
    practice (labels.py excludes it from the labeled set entirely), so
    the None branch only matters for direct unit testing.
    """
    if baseline is None:
        return 0.0
    return math.log1p(max(baseline, 0.0))


def uploads_per_week(
    published_dates: list[datetime],
    now: datetime,
    window_days: int = UPLOADS_WINDOW_DAYS,
) -> float:
    """Recent-window upload cadence for one channel.

    Identical formula to scoring.uploads_per_week in the backend:
    videos published within `window_days` of `now`, divided by the
    number of weeks in that window.
    """
    cutoff = now - timedelta(days=window_days)
    recent = sum(1 for date in published_dates if date is not None and date >= cutoff)
    weeks = window_days / 7
    return recent / weeks


def title_length(title: str | None) -> int:
    return len(title or "")


def title_has_number(title: str | None) -> int:
    return 1 if _DIGIT_RE.search(title or "") else 0


def title_has_question_or_exclaim(title: str | None) -> int:
    return 1 if _QUESTION_OR_EXCLAIM_RE.search(title or "") else 0


def tag_count(tags: list[str] | None) -> int:
    """Most videos have no tags (see the comment on Video.tags in the
    backend schema); that case is just len(None-as-empty) == 0."""
    return len(tags) if tags else 0


def publish_hour_sin_cos(published_at: datetime) -> tuple[float, float]:
    """Cyclical encoding of publish hour-of-day (UTC), so hour 23 and
    hour 0 are close together instead of maximally far apart."""
    hour = published_at.hour
    angle = 2 * math.pi * hour / 24
    return math.sin(angle), math.cos(angle)


def day_of_week_one_hot(published_at: datetime) -> list[int]:
    """7-column one-hot, Monday first (Python's datetime.weekday())."""
    one_hot = [0] * 7
    one_hot[published_at.weekday()] = 1
    return one_hot


def top_category_ids(category_ids: Iterable[str | None], top_n: int = TOP_CATEGORY_COUNT) -> list[str]:
    """The `top_n` most frequent category_id values, deterministically
    ordered (count desc, then id asc) so reruns on the same data always
    pick the same columns."""
    counts = Counter(str(c) for c in category_ids if c is not None)
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [category_id for category_id, _ in ranked[:top_n]]


def category_one_hot(category_id: str | None, top_categories: list[str]) -> list[int]:
    """One-hot over `top_categories` plus a trailing "other" column that
    catches everything else, including a missing category_id."""
    one_hot = [0] * (len(top_categories) + 1)
    key = str(category_id) if category_id is not None else None
    if key is not None and key in top_categories:
        one_hot[top_categories.index(key)] = 1
    else:
        one_hot[-1] = 1
    return one_hot


def feature_names(top_categories: list[str]) -> list[str]:
    """Column names in the exact order build_feature_vector emits them."""
    names = [f"embedding_{i}" for i in range(EMBEDDING_DIM)]
    names += [
        "log_subscribers",
        "subs_missing",
        "log_baseline_velocity",
        "uploads_per_week",
        "title_length",
        "title_has_number",
        "title_has_question_or_exclaim",
        "duration_seconds",
        "is_short",
        "tag_count",
        "publish_hour_sin",
        "publish_hour_cos",
    ]
    names += [f"weekday_{name}" for name in WEEKDAY_NAMES]
    names += [f"category_{category_id}" for category_id in top_categories] + ["category_other"]
    return names


def build_feature_vector(
    row: dict,
    baseline: float | None,
    channel_published_dates: list[datetime],
    now: datetime,
    top_categories: list[str],
) -> list[float]:
    """One training row's full feature vector: embedding + tabular, in
    the order feature_names() describes.

    `row` needs: embedding (384 floats), subscriber_count, subs_hidden,
    title, duration_seconds, is_short, tags, published_at, category_id.
    Values are expected to already be sanitized (None rather than NaN
    or NaT) by the caller — see dataset.py's sanitize_row.
    """
    embedding = row["embedding"]
    title = row.get("title")
    published_at = row["published_at"]
    hour_sin, hour_cos = publish_hour_sin_cos(published_at)

    tabular = [
        log1p_subscribers(row.get("subscriber_count"), bool(row.get("subs_hidden"))),
        float(subs_missing_indicator(bool(row.get("subs_hidden")))),
        log1p_baseline_velocity(baseline),
        uploads_per_week(channel_published_dates, now),
        float(title_length(title)),
        float(title_has_number(title)),
        float(title_has_question_or_exclaim(title)),
        float(row.get("duration_seconds") or 0),
        float(1 if row.get("is_short") else 0),
        float(tag_count(row.get("tags"))),
        hour_sin,
        hour_cos,
        *[float(v) for v in day_of_week_one_hot(published_at)],
        *[float(v) for v in category_one_hot(row.get("category_id"), top_categories)],
    ]
    return [float(v) for v in embedding] + tabular
