"""Shared test fixtures. No database or Redis needed."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.services.quota import ListQuotaRecorder
from app.services.youtube import YouTubeClient


class FakeCache:
    """In-memory stand-in for ResponseCache with the same interface."""

    def __init__(self, cache_enabled: bool = True) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.cache_enabled = cache_enabled

    async def get_json(self, key: str) -> Any | None:
        if not self.cache_enabled:
            return None
        return self.store.get(key)

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        self.store[key] = value
        self.ttls[key] = ttl


@pytest.fixture
def fake_cache() -> FakeCache:
    return FakeCache()


@pytest.fixture
def recorder() -> ListQuotaRecorder:
    return ListQuotaRecorder()


@pytest.fixture
async def http_client():
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def yt(http_client, fake_cache, recorder) -> YouTubeClient:
    return YouTubeClient(
        api_key="test-key",
        http=http_client,
        cache=fake_cache,
        quota=recorder,
    )
