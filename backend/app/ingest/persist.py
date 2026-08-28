"""Turn raw YouTube API items into database rows and upsert them.

The transform functions (api item to row dict) are pure and covered by
unit tests. The upsert helpers use the Postgres dialect insert so a
rerun updates existing rows instead of failing on duplicate keys.
Snapshot inserts skip duplicates instead, because the schema allows at
most one snapshot per video (or channel) per calendar day.

None of the helpers commit. The caller owns the transaction.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Callable

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, ChannelSnapshot, Video, VideoSnapshot

# Videos shorter than this many seconds are treated as Shorts. The API
# has no direct Shorts flag, so duration is the usual proxy.
SHORTS_MAX_SECONDS = 62

# Matches ISO 8601 durations as YouTube emits them, for example
# "PT8M30S", "PT1H2M3S", "P1DT2H", "P0D". Weeks are accepted too.
_DURATION_RE = re.compile(
    r"^P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$"
)


def parse_duration_seconds(value: str | None) -> int | None:
    """Parse an ISO 8601 duration into whole seconds.

    Returns None for missing or unparseable input. Hand-written on
    purpose: the format YouTube uses is tiny and a dependency for it
    is not worth carrying.
    """
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    weeks, days, hours, minutes, seconds = (
        int(group) if group else 0 for group in match.groups()
    )
    return weeks * 604800 + days * 86400 + hours * 3600 + minutes * 60 + seconds


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an API timestamp like 2026-08-01T12:00:00Z."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_int(value) -> int | None:
    """API counts arrive as strings; missing stays None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def today_utc() -> date:
    """Snapshot date: the current calendar date in UTC."""
    return datetime.now(timezone.utc).date()


def channel_row(item: dict) -> dict:
    """Map one channels.list item onto a channels table row."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    subs_hidden = bool(stats.get("hiddenSubscriberCount", False))
    return {
        "id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "custom_url": snippet.get("customUrl"),
        "country": snippet.get("country"),
        "uploads_playlist_id": content.get("relatedPlaylists", {}).get("uploads"),
        "published_at": parse_timestamp(snippet.get("publishedAt")),
        # A hidden subscriber count is stored as None plus the flag,
        # never as zero, so it cannot poison averages later.
        "subscriber_count": None if subs_hidden else _to_int(stats.get("subscriberCount")),
        "subs_hidden": subs_hidden,
        "video_count": _to_int(stats.get("videoCount")),
        "view_count": _to_int(stats.get("viewCount")),
    }


def video_row(item: dict, detected_language: str | None) -> dict:
    """Map one videos.list item onto a videos table row."""
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})
    duration = parse_duration_seconds(content.get("duration"))
    return {
        "id": item["id"],
        "channel_id": snippet.get("channelId"),
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        # Most videos carry no tags at all; keep None rather than [].
        "tags": snippet.get("tags"),
        "category_id": snippet.get("categoryId"),
        "published_at": parse_timestamp(snippet.get("publishedAt")),
        "duration_seconds": duration,
        "detected_language": detected_language,
        "is_short": duration is not None and 0 < duration < SHORTS_MAX_SECONDS,
        # The API includes liveStreamingDetails only for live streams
        # and their recordings.
        "is_live_vod": "liveStreamingDetails" in item,
        "view_count": _to_int(stats.get("viewCount")),
        "like_count": _to_int(stats.get("likeCount")),
        "comment_count": _to_int(stats.get("commentCount")),
    }


def video_snapshot_row(item: dict, snapshot_date: date) -> dict:
    """Map one videos.list item onto a video_snapshots row."""
    stats = item.get("statistics", {})
    return {
        "video_id": item["id"],
        "snapshot_date": snapshot_date,
        "view_count": _to_int(stats.get("viewCount")),
        "like_count": _to_int(stats.get("likeCount")),
        "comment_count": _to_int(stats.get("commentCount")),
    }


def channel_snapshot_row(item: dict, snapshot_date: date) -> dict:
    """Map one channels.list item onto a channel_snapshots row."""
    stats = item.get("statistics", {})
    subs_hidden = bool(stats.get("hiddenSubscriberCount", False))
    return {
        "channel_id": item["id"],
        "snapshot_date": snapshot_date,
        "subscriber_count": None if subs_hidden else _to_int(stats.get("subscriberCount")),
        "video_count": _to_int(stats.get("videoCount")),
        "view_count": _to_int(stats.get("viewCount")),
    }


async def upsert_channels(session: AsyncSession, api_items: list[dict]) -> int:
    """Insert or update channels from channels.list items."""
    rows = [channel_row(item) for item in api_items]
    if not rows:
        return 0
    stmt = pg_insert(Channel).values(rows)
    # Everything from the API refreshes on conflict. Local state such
    # as is_tracked and niche_id is left alone.
    update_cols = [key for key in rows[0] if key != "id"]
    stmt = stmt.on_conflict_do_update(
        index_elements=[Channel.id],
        set_={col: stmt.excluded[col] for col in update_cols},
    )
    await session.execute(stmt)
    return len(rows)


async def upsert_videos(
    session: AsyncSession,
    api_items: list[dict],
    detected_language_fn: Callable[[str, str], str],
) -> int:
    """Insert or update videos, detecting the language of each one."""
    rows = []
    for item in api_items:
        snippet = item.get("snippet", {})
        language = detected_language_fn(
            snippet.get("title", ""), snippet.get("description", "")
        )
        rows.append(video_row(item, language))
    if not rows:
        return 0
    stmt = pg_insert(Video).values(rows)
    update_cols = [key for key in rows[0] if key != "id"]
    stmt = stmt.on_conflict_do_update(
        index_elements=[Video.id],
        set_={col: stmt.excluded[col] for col in update_cols},
    )
    await session.execute(stmt)
    return len(rows)


async def insert_video_snapshots(
    session: AsyncSession, api_items: list[dict]
) -> int:
    """Write one snapshot per video for today (UTC). Duplicates are skipped."""
    snapshot_date = today_utc()
    rows = [video_snapshot_row(item, snapshot_date) for item in api_items]
    if not rows:
        return 0
    stmt = pg_insert(VideoSnapshot).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_video_snapshot_per_day")
    result = await session.execute(stmt)
    return result.rowcount or 0


async def insert_channel_snapshots(
    session: AsyncSession, api_items: list[dict]
) -> int:
    """Write one snapshot per channel for today (UTC). Duplicates are skipped."""
    snapshot_date = today_utc()
    rows = [channel_snapshot_row(item, snapshot_date) for item in api_items]
    if not rows:
        return 0
    stmt = pg_insert(ChannelSnapshot).values(rows)
    stmt = stmt.on_conflict_do_nothing(constraint="uq_channel_snapshot_per_day")
    result = await session.execute(stmt)
    return result.rowcount or 0
