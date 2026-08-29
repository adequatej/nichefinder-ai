"""Quota-strategy benchmark: naive per-topic search vs. the optimized
daily-refresh strategy already shipped in app/ingest/snapshot.py.

This backs the claim in docs/quota-math.md with a real, reproducible
run instead of an estimate. The claim is architectural -- "the same
effective monitoring work costs X naively and Y with batching plus
playlist diffing" -- and that is pure call-count arithmetic over the
fixed UNIT_COSTS table (see app/services/quota.py). Every HTTP call in
this script is intercepted by respx, exactly like
backend/tests/test_bootstrap.py does to prove the bootstrap costs
exactly 103 units: the mocked response *content* does not need to be
realistic, only its shape, so the client's real batching and
pagination code runs. There is never a reason to spend real YouTube
quota to answer "how many calls does each strategy make," so replay
via respx mocks is the only mode this script has.

Fixed scenario (chosen to be small and fast, not to match production
scale -- see docs/quota-math.md's own ~100-channel daily-refresh
example for the production-scale numbers; this scenario's unit counts
scale linearly, so multiplying by 5 recovers that scale for comparison):

    NUM_TRACKED_CHANNELS   = 20   tracked channels
    NEW_VIDEOS_PER_CHANNEL = 5    new uploads discovered per channel/day
    -> 100 new videos discovered across the run.

Optimized strategy: this literally runs app.ingest.snapshot's real
run_daily_refresh -- not a re-implementation -- against 20 synthetic
"bench-*" tracked channels seeded for the duration of the run. Every
other tracked channel is temporarily untracked so the call count stays
exactly on-scenario, and the embedding/clustering hooks
run_daily_refresh calls (embed_new_videos, refresh_niche_scores) are
monkeypatched to no-ops for the duration: those are separately tested
elsewhere and have nothing to do with quota cost, and running the real
sentence-transformers/clustering pipeline over throwaway synthetic
titles would only add noise (and, if run against a shared dev
database, corrupt real niche assignments). Both the temporary
untracking and the monkeypatches are restored/undone in a finally
block, which covers any exception raised during the run but not a hard
kill (SIGKILL, container stop) -- the list of originally-tracked
channel ids lives only in process memory, so a kill between the
untrack commit and the finally block would need a manual `UPDATE
channels SET is_tracked = true WHERE id IN (...)` to recover. The
start-of-run cleanup step (deleting any leftover bench-* channels)
makes a *second* run self-healing after a crash; it does not by itself
restore real channels' tracked flags from a first run's crash.

Naive strategy: benchmark-only code that does what an unoptimized
implementation would do for the same monitoring job -- one
search.list call per tracked topic, then one videos.list call per
video, never batched. This code is not imported by app.ingest or the
scheduler; it exists solely for this comparison.

Ledger: if a live Postgres is reachable (the same DATABASE_URL the api
container uses), both strategies write real rows to api_quota_log via
DbQuotaRecorder under one run_label, and the comparison is read back
with the same (day, strategy_label) grouping /api/stats/quota uses
(app/services/quota_stats.aggregate_quota_rows). Without a reachable
database (or with --memory-only), this falls back cleanly to two
in-memory ListQuotaRecorders, wrapped into the same dict shape so the
one aggregation/report path handles both.

Run inside the api container, where DATABASE_URL already points at the
compose db service:

    docker compose exec api python -m benchmarks.bench_quota
    docker compose exec api python -m benchmarks.bench_quota --memory-only
"""

from __future__ import annotations

import argparse
import asyncio
import math
import uuid
from datetime import date, datetime, timezone

import httpx
import respx

from app.services.quota import UNIT_COSTS, DbQuotaRecorder, ListQuotaRecorder
from app.services.youtube import BASE_URL, BATCH_SIZE, YouTubeClient

NUM_TRACKED_CHANNELS = 20
NEW_VIDEOS_PER_CHANNEL = 5

BENCH_RUN_LABEL_PREFIX = "benchmark-quota"
BENCH_CHANNEL_PREFIX = "UCbench"


def naive_units_for(num_topics: int, num_videos: int) -> int:
    """Hand-computable cost of the naive strategy.

    One search.list call per topic (100 units) plus one uncached,
    unbatched videos.list call per video (1 unit each) -- a naive
    implementation would not think to batch 50 ids into one call.
    """
    return (
        num_topics * UNIT_COSTS["search.list"]
        + num_videos * UNIT_COSTS["videos.list"]
    )


