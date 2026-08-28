"""Quota accounting for YouTube Data API calls.

Every API call, cached or not, is recorded so the ledger can answer
"how many units did this job really cost" and back the quota benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Unit costs per the YouTube Data API v3 quota table.
UNIT_COSTS: dict[str, int] = {
    "search.list": 100,
    "channels.list": 1,
    "videos.list": 1,
    "playlistItems.list": 1,
}


def units_for(endpoint: str) -> int:
    """Return the quota cost of one call to the given endpoint."""
    try:
        return UNIT_COSTS[endpoint]
    except KeyError:
        raise ValueError(f"Unknown endpoint: {endpoint}") from None


class QuotaRecorder(Protocol):
    """Anything that can record one quota ledger entry."""

    async def record(
        self,
        endpoint: str,
        units: int,
        cache_hit: bool,
        run_label: str | None = None,
        strategy_label: str | None = None,
    ) -> None: ...


class DbQuotaRecorder:
    """Writes ledger rows to the api_quota_log table.

    Takes an async session factory (for example SessionLocal) so each
    record gets its own short-lived session and commit.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        endpoint: str,
        units: int,
        cache_hit: bool,
        run_label: str | None = None,
        strategy_label: str | None = None,
    ) -> None:
        from app.db.models import ApiQuotaLog

        async with self._session_factory() as session:
            session.add(
                ApiQuotaLog(
                    endpoint=endpoint,
                    units=units,
                    cache_hit=cache_hit,
                    run_label=run_label,
                    strategy_label=strategy_label,
                )
            )
            await session.commit()


@dataclass
class QuotaEntry:
    endpoint: str
    units: int
    cache_hit: bool
    run_label: str | None = None
    strategy_label: str | None = None


@dataclass
class ListQuotaRecorder:
    """In-memory recorder for tests. No database needed."""

    entries: list[QuotaEntry] = field(default_factory=list)

    async def record(
        self,
        endpoint: str,
        units: int,
        cache_hit: bool,
        run_label: str | None = None,
        strategy_label: str | None = None,
    ) -> None:
        self.entries.append(
            QuotaEntry(endpoint, units, cache_hit, run_label, strategy_label)
        )

    @property
    def total_units(self) -> int:
        return sum(entry.units for entry in self.entries)
