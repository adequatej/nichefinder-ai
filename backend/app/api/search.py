"""Free-text video search: embed the query, then nearest-neighbor scan.

The embedding step is the expensive one (a sentence-transformers
forward pass), not the pgvector scan that follows it, so the query
embedding itself is cached separately from the final response body —
a repeated or popular query skips `embed_query` entirely even if the
underlying video corpus has changed enough that the response cache
key would otherwise still be a hit anyway. Both caches are Layer 2:
computed results of our own, not raw YouTube payloads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.videos import DEFAULT_SIMILAR_LIMIT, MAX_SIMILAR_LIMIT, nearest_neighbor_videos
from app.db.session import get_session
from app.services.api_cache import (
    ApiResponseCache,
    TTL_SEARCH,
    TTL_SEARCH_EMBEDDING,
    build_key,
    get_api_cache,
)
from app.services.embeddings import embed_query

router = APIRouter()


async def _embed_query_cached(cache: ApiResponseCache, query: str) -> list[float]:
    key = build_key("search:embed", {"q": query})
    cached = await cache.get_json(key)
    if cached is not None:
        return cached
    vector = embed_query(query)
    await cache.set_json(key, vector, TTL_SEARCH_EMBEDDING)
    return vector


@router.get("/api/search")
async def search_videos(
    q: str = "",
    limit: int = DEFAULT_SIMILAR_LIMIT,
    session: AsyncSession = Depends(get_session),
    cache: ApiResponseCache = Depends(get_api_cache),
) -> dict:
    query = q.strip()
    if not query:
        raise HTTPException(status_code=400, detail="q is required")
    limit = max(1, min(limit, MAX_SIMILAR_LIMIT))

    response_key = build_key("search", {"q": query, "limit": limit})
    cached_response = await cache.get_json(response_key)
    if cached_response is not None:
        return cached_response

    vector = await _embed_query_cached(cache, query)
    items = await nearest_neighbor_videos(session, vector, limit)

    response = {"query": query, "items": items}
    await cache.set_json(response_key, response, TTL_SEARCH)
    return response