def optimized_expected_units(num_channels: int, new_videos_per_channel: int) -> int:
    """Hand-computable cost of the optimized call pattern for this scenario.

    One channels.list call per 50 tracked channels, one
    playlistItems.list call per channel (a single page, since
    new_videos_per_channel here is well under the 50-per-page limit),
    and one videos.list call per 50 new videos. Used as a sanity check
    against the real, mocked run below -- if these ever disagree, the
    scenario constants and the mocks have drifted apart.
    """
    if num_channels == 0:
        return 0
    channels_calls = math.ceil(num_channels / BATCH_SIZE)
    playlist_calls = num_channels
    total_new_videos = num_channels * new_videos_per_channel
    videos_calls = math.ceil(total_new_videos / BATCH_SIZE) if total_new_videos else 0
    return (
        channels_calls * UNIT_COSTS["channels.list"]
        + playlist_calls * UNIT_COSTS["playlistItems.list"]
        + videos_calls * UNIT_COSTS["videos.list"]
    )


class NullCache:
    """Always-miss cache so this benchmark measures real, uncached calls.

    Reusing the real Redis-backed cache would risk a warm key from a
    previous run silently zeroing out a call this script means to
    count; a cache that never remembers anything removes that risk
    entirely and keeps every run identical.
    """

    async def get_json(self, key: str):
        return None

    async def set_json(self, key: str, value, ttl: int) -> None:
        return None


def bench_channel_ids(num_channels: int = NUM_TRACKED_CHANNELS) -> list[str]:
    return [f"{BENCH_CHANNEL_PREFIX}{i:03d}" for i in range(num_channels)]


def _uploads_playlist_id(channel_id: str) -> str:
    # Mirrors the real fixtures' "UU" + id[2:] convention (see
    # backend/tests/fixtures.py channel_item), so the mocked
    # contentDetails shape matches what the real API returns.
    return "UU" + channel_id[len("UC") :]


def _channel_index_from_playlist(playlist_id: str) -> int:
    return int(playlist_id[-3:])


# Video ids the playlist mock hands out look like "bvid<channel><video>",
# e.g. "bvid00003" for channel index 0, video index 3 -- a fixed-width
# encoding so the videos.list mock can recover which bench channel a
# video "belongs to" and give it a channelId that satisfies the real
# videos.channel_id foreign key when the optimized path persists it.
_VIDEO_ID_PREFIX = "bvid"


def _channel_id_from_video_id(video_id: str) -> str:
    start = len(_VIDEO_ID_PREFIX)
    channel_index = int(video_id[start : start + 3])
    return f"{BENCH_CHANNEL_PREFIX}{channel_index:03d}"


def _channels_side_effect(request: httpx.Request) -> httpx.Response:
    ids = request.url.params.get("id", "").split(",")
    items = [
        {
            "kind": "youtube#channel",
            "id": channel_id,
            "snippet": {"title": f"Bench Channel {channel_id}"},
            "statistics": {
                "subscriberCount": "1000",
                "videoCount": "10",
                "viewCount": "10000",
            },
            "contentDetails": {
                "relatedPlaylists": {"uploads": _uploads_playlist_id(channel_id)}
            },
        }
        for channel_id in ids
        if channel_id
    ]
    return httpx.Response(
        200,
        json={
            "kind": "youtube#channelListResponse",
            "items": items,
            "pageInfo": {"totalResults": len(items), "resultsPerPage": 50},
        },
    )


def _playlist_items_side_effect(request: httpx.Request) -> httpx.Response:
    playlist_id = request.url.params.get("playlistId", "")
    channel_index = _channel_index_from_playlist(playlist_id)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    items = [
        {
            "kind": "youtube#playlistItem",
            "contentDetails": {
                "videoId": f"{_VIDEO_ID_PREFIX}{channel_index:03d}{video_index:02d}",
                "videoPublishedAt": now,
            },
        }
        for video_index in range(NEW_VIDEOS_PER_CHANNEL)
    ]
    return httpx.Response(
        200,
        json={
            "kind": "youtube#playlistItemListResponse",
            "items": items,
            "pageInfo": {"totalResults": len(items), "resultsPerPage": 50},
        },
    )


