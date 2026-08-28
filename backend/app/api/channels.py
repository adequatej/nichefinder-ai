"""Channel detail endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Channel, Niche
from app.db.session import get_session

router = APIRouter()


@router.get("/api/channels/{channel_id}")
async def get_channel(channel_id: str, session: AsyncSession = Depends(get_session)) -> dict:
    channel = await session.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    niche = await session.get(Niche, channel.niche_id) if channel.niche_id else None

    return {
        "id": channel.id,
        "title": channel.title,
        "description": channel.description,
        "custom_url": channel.custom_url,
        "country": channel.country,
        "published_at": channel.published_at.isoformat() if channel.published_at else None,
        "subscriber_count": channel.subscriber_count,
        # True when the channel hides its subscriber count in the API;
        # a None/0 subscriber_count in that case is not "no subscribers."
        "subs_hidden": channel.subs_hidden,
        "video_count": channel.video_count,
        "view_count": channel.view_count,
        "is_tracked": channel.is_tracked,
        "niche": (
            {"id": niche.id, "label": niche.label, "opportunity_score": niche.opportunity_score}
            if niche is not None
            else None
        ),
    }
