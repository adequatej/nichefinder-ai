"""Bootstrap orchestration tests with respx. No database needed.

The in-memory sink stands in for Postgres, and the FakeCache plus
ListQuotaRecorder verify the quota story: a small run costs exactly
103 units (1 search at 100, plus 1 channels, 1 playlist page, and 1
videos call at 1 each), and a full rerun over the warm cache costs 0.
"""

from __future__ import annotations

import httpx
import respx

from app.ingest.bootstrap import run_bootstrap
from app.ingest.langfilter import detect_language
from app.ingest.persist import video_row
from app.services.youtube import BASE_URL, YouTubeClient

from tests.conftest import FakeCache
from tests.fixtures import channels_response, search_response, videos_response
from app.services.quota import ListQuotaRecorder


class MemorySink:
    """In-memory IngestSink so orchestration runs without a database."""

    def __init__(self) -> None:
        self.channels: list[dict] = []
        self.videos: list[dict] = []
        self.tracked: list[str] = []

    async def save_channels(self, api_items: list[dict]) -> None:
        self.channels.extend(api_items)

    async def save_videos(self, api_items: list[dict]) -> None:
        # Same transform path as the database sink uses.
        for item in api_items:
            snippet = item.get("snippet", {})
            language = detect_language(
                snippet.get("title", ""), snippet.get("description", "")
            )
            self.videos.append(video_row(item, language))

    async def video_rows(self) -> list[dict]:
        return list(self.videos)

    async def mark_tracked(self, channel_ids: list[str]) -> None:
        self.tracked = list(channel_ids)


def _single_page_playlist_response() -> dict:
    return {
        "kind": "youtube#playlistItemListResponse",
        "items": [
            {
                "kind": "youtube#playlistItem",
                "contentDetails": {
                    "videoId": "vid00000001",
                    "videoPublishedAt": "2026-08-01T12:00:00Z",
                },
            }
        ],
        "pageInfo": {"totalResults": 1, "resultsPerPage": 50},
    }


def _mock_routes():
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=search_response())
    )
    respx.get(f"{BASE_URL}/channels").mock(
        return_value=httpx.Response(200, json=channels_response(["UCabc123"]))
    )
    respx.get(f"{BASE_URL}/playlistItems").mock(
        return_value=httpx.Response(200, json=_single_page_playlist_response())
    )
    respx.get(f"{BASE_URL}/videos").mock(
        return_value=httpx.Response(200, json=videos_response(["vid00000001"]))
    )


def _client(http, cache, recorder) -> YouTubeClient:
    return YouTubeClient(
        api_key="test-key", http=http, cache=cache, quota=recorder
    )


@respx.mock
async def test_small_bootstrap_costs_exactly_103_units(http_client):
    _mock_routes()
    cache = FakeCache()
    recorder = ListQuotaRecorder()
    sink = MemorySink()

    summary = await run_bootstrap(
        _client(http_client, cache, recorder),
        sink,
        keywords=("japanese high school soccer",),
        seed_channel_ids=[],
    )

    assert recorder.total_units == 103
    endpoints = sorted(e.endpoint for e in recorder.entries)
    assert endpoints == [
        "channels.list",
        "playlistItems.list",
        "search.list",
        "videos.list",
    ]
    assert len(sink.channels) == 1
    assert len(sink.videos) == 1
    # The fixture video is a Seiwa Gakuen title, so both gates count it.
    assert summary["gate_a_count"] == 1
    assert summary["gate_b_count"] == 1
    assert sink.tracked == ["UCabc123"]
    assert summary["stopped_on_quota"] is False


@respx.mock
async def test_full_rerun_over_warm_cache_costs_zero_units(http_client):
    _mock_routes()
    cache = FakeCache()
    sink = MemorySink()

    first = ListQuotaRecorder()
    await run_bootstrap(
        _client(http_client, cache, first),
        sink,
        keywords=("japanese high school soccer",),
        seed_channel_ids=[],
    )
    assert first.total_units == 103

    # Same cache, fresh recorder and sink: everything replays for free.
    second = ListQuotaRecorder()
    rerun_sink = MemorySink()
    summary = await run_bootstrap(
        _client(http_client, cache, second),
        rerun_sink,
        keywords=("japanese high school soccer",),
        seed_channel_ids=[],
    )

    assert second.total_units == 0
    assert all(entry.cache_hit for entry in second.entries)
    assert len(rerun_sink.videos) == 1
    assert summary["gate_b_count"] == 1


@respx.mock
async def test_quota_exhaustion_stops_cleanly_and_keeps_progress(http_client):
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=search_response())
    )
    respx.get(f"{BASE_URL}/channels").mock(
        return_value=httpx.Response(200, json=channels_response(["UCabc123"]))
    )
    # Quota dies at the playlist walk.
    respx.get(f"{BASE_URL}/playlistItems").mock(
        return_value=httpx.Response(403)
    )
    cache = FakeCache()
    recorder = ListQuotaRecorder()
    sink = MemorySink()

    summary = await run_bootstrap(
        _client(http_client, cache, recorder),
        sink,
        keywords=("japanese high school soccer",),
        seed_channel_ids=[],
    )

    # The run did not raise, the channels ingested so far survive, and
    # the gates report zero videos instead of crashing.
    assert summary["stopped_on_quota"] is True
    assert len(sink.channels) == 1
    assert summary["gate_a_count"] == 0
    assert summary["videos_ingested"] == 0
