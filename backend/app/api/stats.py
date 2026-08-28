"""Quota-ledger stats, backing the quota-savings claim in docs/quota-math.md.

See app/services/quota_stats.py for the aggregation math and why
"units saved" has to be reconstructed rather than read directly off
cache-hit rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiQuotaLog
from app.db.session import get_session
from app.services.quota_stats import aggregate_quota_rows

router = APIRouter()

DEFAULT_WINDOW_DAYS = 30


@router.get("/api/stats/quota")
async def get_quota_stats(
    days: int = DEFAULT_WINDOW_DAYS,
    session: AsyncSession = Depends(get_session),
) -> dict:
    days = max(1, days)
    # Bounded window so this scans ix_api_quota_log_created_at instead
    # of the whole table, which only grows (roughly 100 rows/day from
    # the daily refresh, per docs/quota-math.md) and never shrinks.
    since = datetime.now(timezone.utc) - timedelta(days=days)

    stmt = select(
        func.date(ApiQuotaLog.created_at).label("day"),
        ApiQuotaLog.strategy_label,
        ApiQuotaLog.endpoint,
        ApiQuotaLog.cache_hit,
        ApiQuotaLog.units,
    ).where(ApiQuotaLog.created_at >= since)
    result = await session.execute(stmt)
    rows = [
        {
            # func.date() returns a DATE; normalize defensively in case a
            # driver ever hands back a datetime instead.
            "day": row.day.date() if isinstance(row.day, datetime) else row.day,
            "strategy_label": row.strategy_label,
            "endpoint": row.endpoint,
            "cache_hit": row.cache_hit,
            "units": row.units,
        }
        for row in result.all()
    ]
    # An empty ledger (no bootstrap/refresh has run yet, or nothing in
    # the window) is a normal, honest state: zero groups, not an error.
    return {"window_days": days, "by_day": aggregate_quota_rows(rows)}