def _videos_side_effect(request: httpx.Request) -> httpx.Response:
    ids = [vid for vid in request.url.params.get("id", "").split(",") if vid]
    items = [
        {
            "kind": "youtube#video",
            "id": video_id,
            "snippet": {
                "title": f"Bench video {video_id}",
                "description": "",
                # Naive-strategy video ids ("nvid...") are never persisted,
                # so an unparseable channelId there is harmless; only the
                # optimized path's "bvid..." ids need to resolve to a real
                # bench channel for the videos.channel_id FK.
                "channelId": (
                    _channel_id_from_video_id(video_id)
                    if video_id.startswith(_VIDEO_ID_PREFIX)
                    else "UCbench000"
                ),
                "publishedAt": "2026-08-20T00:00:00Z",
                "categoryId": "22",
            },
            "statistics": {"viewCount": "10", "likeCount": "1", "commentCount": "0"},
            "contentDetails": {"duration": "PT3M0S"},
        }
        for video_id in ids
    ]
    return httpx.Response(
        200,
        json={
            "kind": "youtube#videoListResponse",
            "items": items,
            "pageInfo": {"totalResults": len(items), "resultsPerPage": 50},
        },
    )


def _search_side_effect(request: httpx.Request) -> httpx.Response:
    # Content is irrelevant: the naive strategy's per-video lookups use
    # independently generated ids (see run_naive_strategy), not ids
    # parsed back out of this response. Only the endpoint and its unit
    # cost matter here.
    return httpx.Response(
        200,
        json={
            "kind": "youtube#searchListResponse",
            "items": [],
            "pageInfo": {"totalResults": 0, "resultsPerPage": 50},
        },
    )


def install_mocks() -> None:
    respx.get(f"{BASE_URL}/search").mock(side_effect=_search_side_effect)
    respx.get(f"{BASE_URL}/channels").mock(side_effect=_channels_side_effect)
    respx.get(f"{BASE_URL}/playlistItems").mock(side_effect=_playlist_items_side_effect)
    respx.get(f"{BASE_URL}/videos").mock(side_effect=_videos_side_effect)


async def run_naive_strategy(
    client: YouTubeClient,
    num_topics: int = NUM_TRACKED_CHANNELS,
    videos_per_topic: int = NEW_VIDEOS_PER_CHANNEL,
) -> None:
    """Benchmark-only: one search per tracked topic, one videos.list
    call per video, no batching. Never wired into app.ingest or the
    scheduler -- this exists purely so bench_quota.py has a naive side
    to compare the real optimized strategy against.
    """
    for topic_index in range(num_topics):
        await client.search(f"bench topic {topic_index}", type="video")

    for topic_index in range(num_topics):
        for video_index in range(videos_per_topic):
            video_id = f"nvid{topic_index:03d}{video_index:02d}"
            # One call per video on purpose: the naive mistake this
            # strategy models is not batching 50 ids into one call.
            await client.list_videos([video_id])


async def run_optimized_call_pattern(
    client: YouTubeClient,
    num_channels: int = NUM_TRACKED_CHANNELS,
    new_videos_per_channel: int = NEW_VIDEOS_PER_CHANNEL,
) -> None:
    """In-memory fallback: the same call sequence run_daily_refresh
    makes (batched channels.list, one playlistItems.list page per
    channel, batched videos.list for the new ids), without a database.
    Used only when no Postgres is reachable -- see main(). When a
    database is available, run_optimized_via_db below calls the real
    run_daily_refresh instead of this stand-in.
    """
    channel_ids = bench_channel_ids(num_channels)
    channels_response = await client.list_channels(channel_ids)

    new_ids: list[str] = []
    for item in channels_response:
        uploads = item["contentDetails"]["relatedPlaylists"]["uploads"]
        page = await client.list_playlist_items(uploads)
        for entry in page.get("items", []):
            video_id = entry.get("contentDetails", {}).get("videoId")
            if video_id:
                new_ids.append(video_id)

    if new_ids:
        await client.list_videos(new_ids)


async def _try_get_db_session_factory():
    """Return a working session factory, or None if no live Postgres
    with a migrated schema is reachable. Any failure here (connection
    refused, wrong credentials, unmigrated schema) degrades to the
    in-memory fallback rather than raising -- this script must always
    be runnable, per its own reason for existing.
    """
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        async with SessionLocal() as session:
            await session.execute(text("SELECT 1 FROM channels LIMIT 1"))
        return SessionLocal
    except Exception as exc:  # noqa: BLE001 - any failure means "fall back"
        print(
            f"No usable Postgres found ({exc.__class__.__name__}: {exc}); "
            "falling back to an in-memory ledger for both strategies."
        )
        return None


