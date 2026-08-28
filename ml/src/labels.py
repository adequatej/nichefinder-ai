"""Breakout labels: age-curve-corrected, channel-relative view velocity.

A "breakout" video is one growing much faster than is typical for its
own channel, once the fact that younger videos naturally show more
views-per-day (most of a video's lifetime views land in its first
weeks) is corrected for. Two corrections are layered:

  1. Age-curve correction: divide a video's raw views/day by the
     corpus-wide expected views/day for a video of that age, V(t).
     This turns "raw views/day" (which is inflated for young videos
     purely as an artifact of age) into "normalized velocity" (roughly
     1.0 for a video accumulating views at the typical rate for its
     age, regardless of how old it is).
  2. Channel-baseline correction: compare that normalized velocity
     against the same channel's own recent normalized velocity, so a
     channel that always runs hot (or cold) is judged against itself,
     not the whole corpus.

v1 simplifications, documented here rather than hidden, matching the
tone of app/services/scoring.py in the backend:

  - V(t) approximation. There is no true "lifetime final view count"
    to fit a growth curve against yet — most of the corpus has only
    ever had its view_count read once (see Video vs VideoSnapshot in
    the schema; daily snapshots exist going forward but don't cover
    ~2 years of backfill). So V(t) is approximated empirically:
    videos are bucketed into `CURVE_BUCKET_DAYS`-wide age buckets, and
    the median views_per_day (view_count / age_in_days, floored at 1
    day) within each bucket stands in for "the expected accumulation
    rate at that age." This is a median-of-currently-observed-videos
    curve, not a fitted parametric growth model (no logistic/power-law
    fit) and not a true "fraction of eventual views" curve. It is
    honest as "what's typical right now for a video this old," which
    is exactly what channel-relative comparison needs — it does not
    need to be a fitted lifetime-views model.
  - Proxy for velocity itself. views_per_day uses each video's single
    most recent view_count read divided by its age. Once ~90 days of
    daily VideoSnapshot rows accumulate from the running scheduler,
    this should be replaced with a true day-7 (or day-N) delta,
    which is far less sensitive to a single stale read.
  - Channel baseline gate. A channel needs at least
    MIN_BASELINE_VIDEOS (5) other videos aged
    BASELINE_MIN_AGE_DAYS-BASELINE_MAX_AGE_DAYS (30-180) days at `now`
    before any of its videos in the labeling window get a label at
    all. This is a real, expected limitation on small corpora — most
    of the 12-channel sample fixture in app/ingest/sample_data.py will
    end up unlabeled, not because of a bug but because there simply
    isn't enough same-channel history yet to judge against. Channels
    below the gate contribute no rows to the training set.
  - BREAKOUT_MULTIPLIER = 3.0 is the plan's stated default. It is not
    tuned against this repo's sample corpus to land positives at a
    particular rate — that corpus's view counts are i.i.d. random per
    video (see the module docstring on app/ingest/sample_data.py), so
    any resulting positive rate on it is meaningless and tuning
    against it would just be curve-fitting to noise. Calibrating this
    constant against a real ~10-20% positive rate is deferred until
    real bootstrap data exists.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

# Only videos aged 7-180 days at `now` are eligible for a label: too
# young and the view count hasn't settled into any stable trend; too
# old and it's no longer "breaking out," it just is what it is.
MIN_LABEL_AGE_DAYS = 7
MAX_LABEL_AGE_DAYS = 180

# The channel-baseline pool: a channel's OTHER videos aged 30-180 days
# at `now` (not before the target video — before `now`, per the plan).
BASELINE_MIN_AGE_DAYS = 30
BASELINE_MAX_AGE_DAYS = 180
MIN_BASELINE_VIDEOS = 5

# A video is a breakout when its normalized velocity is at least this
# multiple of its channel's baseline normalized velocity.
BREAKOUT_MULTIPLIER = 3.0

# Width of each V(t) age bucket, in days.
CURVE_BUCKET_DAYS = 7


def age_days(published_at: datetime, now: datetime) -> int:
    """Whole days between `published_at` and `now`. May be negative for a
    clock-skewed or bad `published_at`; callers should treat negative as
    ineligible rather than clamp it, since clamping would hide bad data."""
    return (now - published_at).days


def views_per_day(view_count: int, age_days_value: float) -> float:
    """view_count / age, floored at 1 day (matches scoring.view_velocity's
    same-day-spike guard: a same-day publish can't divide by zero)."""
    return view_count / max(age_days_value, 1)


def fit_view_curve(
    observations: list[tuple[float, float]],
    bucket_days: int = CURVE_BUCKET_DAYS,
) -> dict[int, float]:
    """Empirical V(t): median views_per_day within each age bucket.

    `observations` is a list of (age_days, views_per_day) pairs drawn
    from the whole available corpus (not just the labeling window) so
    the curve has support at every age, including the 30-180 day
    baseline range. Buckets with no observations are simply absent —
    see expected_views_per_day for how a missing bucket is handled.
    """
    buckets: dict[int, list[float]] = defaultdict(list)
    for age, vpd in observations:
        buckets[int(age // bucket_days)].append(vpd)
    return {bucket: statistics.median(values) for bucket, values in buckets.items()}


def expected_views_per_day(
    age_days_value: float,
    curve: dict[int, float],
    bucket_days: int = CURVE_BUCKET_DAYS,
) -> float:
    """V(age): the curve's value at `age_days_value`'s bucket.

    Falls back to the nearest bucket with data when the exact bucket is
    empty (sparse ages happen on small corpora); returns 0.0 only when
    the whole curve is empty, which normalized_velocity treats as "no
    signal" rather than dividing by zero.
    """
    if not curve:
        return 0.0
    bucket = int(age_days_value // bucket_days)
    if bucket in curve:
        return curve[bucket]
    nearest = min(curve.keys(), key=lambda candidate: abs(candidate - bucket))
    return curve[nearest]


def normalized_velocity(
    views_per_day_value: float,
    age_days_value: float,
    curve: dict[int, float],
    bucket_days: int = CURVE_BUCKET_DAYS,
) -> float | None:
    """views_per_day / V(age). None when V(age) is 0 (no usable signal),
    rather than a division-by-zero or a fabricated infinite ratio."""
    expected = expected_views_per_day(age_days_value, curve, bucket_days)
    if expected <= 0:
        return None
    return views_per_day_value / expected


def channel_baseline(
    pool: list[tuple[str, float]],
    exclude_video_id: str | None = None,
    min_count: int = MIN_BASELINE_VIDEOS,
) -> float | None:
    """Median normalized velocity of a channel's baseline-window videos.

    `pool` is that channel's (video_id, normalized_velocity) pairs for
    videos aged 30-180 days at `now`; `exclude_video_id` drops the
    target video itself when it also falls in that window, so a
    video is never part of its own baseline ("OTHER videos", per the
    plan). Returns None below `min_count`, per the channel gate
    documented in this module's docstring.
    """
    values = [normalized for video_id, normalized in pool if video_id != exclude_video_id]
    if len(values) < min_count:
        return None
    return statistics.median(values)


def compute_labels(
    rows: list[dict],
    now: datetime,
    bucket_days: int = CURVE_BUCKET_DAYS,
    multiplier: float = BREAKOUT_MULTIPLIER,
    min_baseline_videos: int = MIN_BASELINE_VIDEOS,
) -> dict[str, dict]:
    """Breakout labels for every eligible video in `rows`.

    Each row needs: video_id, channel_id, view_count, published_at,
    is_live_vod. Live-stream recordings are excluded entirely, from
    curve-fitting, from baseline pools, and from receiving a label —
    matching the "excluded from velocity math" comment on
    Video.is_live_vod in the backend schema.

    Returns {video_id: {label, views_per_day, normalized_velocity,
    channel_baseline, age_days}} for every video that: is non-live, has
    a view_count and published_at, is aged 7-180 days at `now`, has a
    usable V(t) value at its age, and belongs to a channel with at
    least `min_baseline_videos` other videos aged 30-180 days. Videos
    failing any of those conditions are simply absent from the result
    — this is the expected, documented behavior on small corpora, not
    an error.
    """
    eligible: list[tuple[str, str, int, float]] = []
    for row in rows:
        if row.get("is_live_vod"):
            continue
        published_at = row.get("published_at")
        view_count = row.get("view_count")
        if published_at is None or view_count is None:
            continue
        age = age_days(published_at, now)
        if age < 0:
            continue
        eligible.append((row["video_id"], row["channel_id"], age, views_per_day(view_count, age)))

    curve = fit_view_curve([(age, vpd) for _, _, age, vpd in eligible], bucket_days)

    normalized_by_video: dict[str, float] = {}
    channel_pool: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for video_id, channel_id, age, vpd in eligible:
        norm = normalized_velocity(vpd, age, curve, bucket_days)
        if norm is None:
            continue
        normalized_by_video[video_id] = norm
        if BASELINE_MIN_AGE_DAYS <= age <= BASELINE_MAX_AGE_DAYS:
            channel_pool[channel_id].append((video_id, norm))

    results: dict[str, dict] = {}
    for video_id, channel_id, age, vpd in eligible:
        if not (MIN_LABEL_AGE_DAYS <= age <= MAX_LABEL_AGE_DAYS):
            continue
        norm = normalized_by_video.get(video_id)
        if norm is None:
            continue
        baseline = channel_baseline(
            channel_pool.get(channel_id, []),
            exclude_video_id=video_id,
            min_count=min_baseline_videos,
        )
        if baseline is None:
            continue
        results[video_id] = {
            "label": 1 if norm >= multiplier * baseline else 0,
            "views_per_day": vpd,
            "normalized_velocity": norm,
            "channel_baseline": baseline,
            "age_days": age,
        }
    return results
