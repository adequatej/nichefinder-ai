"""Resumable bootstrap: build the initial corpus from seed keywords.

Flow: one untyped search per seed keyword to collect channel ids, add
the hand-curated seed channels, fetch channel details, then walk each
channel's uploads playlist (up to 100 videos or 24 months back,
whichever comes first), batch-fetch video stats, detect language, and
upsert everything.

Resumability comes from the Layer 1 response cache: a rerun replays
cached API responses at 0 quota units, so after a quota-exhausted stop
the next day's run fast-forwards through everything already fetched.

After ingest the two hard gates are reported:
  Gate A: at least GATE_A_THRESHOLD videos with detected_language "en".
  Gate B: at least GATE_B_THRESHOLD English videos whose title matches
          a demo-topic term.
Finally up to 100 channels are marked is_tracked for the daily refresh:
channels owning Gate B videos first, then the most-viewed English
channels.

Run inside the api container with: python -m app.ingest.bootstrap
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Protocol

import httpx
from sqlalchemy import select, update

from app.config import get_settings
from app.ingest import persist
from app.ingest.langfilter import detect_language
from app.ingest.seeds import DEMO_TOPIC_TERMS, SEED_CHANNEL_IDS, SEED_KEYWORDS
from app.services.youtube import QuotaExceededError, YouTubeClient

GATE_A_THRESHOLD = 10000
GATE_B_THRESHOLD = 30
MAX_VIDEOS_PER_CHANNEL = 100
MONTHS_BACK = 24
TRACKED_CHANNEL_LIMIT = 100

# 24 months, using the 365.25-day average year.
_LOOKBACK = timedelta(days=int(MONTHS_BACK * 30.44))


class IngestSink(Protocol):
    """Where the bootstrap writes its results.

    The real implementation (DbSink) writes to Postgres. Tests use an
    in-memory sink so the orchestration is testable without a database.
    """

    async def save_channels(self, api_items: list[dict]) -> None: ...
    async def save_videos(self, api_items: list[dict]) -> None: ...
    async def video_rows(self) -> list[dict]: ...
    async def mark_tracked(self, channel_ids: list[str]) -> None: ...


class DbSink:
    """Postgres-backed sink used by the real bootstrap and sample mode."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def save_channels(self, api_items: list[dict]) -> None:
        async with self._session_factory() as session:
            await persist.upsert_channels(session, api_items)
            await persist.insert_channel_snapshots(session, api_items)
            await session.commit()

    async def save_videos(self, api_items: list[dict]) -> None:
        async with self._session_factory() as session:
            await persist.upsert_videos(session, api_items, detect_language)
            await persist.insert_video_snapshots(session, api_items)
            await session.commit()

    async def video_rows(self) -> list[dict]:
        from app.db.models import Video

        async with self._session_factory() as session:
            result = await session.execute(
                select(
                    Video.id,
                    Video.channel_id,
                    Video.title,
                    Video.detected_language,
                    Video.view_count,
                )
            )
            return [
                {
                    "id": row.id,
                    "channel_id": row.channel_id,
                    "title": row.title,
                    "detected_language": row.detected_language,
                    "view_count": row.view_count,
                }
                for row in result
            ]

    async def mark_tracked(self, channel_ids: list[str]) -> None:
        from app.db.models import Channel

        async with self._session_factory() as session:
            # Reset first so a rerun cannot leave stale tracked flags.
            await session.execute(update(Channel).values(is_tracked=False))
            if channel_ids:
                await session.execute(
                    update(Channel)
                    .where(Channel.id.in_(channel_ids))
                    .values(is_tracked=True)
                )
            await session.commit()


def collect_channel_ids(search_response: dict) -> list[str]:
    """Pull channel ids out of an untyped search response, in order."""
    ids: list[str] = []
    for item in search_response.get("items", []):
        item_id = item.get("id", {})
        channel_id = item_id.get("channelId") or item.get("snippet", {}).get(
            "channelId"
        )
        if channel_id:
            ids.append(channel_id)
    return ids