async def run_optimized_via_db(session_factory, run_label: str) -> dict:
    """Run the real run_daily_refresh against a fixed, isolated scenario.

    Seeds NUM_TRACKED_CHANNELS synthetic channels as the only tracked
    channels for the duration of the run (any real tracked channels
    are restored afterward), monkeypatches out the embedding/scoring
    hooks (out of scope for a quota benchmark, see module docstring),
    runs the real function against respx-mocked HTTP, then cleans up
    every row it touched.
    """
    from sqlalchemy import delete, select, update

    from app.db.models import Channel
    from app.ingest import snapshot as snapshot_module

    channel_ids = bench_channel_ids()

    async def _noop(*_args, **_kwargs) -> None:
        return None

    async with session_factory() as session:
        # Self-healing: if a previous run crashed before cleanup, clear
        # any leftover bench channels before seeding fresh ones.
        await session.execute(delete(Channel).where(Channel.id.in_(channel_ids)))
        original_tracked = [
            row.id
            for row in (
                await session.execute(
                    select(Channel.id).where(Channel.is_tracked.is_(True))
                )
            ).all()
        ]
        await session.execute(update(Channel).values(is_tracked=False))
        for channel_id in channel_ids:
            session.add(Channel(id=channel_id, is_tracked=True))
        await session.commit()

    original_embed = snapshot_module.embed_new_videos
    original_score = snapshot_module.refresh_niche_scores
    snapshot_module.embed_new_videos = _noop
    snapshot_module.refresh_niche_scores = _noop

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            client = YouTubeClient(
                api_key="benchmark-key",
                http=http,
                cache=NullCache(),
                quota=DbQuotaRecorder(session_factory),
                run_label=run_label,
                strategy_label="optimized",
            )
            with respx.mock:
                install_mocks()
                summary = await snapshot_module.run_daily_refresh(session_factory, client)
        return summary
    finally:
        snapshot_module.embed_new_videos = original_embed
        snapshot_module.refresh_niche_scores = original_score
        async with session_factory() as session:
            # Cascades to this run's videos/snapshots/embeddings too.
            await session.execute(delete(Channel).where(Channel.id.in_(channel_ids)))
            await session.execute(update(Channel).values(is_tracked=False))
            if original_tracked:
                await session.execute(
                    update(Channel)
                    .where(Channel.id.in_(original_tracked))
                    .values(is_tracked=True)
                )
            await session.commit()


async def _fetch_db_rows(session_factory, run_label: str) -> list[dict]:
    """Read this run's rows back the same way /api/stats/quota does."""
    from sqlalchemy import func, select

    from app.db.models import ApiQuotaLog

    async with session_factory() as session:
        stmt = select(
            func.date(ApiQuotaLog.created_at).label("day"),
            ApiQuotaLog.strategy_label,
            ApiQuotaLog.endpoint,
            ApiQuotaLog.cache_hit,
            ApiQuotaLog.units,
        ).where(ApiQuotaLog.run_label == run_label)
        result = await session.execute(stmt)
        return [
            {
                "day": row.day.date() if isinstance(row.day, datetime) else row.day,
                "strategy_label": row.strategy_label,
                "endpoint": row.endpoint,
                "cache_hit": row.cache_hit,
                "units": row.units,
            }
            for row in result.all()
        ]


def _rows_from_recorder(recorder: ListQuotaRecorder, strategy_label: str) -> list[dict]:
    today = date.today()
    return [
        {
            "day": today,
            "strategy_label": strategy_label,
            "endpoint": entry.endpoint,
            "cache_hit": entry.cache_hit,
            "units": entry.units,
        }
        for entry in recorder.entries
    ]


