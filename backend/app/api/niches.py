"""Niche listing and detail endpoints.

Layer 2 (computed-response) caching applies to the list endpoint only:
it is the one users hit repeatedly (the default landing view), and its
ordering is cheap to recompute but still worth skipping under load.
Detail and videos-in-niche are per-id and lower traffic, so they go
straight to the database.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Niche, Video
from app.db.session import get_session
from app.services.api_cache import ApiResponseCache, TTL_NICHES, build_key, get_api_cache

router = APIRouter()

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


def _niche_summary(niche: Niche) -> dict:
    return {
        "id": niche.id,
        "label": niche.label,
        "top_terms": niche.top_terms,
        "demand_score": niche.demand_score,
        "supply_score": niche.supply_score,
        "opportunity_score": niche.opportunity_score,
        "video_count": niche.video_count,
        "channel_count": niche.channel_count,
    }


def _niche_detail(niche: Niche) -> dict:
    return {**_niche_summary(niche), "score_components": niche.score_components}


def _video_summary(video: Video) -> dict:
    return {
        "id": video.id,
        "title": video.title,
        "channel_id": video.channel_id,
        "view_count": video.view_count,
        "like_count": video.like_count,
        "comment_count": video.comment_count,
        "published_at": video.published_at.isoformat() if video.published_at else None,
        "is_short": video.is_short,
    }


@router.get("/api/niches")
async def list_niches(
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    cache: ApiResponseCache = Depends(get_api_cache),
) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    key = build_key("niches", {"limit": limit, "offset": offset})
    cached = await cache.get_json(key)
    if cached is not None:
        return cached

    # Nulls (ineligible niches, see scoring.py's eligibility floor) sort
    # last: an unscored niche is not "worse," it just has no opinion yet,
    # and it must never be mistaken for a confident zero.
    stmt = (
        select(Niche)
        .order_by(Niche.opportunity_score.desc().nullslast(), Niche.id.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    niches = result.scalars().all()

    response = {"items": [_niche_summary(n) for n in niches], "limit": limit, "offset": offset}
    await cache.set_json(key, response, TTL_NICHES)
    return response


@router.get("/api/niches/{niche_id}")
async def get_niche(niche_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    niche = await session.get(Niche, niche_id)
    if niche is None:
        raise HTTPException(status_code=404, detail="Niche not found")
    return _niche_detail(niche)


@router.get("/api/niches/{niche_id}/videos")
async def get_niche_videos(
    niche_id: int,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    niche = await session.get(Niche, niche_id)
    if niche is None:
        raise HTTPException(status_code=404, detail="Niche not found")

    stmt = (
        select(Video)
        .where(Video.niche_id == niche_id)
        .order_by(Video.published_at.desc().nullslast())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    videos = result.scalars().all()

    return {
        "items": [_video_summary(v) for v in videos],
        "limit": limit,
        "offset": offset,
    }
