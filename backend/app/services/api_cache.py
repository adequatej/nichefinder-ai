"""Layer 2 cache: this API's own computed JSON responses, in Redis.

Distinct from `cache.py`'s Layer 1 cache, which stores raw upstream
YouTube API responses so ingestion is resumable and cheap to retry.
Layer 2 stores the *results of our own computation* over already-
ingested data (a niches list, a similarity search, a query embedding)
so a repeated request skips the database query, the nearest-neighbor
scan, or — for search — the sentence-transformers forward pass
entirely. That last one is the dominant win: embedding a query costs
far more wall-clock time than the pgvector scan that follows it, so
`api:search:embed:*` caches the embedding vector itself, not just the
final response, and is checked before `_get_model()` is ever touched.

Keys are namespaced `api:<area>:<hash>` (compare Layer 1's `yt:*`) so
the two caches can never collide even though they share one Redis.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncGenerator
from typing import Any

from redis.asyncio import Redis

from app.config import get_settings

TTL_NICHES = 15 * 60
TTL_SIMILAR = 60 * 60
TTL_SEARCH = 60 * 60
# The query embedding is cheap to keep around long after the response
# it fed has expired; re-embedding is the expensive part, not storage.
TTL_SEARCH_EMBEDDING = 60 * 60


def build_key(area: str, params: dict[str, Any]) -> str:
    """Build a deterministic cache key from an area name plus params.

    Mirrors cache.py's build_key: params are serialized with sorted
    keys so argument order never changes the key.
    """
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return f"api:{area}:{digest}"


class ApiResponseCache:
    """Thin async wrapper over Redis for computed JSON payloads.

    Fails open: any Redis error is treated as a cache miss on read and
    a no-op on write, so a down Redis degrades to "compute every time"
    rather than a 500. cache_enabled=False (mirrors ResponseCache)
    always misses on read but still writes, so turning caching back on
    later benefits from whatever was written while it was off.
    """

    def __init__(self, redis: Redis, cache_enabled: bool = True) -> None:
        self._redis = redis
        self.cache_enabled = cache_enabled

    async def get_json(self, key: str) -> Any | None:
        if not self.cache_enabled:
            return None
        try:
            raw = await self._redis.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._redis.set(key, json.dumps(value), ex=ttl)
        except Exception:
            pass


async def get_api_cache() -> AsyncGenerator[ApiResponseCache, None]:
    """FastAPI dependency: a per-request Redis connection wrapped in ApiResponseCache.

    Mirrors health.py's inline `aioredis.from_url` pattern rather than a
    shared module-level client, so a bad redis_url surfaces per-request
    (as a cache miss, per the fail-open behavior above) instead of at
    import time.
    """
    settings = get_settings()
    client = Redis.from_url(settings.redis_url)
    try:
        yield ApiResponseCache(client, cache_enabled=settings.cache_enabled)
    finally:
        await client.aclose()
