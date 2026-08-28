"""Opportunity scoring for niches.

A niche is scored only once it clears an eligibility floor
(MIN_ELIGIBLE_CHANNELS channels and MIN_ELIGIBLE_VIDEOS videos); below
that the sample is too thin to say anything, so its demand/supply/
opportunity fields are left NULL rather than published with false
confidence. Its video_count and channel_count are still stored (set by
clustering.py) so the UI can explain why it isn't ranked.

v1 simplifications, documented here rather than hidden in the formula:
  - median_view_velocity is view_count / days_since_published per
    video, then the niche's median. Real time-series data (multiple
    snapshots per video) doesn't exist yet for most of the corpus, so
    this is a lifetime-average proxy for "how fast is this growing,"
    not a true recent-velocity signal.
  - active_channel_count is just channel_count: the number of distinct
    channels with at least one video in this niche. That is not the
    same thing as "channels whose niche_id is this niche" (that is the
    per-channel mode computed in clustering.py) — a channel can have
    videos scattered across several niches while being counted here in
    each one, and being the mode of only one of them. A later phase
    could narrow this to channels that posted recently.
  - Live-stream recordings (is_live_vod) are excluded from the
    velocity calculation, per the comment on Video.is_live_vod in
    models.py ("excluded from velocity math"); they are not excluded
    from view/engagement medians, since a recording's view count is
    still a real demand signal.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MIN_ELIGIBLE_CHANNELS = 3
MIN_ELIGIBLE_VIDEOS = 25

# Shrinkage reaches full weight (1.0) at this many videos. It must sit
# above MIN_ELIGIBLE_VIDEOS (25) or every eligible niche would already
# get full weight and shrinkage would never do anything: niches between
# the eligibility floor and this threshold get partial shrinkage toward
# the global median, tapering to none as they grow past it.
SHRINKAGE_VIDEO_THRESHOLD = 50

# uploads_per_week counts videos published within this many days of
# `now`, divided by the number of weeks in that window. A fixed recent
# window is simpler than "total videos / channel age" and better
# reflects current upload cadence rather than a channel's whole
# lifetime average.
RECENT_WINDOW_DAYS = 90


def view_velocity(
    view_count: int | None, published_at: datetime | None, now: datetime
) -> float | None:
    """views per day since publish, floored at 1 day to avoid a same-day spike."""
    if view_count is None or published_at is None:
        return None
    days = max((now - published_at).days, 1)
    return view_count / days


def engagement_ratio(
    view_count: int | None, like_count: int | None, comment_count: int | None
) -> float | None:
    """(likes + comments) / views. None (not zero) when views is 0 or missing."""
    if not view_count:
        return None
    return ((like_count or 0) + (comment_count or 0)) / view_count


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def uploads_per_week(
    published_dates: list[datetime],
    now: datetime,
    window_days: int = RECENT_WINDOW_DAYS,
) -> float:
    cutoff = now - timedelta(days=window_days)
    recent = sum(1 for date in published_dates if date is not None and date >= cutoff)
    weeks = window_days / 7
    return recent / weeks


def zscore_map(values: dict[int, float]) -> dict[int, float]:
    """z-score each value against the mean/std of the whole set.

    A single-element or zero-variance set returns all zeros rather
    than dividing by zero: with nothing to compare against, "average"
    is the only honest answer.
    """
    if not values:
        return {}
    nums = list(values.values())
    mean = statistics.fmean(nums)
    std = statistics.pstdev(nums)
    if std == 0:
        return {key: 0.0 for key in values}
    return {key: (value - mean) / std for key, value in values.items()}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def is_eligible(video_count: int, channel_count: int) -> bool:
    return video_count >= MIN_ELIGIBLE_VIDEOS and channel_count >= MIN_ELIGIBLE_CHANNELS


def shrinkage_weight(
    video_count: int, threshold: float = SHRINKAGE_VIDEO_THRESHOLD
) -> float:
    """Linear ramp from 0 to 1 as video_count goes from 0 to `threshold`.

    A niche's own stats count in full only once it reaches `threshold`
    videos; below that they are blended with the global median in
    proportion to how far short they are; see shrink_toward_global.
    """
    if threshold <= 0:
        return 1.0
    return min(video_count / threshold, 1.0)


def shrink_toward_global(value: float, global_value: float, weight: float) -> float:
    """Blend `value` with `global_value`, `weight` toward `value` itself."""
    return weight * value + (1 - weight) * global_value


def compute_niche_raw_stats(
    niche_id: int,
    videos: list[dict],
    channel_count: int,
    now: datetime,
) -> dict:
    """Raw (pre-shrinkage, pre-z-score) stats for one niche.

    Each video dict needs view_count, like_count, comment_count,
    published_at, is_live_vod.
    """
    views = [v["view_count"] for v in videos if v.get("view_count") is not None]
    velocities = [
        velocity
        for v in videos
        if not v.get("is_live_vod")
        and (
            velocity := view_velocity(v.get("view_count"), v.get("published_at"), now)
        )
        is not None
    ]
    engagements = [
        ratio
        for v in videos
        if (
            ratio := engagement_ratio(
                v.get("view_count"), v.get("like_count"), v.get("comment_count")
            )
        )
        is not None
    ]
    published_dates = [v["published_at"] for v in videos if v.get("published_at") is not None]

    return {
        "niche_id": niche_id,
        "video_count": len(videos),
        "channel_count": channel_count,
        "active_channel_count": channel_count,
        "median_views": median(views),
        "median_velocity": median(velocities),
        "median_engagement": median(engagements),
        "uploads_per_week": uploads_per_week(published_dates, now),
    }


def score_niches(raw_stats: dict[int, dict]) -> dict[int, dict]:
    """Demand/supply/opportunity for every eligible niche in `raw_stats`.

      demand  = 0.5*z(log1p(median_views)) + 0.3*z(median_velocity) + 0.2*z(median_engagement)
      supply  = 0.6*z(log1p(active_channel_count)) + 0.4*z(uploads_per_week)
      opportunity = 100 * sigmoid(demand - supply)

    z-scores are computed across the eligible niches only; ineligible
    ones would only add noise to "what's normal here." Before
    z-scoring, log1p(median_views), median_velocity and
    median_engagement are shrunk toward their global (cross-niche)
    median in proportion to shrinkage_weight, so a single viral video
    in a niche that just barely clears the eligibility floor can't
    dominate the ranking.

    Returns {} if no niche is eligible. Ineligible niches are simply
    absent from the result; the caller is responsible for leaving
    their score fields NULL.
    """
    eligible = {
        niche_id: stats
        for niche_id, stats in raw_stats.items()
        if is_eligible(stats["video_count"], stats["channel_count"])
    }
    if not eligible:
        return {}

    log_views = {nid: math.log1p(s["median_views"]) for nid, s in eligible.items()}
    velocities = {nid: s["median_velocity"] for nid, s in eligible.items()}
    engagements = {nid: s["median_engagement"] for nid, s in eligible.items()}
    log_active_channels = {
        nid: math.log1p(s["active_channel_count"]) for nid, s in eligible.items()
    }
    upw = {nid: s["uploads_per_week"] for nid, s in eligible.items()}

    global_log_views = median(list(log_views.values()))
    global_velocity = median(list(velocities.values()))
    global_engagement = median(list(engagements.values()))

    weights: dict[int, float] = {}
    shrunk_log_views: dict[int, float] = {}
    shrunk_velocity: dict[int, float] = {}
    shrunk_engagement: dict[int, float] = {}
    for nid, stats in eligible.items():
        weight = shrinkage_weight(stats["video_count"])
        weights[nid] = weight
        shrunk_log_views[nid] = shrink_toward_global(log_views[nid], global_log_views, weight)
        shrunk_velocity[nid] = shrink_toward_global(velocities[nid], global_velocity, weight)
        shrunk_engagement[nid] = shrink_toward_global(
            engagements[nid], global_engagement, weight
        )

    z_views = zscore_map(shrunk_log_views)
    z_velocity = zscore_map(shrunk_velocity)
    z_engagement = zscore_map(shrunk_engagement)
    z_channels = zscore_map(log_active_channels)
    z_uploads = zscore_map(upw)

    results: dict[int, dict] = {}
    for nid, stats in eligible.items():
        demand = 0.5 * z_views[nid] + 0.3 * z_velocity[nid] + 0.2 * z_engagement[nid]
        supply = 0.6 * z_channels[nid] + 0.4 * z_uploads[nid]
        opportunity = 100 * sigmoid(demand - supply)
        results[nid] = {
            "demand_score": demand,
            "supply_score": supply,
            "opportunity_score": opportunity,
            "score_components": {
                "median_views": stats["median_views"],
                "median_velocity": stats["median_velocity"],
                "median_engagement": stats["median_engagement"],
                "active_channel_count": stats["active_channel_count"],
                "uploads_per_week": stats["uploads_per_week"],
                "video_count": stats["video_count"],
                "channel_count": stats["channel_count"],
                "shrinkage_weight": weights[nid],
            },
        }
    return results


async def _fetch_niche_video_rows(session_factory) -> dict[int, list[dict]]:
    from sqlalchemy import select

    from app.db.models import Video

    async with session_factory() as session:
        stmt = select(
            Video.niche_id,
            Video.view_count,
            Video.like_count,
            Video.comment_count,
            Video.published_at,
            Video.is_live_vod,
        ).where(Video.niche_id.is_not(None))
        result = await session.execute(stmt)
        by_niche: dict[int, list[dict]] = defaultdict(list)
        for row in result:
            by_niche[row.niche_id].append(
                {
                    "view_count": row.view_count,
                    "like_count": row.like_count,
                    "comment_count": row.comment_count,
                    "published_at": row.published_at,
                    "is_live_vod": row.is_live_vod,
                }
            )
        return dict(by_niche)


async def run_scoring(session_factory, now: datetime | None = None) -> dict:
    """Recompute demand/supply/opportunity for every niche in the database.

    Every niche's score_components reflect its raw inputs even when
    ineligible, so the UI can show why a niche isn't ranked; only
    eligible niches get non-NULL demand/supply/opportunity scores.
    """
    from sqlalchemy import select, update

    from app.db.models import Niche

    now = now or datetime.now(timezone.utc)
    videos_by_niche = await _fetch_niche_video_rows(session_factory)

    async with session_factory() as session:
        result = await session.execute(select(Niche.id, Niche.channel_count))
        niche_channel_counts = {row.id: row.channel_count for row in result}

    raw_stats = {
        niche_id: compute_niche_raw_stats(
            niche_id, videos_by_niche.get(niche_id, []), channel_count, now
        )
        for niche_id, channel_count in niche_channel_counts.items()
    }
    scored = score_niches(raw_stats)

    async with session_factory() as session:
        for niche_id, stats in raw_stats.items():
            values = scored.get(niche_id)
            components = (
                values["score_components"]
                if values
                else {
                    "median_views": stats["median_views"],
                    "median_velocity": stats["median_velocity"],
                    "median_engagement": stats["median_engagement"],
                    "active_channel_count": stats["active_channel_count"],
                    "uploads_per_week": stats["uploads_per_week"],
                    "video_count": stats["video_count"],
                    "channel_count": stats["channel_count"],
                }
            )
            await session.execute(
                update(Niche)
                .where(Niche.id == niche_id)
                .values(
                    demand_score=values["demand_score"] if values else None,
                    supply_score=values["supply_score"] if values else None,
                    opportunity_score=values["opportunity_score"] if values else None,
                    score_components=components,
                )
            )
        await session.commit()

    ranked = sorted(
        ((nid, v["opportunity_score"]) for nid, v in scored.items()),
        key=lambda pair: -pair[1],
    )
    return {
        "niches_total": len(raw_stats),
        "niches_eligible": len(scored),
        "top_by_opportunity": ranked[:3],
    }