def print_report(run_label: str, source: str, groups: list[dict]) -> None:
    by_strategy = {group["strategy_label"]: group for group in groups}
    print(f"\nQuota benchmark ({source}), run_label={run_label}")
    print(
        f"Scenario: {NUM_TRACKED_CHANNELS} tracked channels, "
        f"{NEW_VIDEOS_PER_CHANNEL} new videos each "
        f"({NUM_TRACKED_CHANNELS * NEW_VIDEOS_PER_CHANNEL} new videos total)"
    )
    print(f"{'strategy':<12} {'units_spent':>12} {'calls_uncached':>15}")
    for label in ("naive", "optimized"):
        group = by_strategy.get(label)
        units = group["units_spent"] if group else 0
        calls = group["calls_uncached"] if group else 0
        print(f"{label:<12} {units:>12} {calls:>15}")

    naive_units = by_strategy.get("naive", {}).get("units_spent", 0)
    optimized_units = by_strategy.get("optimized", {}).get("units_spent", 0)

    # Sanity check: the measured numbers must match the hand-computable
    # formulas exactly. If they ever disagree, the scenario constants
    # and the mocks (or a code change to snapshot.py) have drifted
    # apart, and that is a bug in this benchmark worth surfacing loudly
    # rather than silently reporting a wrong-but-plausible number.
    expected_naive = naive_units_for(
        NUM_TRACKED_CHANNELS, NUM_TRACKED_CHANNELS * NEW_VIDEOS_PER_CHANNEL
    )
    expected_optimized = optimized_expected_units(
        NUM_TRACKED_CHANNELS, NEW_VIDEOS_PER_CHANNEL
    )
    if naive_units != expected_naive or optimized_units != expected_optimized:
        print(
            "\nMISMATCH: measured units do not match the hand-computed "
            f"formulas (naive: measured {naive_units} vs expected "
            f"{expected_naive}; optimized: measured {optimized_units} vs "
            f"expected {expected_optimized}). Treat the numbers below as "
            "suspect until this is explained."
        )

    if naive_units:
        saved_pct = (naive_units - optimized_units) / naive_units * 100
        print(
            f"\nOptimized costs {optimized_units} units vs {naive_units} naive "
            f"-- {saved_pct:.1f} percent fewer units for the same "
            "monitoring work."
        )
        print(
            "Scaled 5x (to the ~100-channel scale docs/quota-math.md "
            f"illustrates): naive {naive_units * 5}, optimized "
            f"{optimized_units * 5} units/day."
        )


async def main(memory_only: bool = False) -> int:
    from app.services.quota_stats import aggregate_quota_rows

    # Unique per invocation, not just per day: the DB path reads back
    # every row logged under this run_label, so two runs on the same
    # day sharing one label would silently double-count each other.
    today = date.today().isoformat()
    run_label = f"{BENCH_RUN_LABEL_PREFIX}-{today}-{uuid.uuid4().hex[:8]}"

    session_factory = None if memory_only else await _try_get_db_session_factory()

    if session_factory is not None:
        naive_recorder = DbQuotaRecorder(session_factory)
        async with httpx.AsyncClient(timeout=10) as http:
            naive_client = YouTubeClient(
                api_key="benchmark-key",
                http=http,
                cache=NullCache(),
                quota=naive_recorder,
                run_label=run_label,
                strategy_label="naive",
            )
            with respx.mock:
                install_mocks()
                await run_naive_strategy(naive_client)

        await run_optimized_via_db(session_factory, run_label)

        rows = await _fetch_db_rows(session_factory, run_label)
        source = "real Postgres, api_quota_log"
    else:
        naive_recorder = ListQuotaRecorder()
        optimized_recorder = ListQuotaRecorder()
        async with httpx.AsyncClient(timeout=10) as http:
            naive_client = YouTubeClient(
                api_key="benchmark-key",
                http=http,
                cache=NullCache(),
                quota=naive_recorder,
                run_label=run_label,
                strategy_label="naive",
            )
            optimized_client = YouTubeClient(
                api_key="benchmark-key",
                http=http,
                cache=NullCache(),
                quota=optimized_recorder,
                run_label=run_label,
                strategy_label="optimized",
            )
            with respx.mock:
                install_mocks()
                await run_naive_strategy(naive_client)
                await run_optimized_call_pattern(optimized_client)

        rows = _rows_from_recorder(naive_recorder, "naive") + _rows_from_recorder(
            optimized_recorder, "optimized"
        )
        source = "in-memory ListQuotaRecorder (no live Postgres found)"

    groups = aggregate_quota_rows(rows)
    print_report(run_label, source, groups)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memory-only",
        action="store_true",
        help="Skip the live-Postgres check and use in-memory recorders for both strategies.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    import sys

    args = _parse_args()
    sys.exit(asyncio.run(main(memory_only=args.memory_only)))
