"""Tests for the YouTube client: batching, caching, quota, retries."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.cache import TTL_VIDEOS, build_key
from app.services.youtube import BASE_URL, QuotaExceededError, YouTubeApiError

from tests.fixtures import (
    channels_response,
    playlist_items_response,
    search_response,
    videos_response,
)


@respx.mock
async def test_list_videos_batches_120_ids_into_3_calls(yt, recorder):
    route = respx.get(f"{BASE_URL}/videos").mock(
        side_effect=lambda request: httpx.Response(
            200, json=videos_response(request.url.params["id"].split(","))
        )
    )
    ids = [f"vid{i:08d}" for i in range(120)]

    items = await yt.list_videos(ids)

    assert route.call_count == 3
    sizes = [
        len(call.request.url.params["id"].split(",")) for call in route.calls
    ]
    assert sizes == [50, 50, 20]
    assert len(items) == 120
    assert recorder.total_units == 3
    assert all(e.endpoint == "videos.list" and not e.cache_hit for e in recorder.entries)


@respx.mock
async def test_list_channels_batches_120_ids_into_3_calls(yt, recorder):
    route = respx.get(f"{BASE_URL}/channels").mock(
        side_effect=lambda request: httpx.Response(
            200, json=channels_response(request.url.params["id"].split(","))
        )
    )
    ids = [f"UCchan{i:06d}" for i in range(120)]

    items = await yt.list_channels(ids)

    assert route.call_count == 3
    assert len(items) == 120
    assert recorder.total_units == 3


@respx.mock
async def test_cache_hit_records_zero_units_and_skips_http(yt, recorder):
    route = respx.get(f"{BASE_URL}/videos").mock(
        return_value=httpx.Response(200, json=videos_response(["vid00000001"]))
    )

    await yt.list_videos(["vid00000001"])
    await yt.list_videos(["vid00000001"])

    assert route.call_count == 1
    assert [e.units for e in recorder.entries] == [1, 0]
    assert [e.cache_hit for e in recorder.entries] == [False, True]


@respx.mock
async def test_cache_miss_records_correct_units_and_caches(yt, recorder, fake_cache):
    respx.get(f"{BASE_URL}/videos").mock(
        return_value=httpx.Response(200, json=videos_response(["vid00000001"]))
    )

    await yt.list_videos(["vid00000001"])

    assert recorder.entries[0].units == 1
    assert recorder.entries[0].cache_hit is False
    assert len(fake_cache.store) == 1
    assert list(fake_cache.ttls.values()) == [TTL_VIDEOS]


@respx.mock
async def test_search_records_100_units(yt, recorder):
    respx.get(f"{BASE_URL}/search").mock(
        return_value=httpx.Response(200, json=search_response())
    )

    result = await yt.search("japanese high school soccer")

    assert result["items"][0]["id"]["videoId"] == "vid00000001"
    assert recorder.entries[0].endpoint == "search.list"
    assert recorder.entries[0].units == 100


@respx.mock
async def test_retry_on_500_then_success(yt, recorder, monkeypatch):
    # Skip the real backoff sleep to keep the test fast.
    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr("app.services.youtube.asyncio.sleep", no_sleep)
    route = respx.get(f"{BASE_URL}/playlistItems").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json=playlist_items_response("UUabc123")),
        ]
    )

    result = await yt.list_playlist_items("UUabc123")

    assert route.call_count == 2
    assert result["nextPageToken"] == "CAUQAA"
    assert recorder.total_units == 1


@respx.mock
async def test_gives_up_after_three_failures(yt, monkeypatch):
    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr("app.services.youtube.asyncio.sleep", no_sleep)
    route = respx.get(f"{BASE_URL}/videos").mock(
        return_value=httpx.Response(503)
    )

    with pytest.raises(YouTubeApiError):
        await yt.list_videos(["vid00000001"])
    assert route.call_count == 3


@respx.mock
async def test_403_raises_quota_exceeded(yt):
    respx.get(f"{BASE_URL}/search").mock(return_value=httpx.Response(403))

    with pytest.raises(QuotaExceededError):
        await yt.search("anything")


def test_params_order_does_not_change_cache_key():
    key_a = build_key("videos.list", {"part": "snippet", "id": "a,b", "maxResults": 50})
    key_b = build_key("videos.list", {"maxResults": 50, "id": "a,b", "part": "snippet"})
    assert key_a == key_b
    assert key_a.startswith("yt:videos.list:")


@respx.mock
async def test_api_key_never_in_cache_keys(yt, fake_cache):
    respx.get(f"{BASE_URL}/videos").mock(
        return_value=httpx.Response(200, json=videos_response(["vid00000001"]))
    )

    await yt.list_videos(["vid00000001"])

    assert all("test-key" not in key for key in fake_cache.store)