def dedupe_keep_order(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in ids:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def is_demo_topic_title(title: str) -> bool:
    """True when the lowercase title contains any demo-topic term."""
    lowered = (title or "").lower()
    return any(term in lowered for term in DEMO_TOPIC_TERMS)


def gate_a_count(video_rows: list[dict]) -> int:
    """Number of videos detected as English."""
    return sum(1 for row in video_rows if row.get("detected_language") == "en")


def gate_b_count(video_rows: list[dict]) -> int:
    """Number of English videos whose title matches a demo-topic term."""
    return sum(
        1
        for row in video_rows
        if row.get("detected_language") == "en"
        and is_demo_topic_title(row.get("title", ""))
    )


def select_tracked_channels(
    video_rows: list[dict], limit: int = TRACKED_CHANNEL_LIMIT
) -> list[str]:
    """Pick up to `limit` channel ids for daily tracking.

    Channels owning Gate B (demo topic) videos come first, ordered by
    how many they own. The rest of the slots go to the channels with
    the most total views across their English videos.
    """
    demo_counts: dict[str, int] = {}
    english_views: dict[str, int] = {}
    for row in video_rows:
        channel_id = row.get("channel_id")
        if not channel_id or row.get("detected_language") != "en":
            continue
        english_views[channel_id] = english_views.get(channel_id, 0) + (
            row.get("view_count") or 0
        )
        if is_demo_topic_title(row.get("title", "")):
            demo_counts[channel_id] = demo_counts.get(channel_id, 0) + 1

    demo_first = sorted(
        demo_counts,
        key=lambda cid: (-demo_counts[cid], -english_views.get(cid, 0), cid),
    )
    others = sorted(
        (cid for cid in english_views if cid not in demo_counts),
        key=lambda cid: (-english_views[cid], cid),
    )
    return (demo_first + others)[:limit]


def report_gates(
    video_rows: list[dict],
    gate_a_threshold: int = GATE_A_THRESHOLD,
    gate_b_threshold: int = GATE_B_THRESHOLD,
) -> tuple[int, int]:
    """Print both gate counts clearly and return them."""
    count_a = gate_a_count(video_rows)
    count_b = gate_b_count(video_rows)
    status_a = "PASS" if count_a >= gate_a_threshold else "NOT YET"
    status_b = "PASS" if count_b >= gate_b_threshold else "NOT YET"
    print(
        f"Gate A (English videos): {count_a} of {gate_a_threshold} needed "
        f"[{status_a}]"
    )
    print(
        f"Gate B (English demo-topic videos): {count_b} of "
        f"{gate_b_threshold} needed [{status_b}]"
    )
    return count_a, count_b


async def _collect_upload_video_ids(
    client: YouTubeClient,
    playlist_id: str,
    max_videos: int,
    cutoff: datetime,
) -> list[str]:
    """Walk an uploads playlist newest-first until either limit hits."""
    video_ids: list[str] = []
    page_token: str | None = None
    while True:
        page = await client.list_playlist_items(playlist_id, page_token=page_token)
        for item in page.get("items", []):
            details = item.get("contentDetails", {})
            video_id = details.get("videoId")
            if not video_id:
                continue
            published = persist.parse_timestamp(details.get("videoPublishedAt"))
            if published is not None and published < cutoff:
                return video_ids
            video_ids.append(video_id)
            if len(video_ids) >= max_videos:
                return video_ids
        page_token = page.get("nextPageToken")
        if not page_token:
            return video_ids


async def run_bootstrap(
    client: YouTubeClient,
    sink: IngestSink,
    keywords: tuple[str, ...] = SEED_KEYWORDS,
    seed_channel_ids: list[str] = SEED_CHANNEL_IDS,
    max_videos_per_channel: int = MAX_VIDEOS_PER_CHANNEL,
    gate_a_threshold: int = GATE_A_THRESHOLD,
    gate_b_threshold: int = GATE_B_THRESHOLD,
    tracked_limit: int = TRACKED_CHANNEL_LIMIT,
) -> dict:
    """Run the bootstrap. Returns a summary dict.

    On QuotaExceededError the run stops cleanly, keeps everything
    ingested so far, and still reports the gates. Rerunning later
    replays cached calls for free and continues where it stopped.
    """
    cutoff = datetime.now(timezone.utc) - _LOOKBACK
    stopped_on_quota = False
    channels_ingested = 0
    try:
        channel_ids: list[str] = []
        for keyword in keywords:
            # type=None makes this an untyped search so channel results
            # count too, not only videos.
            response = await client.search(keyword, type=None)
            channel_ids.extend(collect_channel_ids(response))
        channel_ids.extend(seed_channel_ids)
        channel_ids = dedupe_keep_order(channel_ids)

        channel_items = await client.list_channels(channel_ids)
        await sink.save_channels(channel_items)
        channels_ingested = len(channel_items)

        for channel_item in channel_items:
            uploads = (
                channel_item.get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
            if not uploads:
                continue
            video_ids = await _collect_upload_video_ids(
                client, uploads, max_videos_per_channel, cutoff
            )
            if not video_ids:
                continue
            video_items = await client.list_videos(video_ids)
            await sink.save_videos(video_items)
    except QuotaExceededError as exc:
        stopped_on_quota = True
        print(f"Stopping cleanly: {exc}")
        print(
            "Partial progress is saved. Rerun tomorrow; cached calls "
            "cost 0 units, so the run resumes where it stopped."
        )

    video_rows = await sink.video_rows()
    count_a, count_b = report_gates(video_rows, gate_a_threshold, gate_b_threshold)
    tracked = select_tracked_channels(video_rows, tracked_limit)
    await sink.mark_tracked(tracked)
    print(f"Marked {len(tracked)} channels as tracked for the daily refresh.")

    return {
        "channels_ingested": channels_ingested,
        "videos_ingested": len(video_rows),
        "gate_a_count": count_a,
        "gate_b_count": count_b,
        "gate_a_passed": count_a >= gate_a_threshold,
        "gate_b_passed": count_b >= gate_b_threshold,
        "tracked_channels": len(tracked),
        "stopped_on_quota": stopped_on_quota,
    }


async def main() -> int:
    from redis.asyncio import Redis

    from app.db.session import SessionLocal
    from app.services.cache import ResponseCache
    from app.services.quota import DbQuotaRecorder

    settings = get_settings()
    if not settings.youtube_api_key:
        print(
            "YOUTUBE_API_KEY is empty. Set it in .env to run the real "
            "bootstrap, or use `make bootstrap-sample` for keyless "
            "sample data."
        )
        return 1

    redis = Redis.from_url(settings.redis_url)
    cache = ResponseCache(redis, cache_enabled=settings.cache_enabled)
    recorder = DbQuotaRecorder(SessionLocal)
    run_label = f"bootstrap-{persist.today_utc().isoformat()}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            client = YouTubeClient(
                api_key=settings.youtube_api_key,
                http=http,
                cache=cache,
                quota=recorder,
                run_label=run_label,
                strategy_label="optimized",
            )
            summary = await run_bootstrap(client, DbSink(SessionLocal))
    finally:
        await redis.aclose()
    print(f"Bootstrap summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
