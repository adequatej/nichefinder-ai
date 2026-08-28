"""Async YouTube Data API v3 client with caching and quota accounting.

Every request goes through one path: check the response cache, record
quota units either way, retry transient failures, and never let the
API key leak into cache keys or log output.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

from app.services.cache import ENDPOINT_TTLS, build_key
from app.services.quota import QuotaRecorder, units_for

BASE_URL = "https://www.googleapis.com/youtube/v3"
BATCH_SIZE = 50
MAX_TRIES = 3
BACKOFF_BASE_SECONDS = 0.5

ENDPOINT_PATHS: dict[str, str] = {
    "search.list": "/search",
    "channels.list": "/channels",
    "videos.list": "/videos",
    "playlistItems.list": "/playlistItems",
}


class ResponseCacheLike(Protocol):
    """The subset of the cache interface the client needs."""

    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl: int) -> None: ...


class YouTubeApiError(Exception):
    """A YouTube API call failed after retries."""


class QuotaExceededError(YouTubeApiError):
    """The daily quota is exhausted. Resume tomorrow; cached calls still work."""


class YouTubeClient:
    def __init__(
        self,
        api_key: str,
        http: httpx.AsyncClient,
        cache: ResponseCacheLike,
        quota: QuotaRecorder,
        run_label: str | None = None,
        strategy_label: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._cache = cache
        self._quota = quota
        self.run_label = run_label
        self.strategy_label = strategy_label

    async def search(self, q: str, **params: Any) -> dict:
        merged = {
            "part": "snippet",
            "type": "video",
            "maxResults": 50,
            "relevanceLanguage": "en",
            "q": q,
        }
        merged.update(params)
        # Passing None for a param drops it, so callers can make an
        # untyped search (no type filter) with type=None.
        merged = {key: value for key, value in merged.items() if value is not None}
        return await self._request("search.list", merged)

    async def list_channels(self, ids: list[str]) -> list[dict]:
        """Fetch channel details, batching up to 50 ids per call."""
        items: list[dict] = []
        for batch in _chunks(ids, BATCH_SIZE):
            response = await self._request(
                "channels.list",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            items.extend(response.get("items", []))
        return items

    async def list_videos(self, ids: list[str]) -> list[dict]:
        """Fetch video details, batching up to 50 ids per call."""
        items: list[dict] = []
        for batch in _chunks(ids, BATCH_SIZE):
            response = await self._request(
                "videos.list",
                {
                    "part": "snippet,statistics,contentDetails,liveStreamingDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            items.extend(response.get("items", []))
        return items

    async def list_playlist_items(
        self,
        playlist_id: str,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> dict:
        params: dict[str, Any] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": max_results,
        }
        if page_token:
            params["pageToken"] = page_token
        return await self._request("playlistItems.list", params)

    async def _request(self, endpoint: str, params: dict[str, Any]) -> dict:
        """Cache check, quota record, HTTP call with retries."""
        cache_key = build_key(endpoint, params)
        cached = await self._cache.get_json(cache_key)
        if cached is not None:
            await self._record(endpoint, 0, cache_hit=True)
            return cached

        response = await self._fetch_with_retries(endpoint, params)
        await self._record(endpoint, units_for(endpoint), cache_hit=False)
        await self._cache.set_json(cache_key, response, ENDPOINT_TTLS[endpoint])
        return response

    async def _fetch_with_retries(self, endpoint: str, params: dict[str, Any]) -> dict:
        url = BASE_URL + ENDPOINT_PATHS[endpoint]
        # The key goes only into the outgoing request, never into cache keys.
        request_params = {**params, "key": self._api_key}
        last_status: int | None = None
        for attempt in range(MAX_TRIES):
            response = await self._http.get(url, params=request_params)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 403:
                raise QuotaExceededError(
                    f"YouTube API returned 403 on {endpoint}. This usually "
                    "means the daily quota is exhausted or the key is "
                    "restricted. Check the quota page in Google Cloud."
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                if attempt < MAX_TRIES - 1:
                    await asyncio.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
                continue
            raise YouTubeApiError(
                f"YouTube API returned {response.status_code} on {endpoint}"
            )
        raise YouTubeApiError(
            f"YouTube API call to {endpoint} failed after {MAX_TRIES} tries "
            f"(last status {last_status})"
        )

    async def _record(self, endpoint: str, units: int, cache_hit: bool) -> None:
        await self._quota.record(
            endpoint,
            units,
            cache_hit,
            run_label=self.run_label,
            strategy_label=self.strategy_label,
        )


def _chunks(ids: list[str], size: int) -> list[list[str]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]
