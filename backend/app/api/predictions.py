"""Breakout-prediction feed.

The predictions table is populated by ml/'s training pipeline, which
as of this phase has not been run against real bootstrap data (see
ml/README.md) — so on a fresh install this legitimately returns an
empty list. That is the correct behavior, not a bug: nothing here
fabricates a score for a video that has none.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction, Video
from app.db.session import get_session

router = APIRouter()

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@router.get("/api/predictions/breakouts")
async def get_breakouts(
    limit: int = DEFAULT_LIMIT,
    session: AsyncSession = Depends(get_session),
) -> dict:
    limit = max(1, min(limit, MAX_LIMIT))

    stmt = (
        select(Prediction, Video)
        .join(Video, Video.id == Prediction.video_id)
        .order_by(Prediction.breakout_probability.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)

    items = [
        {
            "video_id": video.id,
            "title": video.title,
            "channel_id": video.channel_id,
            "view_count": video.view_count,
            "published_at": video.published_at.isoformat() if video.published_at else None,
            "breakout_probability": prediction.breakout_probability,
            "model_version": prediction.model_version,
        }
        for prediction, video in result.all()
    ]
    return {"items": items}
