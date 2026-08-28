"""Quota-ledger stats, backing the quota-savings claim in docs/quota-math.md.

See app/services/quota_stats.py for the aggregation math and why
"units saved" has to be reconstructed rather than read directly off
cache-hit rows.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from app.db.models import ApiQuotaLog
from app.db.session import get_session
from app.services.quota_stats import aggregate_quota_rows

router = APIRouter()


@router.get("/api/stats/quota")
async def get_quota_stats(session: AsyncSession = Depends(get_session)) -> dict:
    stmt = select(
        func.date(ApiQuotaLog.created_at).label("day"),
        ApiQuotaLog.strategy_label,
        ApiQuotaLog.endpoint,
        ApiQuotaLog.cache_hit,
        ApiQuotaLog.units,
    )
    result = await session.execute(stmt)
    rows = [
        {
            "day": row.day,
            "strategy_label": row.strategy_label,
            "endpoint": row.endpoint,
            "cache_hit": row.cache_hit,
            "units": row.units,
        }
        for row in result.all()
    ]
    # An empty ledger (no bootstrap/refresh has run yet) is a normal,
    # honest state: zero groups, not an error.
    return {"by_day": aggregate_quota_rows(rows)}
