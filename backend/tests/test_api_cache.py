"""Tests for the Layer 2 (computed-response) cache key builder and the
fail-open ApiResponseCache wrapper. No database, no real Redis.
"""

from __future__ import annotations

import pytest

from app.services.api_cache import ApiResponseCache, build_key


def test_build_key_is_deterministic_regardless_of_param_order():
    key1 = build_key("niches", {"limit": 20, "offset": 0})
    key2 = build_key("niches", {"offset": 0, "limit": 20})
    assert key1 == key2
    assert key1.startswith("api:niches:")


def test_build_key_differs_by_area_and_by_params():
    assert build_key("niches", {"limit": 20}) != build_key("similar", {"limit": 20})
    assert build_key("niches", {"limit": 20}) != build_key("niches", {"limit": 21})


class _BrokenRedis:
    """Stands in for a Redis client that is simply down."""

    async def get(self, key):
        raise ConnectionError("redis is down")

    async def set(self, key, value, ex=None):
        raise ConnectionError("redis is down")


@pytest.mark.asyncio
async def test_cache_fails_open_on_redis_errors():
    cache = ApiResponseCache(_BrokenRedis())
    # Neither call should raise; a down Redis must degrade to "always
    # compute," never to a 500.
    assert await cache.get_json("api:niches:x") is None
    await cache.set_json("api:niches:x", {"a": 1}, ttl=60)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.mark.asyncio
async def test_cache_round_trips_json():
    cache = ApiResponseCache(_FakeRedis())
    await cache.set_json("k", {"a": [1, 2, 3]}, ttl=60)
    assert await cache.get_json("k") == {"a": [1, 2, 3]}


@pytest.mark.asyncio
async def test_cache_disabled_always_misses_on_read_but_still_writes():
    redis = _FakeRedis()
    cache = ApiResponseCache(redis, cache_enabled=False)
    await cache.set_json("k", {"a": 1}, ttl=60)
    assert await cache.get_json("k") is None
    # The write still happened, so re-enabling caching later benefits.
    assert redis.store["k"] is not None
