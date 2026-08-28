"""Daily refresh for tracked channels.

For every channel marked is_tracked: refresh channel stats and write a
channel snapshot, read the first uploads-playlist page to spot new
videos, then batch-fetch stats for the new videos plus every tracked
video published in the last 30 days, writing video snapshots. This is
the optimized quota strategy: playlist diffing plus 50-id batching
instead of daily searches.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ingest import persist
from app.ingest.langfilter import detect_language
from app.services.youtube import YouTubeClient

RECENT_DAYS = 30


def embed_new_videos(video_ids: list[str]) -> None:
    """No-op hook. P3 fills this in with embedding generation."""


def refresh_niche_scores() -> None:
    """No-op hook. P3 fills this in with niche score recomputation."""


def run_predictions() -> None:
    """No-op hook. P4 fills this in with breakout model scoring."""


async def run_daily_refresh(session_factory, client: YouTubeClient) -> dict:
    """Refresh tracked channels and videos. Returns a stats dict."""
    from app.db.models import Channel, Video

    stats = {
        "channels_refreshed": 0,
        "new_videos": 0,
        "snapshots_written": 0,
        "units_spent": None,
    }

    async with session_factory() as session:
        result = await session.execute(
            select(Channel.id).where(Channel.is_tracked.is_(True))
        )
        tracked_ids = [row.id for row in result]

    if not tracked_ids:
        print("No tracked channels yet. Run the bootstrap first.")
        return stats

    # Refresh channel stats and snapshot them (1 unit per 50 channels).
    channel_items = await client.list_channels(tracked_ids)
    async with session_factory() as session:
        await persist.upsert_channels(session, channel_items)
        stats["snapshots_written"] += await persist.insert_channel_snapshots(
            session, channel_items
        )
        await session.commit()
    stats["channels_refreshed"] = len(channel_items)

    # First uploads-playlist page per channel to diff for new videos.
    candidate_ids: list[str] = []
    for item in channel_items:
        uploads = (
            item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        )
        if not uploads:
            continue
        page = await client.list_playlist_items(uploads)
        for playlist_item in page.get("items", []):
            video_id = playlist_item.get("contentDetails", {}).get("videoId")
            if video_id:
                candidate_ids.append(video_id)

    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
    async with session_factory() as session:
        known = await session.execute(
            select(Video.id).where(Video.id.in_(candidate_ids))
        )
        known_ids = {row.id for row in known}
        recent = await session.execute(
            select(Video.id).where(
                Video.channel_id.in_(tracked_ids),
                Video.published_at >= recent_cutoff,
            )
        )
        recent_ids = [row.id for row in recent]

    new_ids = [vid for vid in candidate_ids if vid not in known_ids]
    fetch_ids = list(dict.fromkeys(new_ids + recent_ids))

    if fetch_ids:
        video_items = await client.list_videos(fetch_ids)
        async with session_factory() as session:
            await persist.upsert_videos(session, video_items, detect_language)
            stats["snapshots_written"] += await persist.insert_video_snapshots(
                session, video_items
            )
            await session.commit()
    stats["new_videos"] = len(new_ids)

    # Later phases hang off these hooks.
    embed_new_videos(new_ids)
    refresh_niche_scores()
    run_predictions()

    # The in-memory test recorder exposes total_units; the database
    # recorder does not, so units_spent stays None there.
    recorder = getattr(client, "_quota", None)
    stats["units_spent"] = getattr(recorder, "total_units", None)
    return stats
