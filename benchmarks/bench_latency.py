"""Latency benchmark for the live /api/search and /api/niches endpoints.

Precondition: this script does not start, migrate, or seed anything.
It expects a running stack -- `make up`, `make migrate`, then either
`make bootstrap-sample` or a real `make bootstrap`, then `make
cluster` -- reachable at BENCHMARK_API_URL (default
http://localhost:8000). Run it from inside the api container, where
that default already resolves to the api's own server:

    docker compose exec api python -m benchmarks.bench_latency

Unlike bench_quota.py, these numbers are not architecture-only: they
depend on how much data is actually in Postgres/Redis right now. This
script's precondition is the sample corpus (a few hundred videos, one
niches table with about a dozen rows), so treat these as "latency at
sample-corpus scale," not a promise about latency at 10k+ real videos
-- a bigger corpus makes the nearest-neighbor scan and the niches
query slower, though the *relative* cold-vs-warm gap this script is
really measuring (cache miss vs. cache hit) should hold at any scale,
since that gap is dominated by re-running the embedding model and/or
the database query, not by their absolute cost.

What "cold" and "warm" mean here, concretely:

  /api/niches: Layer 2 caches the computed response per (limit,
  offset) (see app/services/api_cache.py). Cold samples use a fresh,
  never-before-requested offset each time (a random per-run salt), so
  every one is a guaranteed cache miss. Warm samples repeat one fixed
  (limit, offset) after a warmup call, so every timed request is a
  cache hit.

  /api/search: two Layer 2 caches stack here -- the query embedding
  (keyed on q alone) and the full response (keyed on q + limit). Cold
  samples use distinct, realistic-looking queries salted with a random
  per-run token, so neither cache has ever seen them (a true cold
  path, not an OS/HTTP-level artifact of reusing one string). Warm
  samples repeat one fixed (q, limit) after a warmup call, hitting the
  full response cache -- described in api_cache.py as "the dominant
  win." A third set holds q fixed but varies limit, so the response
  cache always misses while the embedding cache always hits: this
  isolates how much of the win is "skip the embedding model" versus
  "skip the whole request."

  One wrinkle: the very first call to /api/search in a freshly started
  process pays a one-time cost to load the sentence-transformers model
  into memory. That is a process-lifetime cost that has nothing to do
  with caching, so the cold-search benchmark burns it off with one
  throwaway warmup query before timing anything -- otherwise it would
  dominate every other number here.

Reports p50/p95 in absolute milliseconds per case, never a percentage
averaged across endpoints -- some endpoints barely benefit from
caching and others benefit enormously, and blending those into one
number would hide exactly the thing worth knowing.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass

import httpx

BASE_URL = os.environ.get("BENCHMARK_API_URL", "http://localhost:8000")
COLD_SAMPLES = 20
WARM_SAMPLES = 30

REALISTIC_QUERIES = [
    "arsenal vs chelsea highlights",
    "japanese high school soccer",
    "premier league goals compilation",
    "high school football japan",
    "champions league highlights",
    "soccer training drills",
    "youth soccer tournament",
    "goalkeeper saves compilation",
]

WARM_SEARCH_QUERY = "arsenal vs chelsea highlights"
WARM_NICHES_PARAMS = {"limit": 20, "offset": 0}


@dataclass
class LatencyStats:
    label: str
    n: int
    p50_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float

    def format_row(self) -> str:
        return (
            f"{self.label:<45} {self.n:>4}  p50={self.p50_ms:8.1f}ms  "
            f"p95={self.p95_ms:8.1f}ms  (min={self.min_ms:.1f}, max={self.max_ms:.1f})"
        )


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolation percentile. No numpy dependency needed for
    sample sizes this small."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(label: str, samples_ms: list[float]) -> LatencyStats:
    return LatencyStats(
        label=label,
        n=len(samples_ms),
        p50_ms=_percentile(samples_ms, 50),
        p95_ms=_percentile(samples_ms, 95),
        min_ms=min(samples_ms),
        max_ms=max(samples_ms),
    )


async def _timed_get(client: httpx.AsyncClient, path: str, params: dict) -> float:
    start = time.perf_counter()
    response = await client.get(path, params=params)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.raise_for_status()
    return elapsed_ms


async def bench_niches_cold(client: httpx.AsyncClient, salt: int) -> LatencyStats:
    samples = []
    for i in range(COLD_SAMPLES):
        params = {"limit": 20, "offset": salt + i}
        samples.append(await _timed_get(client, "/api/niches", params))
    return summarize("niches: cold (unique offset, cache miss)", samples)


async def bench_niches_warm(client: httpx.AsyncClient) -> LatencyStats:
    await _timed_get(client, "/api/niches", WARM_NICHES_PARAMS)  # warm the cache
    samples = [
        await _timed_get(client, "/api/niches", WARM_NICHES_PARAMS)
        for _ in range(WARM_SAMPLES)
    ]
    return summarize("niches: warm (repeated, cache hit)", samples)


async def bench_search_cold(client: httpx.AsyncClient, salt: str) -> LatencyStats:
    # The very first call to /api/search in a freshly started process
    # pays a one-time cost to load the sentence-transformers model into
    # memory (see embed_query's _get_model()) -- that's a process
    # lifetime cost, not something caching affects, so it would swamp
    # every other number here if left in. Burn it off on a throwaway
    # query (its own cache entries are never touched by the real
    # samples below) before the timed loop starts.
    await _timed_get(client, "/api/search", {"q": f"warmup {salt}", "limit": 1})

    samples = []
    for i in range(COLD_SAMPLES):
        base = REALISTIC_QUERIES[i % len(REALISTIC_QUERIES)]
        query = f"{base} {salt}-{i}"
        samples.append(
            await _timed_get(client, "/api/search", {"q": query, "limit": 10})
        )
    return summarize("search: cold (unique query, both caches miss)", samples)


async def bench_search_warm_embedding_only(client: httpx.AsyncClient, salt: str) -> LatencyStats:
    # One query, held fixed, but a different `limit` on every call so
    # the response-cache key (q + limit) never repeats while the
    # embedding-cache key (q alone) always does.
    query = f"warm embedding query {salt}"
    await _timed_get(client, "/api/search", {"q": query, "limit": 5})  # warm the embed cache
    samples = [
        await _timed_get(client, "/api/search", {"q": query, "limit": 5 + (i % 20)})
        for i in range(WARM_SAMPLES)
    ]
    return summarize("search: warm embedding only (response cache still misses)", samples)


async def bench_search_warm_full(client: httpx.AsyncClient) -> LatencyStats:
    params = {"q": WARM_SEARCH_QUERY, "limit": 10}
    await _timed_get(client, "/api/search", params)  # warm both caches
    samples = [await _timed_get(client, "/api/search", params) for _ in range(WARM_SAMPLES)]
    return summarize("search: warm full response (cache hit)", samples)


async def main() -> int:
    salt = uuid.uuid4().hex[:10]
    offset_salt = int(time.time())

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        try:
            health = await client.get("/api/health")
            health.raise_for_status()
        except httpx.HTTPError as exc:
            print(
                f"Could not reach {BASE_URL} ({exc}). This script expects a "
                "running stack -- see the module docstring for the "
                "precondition (make up / make migrate / make "
                "bootstrap-sample / make cluster)."
            )
            return 1

        results = [
            await bench_niches_cold(client, offset_salt),
            await bench_niches_warm(client),
            await bench_search_cold(client, salt),
            await bench_search_warm_embedding_only(client, salt),
            await bench_search_warm_full(client),
        ]

    print(f"\nLatency benchmark against {BASE_URL}")
    print(
        "Measured on the corpus currently loaded -- see this script's "
        "docstring for what that does and doesn't prove.\n"
    )
    for stats in results:
        print(stats.format_row())
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(asyncio.run(main()))
