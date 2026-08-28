"""Worker entry point: run the daily refresh on a schedule.

APScheduler fires run_daily_refresh every day at 06:00 local time.
Without an API key the run is skipped with a clear log line instead of
crashing, so the worker container is safe to run in keyless setups.

Run inside the worker container with: python -m app.ingest.scheduler
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.ingest import persist
from app.ingest.snapshot import run_daily_refresh
from app.services.youtube import YouTubeClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nichefinder.scheduler")

REFRESH_HOUR = 6
REFRESH_MINUTE = 0


async def scheduled_refresh() -> None:
    """One scheduled run: build a client, refresh, log the stats."""
    from redis.asyncio import Redis

    from app.db.session import SessionLocal
    from app.services.cache import ResponseCache
    from app.services.quota import DbQuotaRecorder

    settings = get_settings()
    if not settings.youtube_api_key:
        logger.warning(
            "YOUTUBE_API_KEY is empty. Skipping the daily refresh. "
            "Set the key in .env to enable it."
        )
        return

    redis = Redis.from_url(settings.redis_url)
    cache = ResponseCache(redis, cache_enabled=settings.cache_enabled)
    recorder = DbQuotaRecorder(SessionLocal)
    run_label = f"daily-{persist.today_utc().isoformat()}"
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            client = YouTubeClient(
                api_key=settings.youtube_api_key,
                http=http,
                cache=cache,
                quota=recorder,
                run_label=run_label,
                strategy_label="optimized",
            )
            stats = await run_daily_refresh(SessionLocal, client)
        logger.info("Daily refresh done: %s", stats)
    except Exception:
        logger.exception("Daily refresh failed. Next run is unaffected.")
    finally:
        await redis.aclose()


async def main() -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        scheduled_refresh,
        CronTrigger(hour=REFRESH_HOUR, minute=REFRESH_MINUTE),
        id="daily_refresh",
    )
    scheduler.start()
    logger.info(
        "Scheduler started. Daily refresh runs at %02d:%02d local time.",
        REFRESH_HOUR,
        REFRESH_MINUTE,
    )
    # Keep the process alive forever; the scheduler runs in this loop.
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
