import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session

router = APIRouter()


@router.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    db_ok = False
    redis_ok = False

    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        client = aioredis.from_url(get_settings().redis_url)
        redis_ok = await client.ping()
        await client.aclose()
    except Exception:
        pass

    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": db_ok,
        "redis": bool(redis_ok),
    }
