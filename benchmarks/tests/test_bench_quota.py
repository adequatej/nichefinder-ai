"""Exact-arithmetic tests for the naive quota strategy.

Same spirit as backend/tests/test_bootstrap.py's exact-103-units test:
a small, deterministic, hand-computable assertion. The full HTTP round
trip through a real YouTubeClient plus respx mocks is covered by
actually running `python -m benchmarks.bench_quota` (see
benchmarks/results/BENCHMARKS.md for that output) rather than
duplicated here.
"""

from __future__ import annotations

import httpx
import respx

from app.services.quota import ListQuotaRecorder
from app.services.youtube import BASE_URL, YouTubeClient

from benchmarks.bench_quota import (
    install_mocks,
    naive_units_for,
    optimized_expected_units,
    run_naive_strategy,
)


def test_naive_units_formula_is_topics_times_100_plus_videos():
    # 5 topics scanned once each (500) plus 12 videos looked up one at
    # a time (12) is exactly 512 units -- no batching credit anywhere.
    assert naive_units_for(num_topics=5, num_videos=12) == 512


def test_naive_units_formula_handles_zero_topics_or_videos():
    assert naive_units_for(num_topics=0, num_videos=0) == 0
    assert naive_units_for(num_topics=1, num_videos=0) == 100
    assert naive_units_for(num_topics=0, num_videos=1) == 1


def test_optimized_expected_units_batches_by_fifty():
    # 120 channels needs 3 batched channels.list calls (ceil(120/50)),
    # one playlistItems.list page per channel, and 360 new videos
    # needs 8 batched videos.list calls (ceil(360/50)).
    assert optimized_expected_units(num_channels=120, new_videos_per_channel=3) == (
        3 * 1 + 120 * 1 + 8 * 1
    )


@respx.mock
async def test_run_naive_strategy_costs_exactly_the_formula():
    install_mocks()
    recorder = ListQuotaRecorder()
    async with httpx.AsyncClient() as http_client:
        client = YouTubeClient(
            api_key="test-key",
            http=http_client,
            cache=_AlwaysMissCache(),
            quota=recorder,
            strategy_label="naive",
        )
        await run_naive_strategy(client, num_topics=4, videos_per_topic=3)

    assert recorder.total_units == naive_units_for(num_topics=4, num_videos=12)
    endpoints = [entry.endpoint for entry in recorder.entries]
    assert endpoints.count("search.list") == 4
    assert endpoints.count("videos.list") == 12
    assert all(not entry.cache_hit for entry in recorder.entries)


class _AlwaysMissCache:
    async def get_json(self, key: str):
        return None

    async def set_json(self, key: str, value, ttl: int) -> None:
        return None
