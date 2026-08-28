"""Layer 1 cache: raw YouTube API responses stored as JSON in Redis.

This cache makes the bootstrap resumable and retries free. Keys never
contain the API key, only the endpoint and a hash of the query params.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from redis.asyncio import Redis

# TTLs in seconds. Search results change slowly, stats change fast.
TTL_SEARCH = 7 * 24 * 3600
TTL_CHANNELS = 24 * 3600
TTL_VIDEOS = 12 * 3600
TTL_PLAYLIST_ITEMS = 6 * 3600

ENDPOINT_TTLS: dict[str, int] = {
    "search.list": TTL_SEARCH,
    "channels.list": TTL_CHANNELS,
    "videos.list": TTL_VIDEOS,
    "playlistItems.list": TTL_PLAYLIST_ITEMS,
}


def build_key(endpoint: str, params: dict[str, Any]) -> str:
    """Build a deterministic cache key from endpoint plus params.

    Params are serialized with sorted keys so ordering does not change
    the key. The API key must never be in the params passed here.
    """
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"yt:{endpoint}:{digest}"


class ResponseCache:
    """Thin async wrapper over Redis for JSON payloads.

    When cache_enabled is False reads always miss, but writes still
    happen so a later run with caching on can benefit.
    """

    def __init__(self, redis: Redis, cache_enabled: bool = True) -> None:
        self._redis = redis
        self.cache_enabled = cache_enabled

    async def get_json(self, key: str) -> Any | None:
        if not self.cache_enabled:
            return None
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl)
