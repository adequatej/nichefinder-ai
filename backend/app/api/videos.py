"""Nearest-neighbor video lookups by embedding cosine distance.

Shared with app/api/search.py, which builds a query vector from free
text and calls the same nearest_neighbor_videos helper this endpoint
uses to compare one video's stored embedding against every other.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Video, VideoEmbedding
from app.db.session import get_session
from app.services.api_cache import ApiResponseCache, TTL_SIMILAR, build_key, get_api_cache

router = APIRouter()

DEFAULT_SIMILAR_LIMIT = 10
MAX_SIMILAR_LIMIT = 50


def video_result(video: Video, distance: float) -> dict:
    return {
        "id": video.id,
        "title": video.title,
        "channel_id": video.channel_id,
        "view_count": video.view_count,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        # Cosine distance in [0, 2]; lower is more similar. No thumbnail
        # column exists on Video — the frontend derives a thumbnail URL
        # client-side from the video id.
        "distance": distance,
    }


async def nearest_neighbor_videos(
    session: AsyncSession,
    query_vector: list[float],
    limit: int,
    exclude_video_id: str | None = None,
) -> list[dict]:
    """Videos nearest `query_vector` by cosine distance, most similar first."""
    stmt = (
        select(Video, VideoEmbedding.embedding.cosine_distance(query_vector).label("distance"))
        .join(VideoEmbedding, VideoEmbedding.video_id == Video.id)
        .order_by("distance")
        .limit(limit + (1 if exclude_video_id else 0))
    )
    result = await session.execute(stmt)
    rows = [
        (video, distance) for video, distance in result.all() if video.id != exclude_video_id
    ]
    return [video_result(video, distance) for video, distance in rows[:limit]]


@router.get("/api/videos/{video_id}/similar")
async def get_similar_videos(
    video_id: str,
    limit: int = DEFAULT_SIMILAR_LIMIT,
    session: AsyncSession = Depends(get_session),
    cache: ApiResponseCache = Depends(get_api_cache),
) -> dict:
    limit = max(1, min(limit, MAX_SIMILAR_LIMIT))

    embedding_row = await session.get(VideoEmbedding, video_id)
    if embedding_row is None:
        raise HTTPException(status_code=404, detail="Video or its embedding not found")

    key = build_key("similar", {"video_id": video_id, "limit": limit})
    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    items = await nearest_neighbor_videos(
        session, embedding_row.embedding, limit, exclude_video_id=video_id
    )
    response = {"video_id": video_id, "items": items}
    await cache.set_json(key, response, TTL_SIMILAR)
    return response
