"""Aggregation math for /api/stats/quota, kept pure so it's testable
without a database.

youtube.py's `_record` (see its call sites) logs a cache-hit call with
units=0 — the honest ledger value, since a cache hit truly costs zero
quota. That means "units saved by caching" is not a column in the
table; it has to be reconstructed by re-applying quota.py's own fixed
per-endpoint cost table (UNIT_COSTS) to each cache-hit row's endpoint.
That reconstruction is exact, not an estimate, because the cost table
is a fixed constant per endpoint, not something that varies call to
call.

docs/quota-math.md is explicit that the quota-savings story is about
architecture (search-once-then-batch) rather than caching — caching
makes retries free, it isn't the headline number. So this module keeps
"units actually spent" (real, cache-hit rows already contribute 0) and
"units a cache hit avoided re-spending" (reconstructed) as separate
fields rather than one blended "savings" figure.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.services.quota import UNIT_COSTS


def aggregate_quota_rows(rows: list[dict]) -> list[dict]:
    """Group quota-log rows by (day, strategy_label).

    Each row needs: day (a date), strategy_label (str | None), endpoint
    (str), cache_hit (bool), units (int, the value actually logged).

    Returns one dict per (day, strategy_label) group, sorted by day
    then strategy_label, with:
      units_spent      - sum of `units` on non-cache-hit rows (real cost)
      calls_uncached    - count of non-cache-hit rows
      calls_cached      - count of cache-hit rows
      units_saved       - sum of UNIT_COSTS[endpoint] over cache-hit rows
                          (reconstructed; those rows themselves log 0)
    """
    groups: dict[tuple[date, str | None], dict] = defaultdict(
        lambda: {"units_spent": 0, "calls_uncached": 0, "calls_cached": 0, "units_saved": 0}
    )
    for row in rows:
        key = (row["day"], row.get("strategy_label"))
        bucket = groups[key]
        if row["cache_hit"]:
            bucket["calls_cached"] += 1
            bucket["units_saved"] += UNIT_COSTS.get(row["endpoint"], 0)
        else:
            bucket["calls_uncached"] += 1
            bucket["units_spent"] += row["units"]

    return [
        {"day": day.isoformat(), "strategy_label": strategy_label, **stats}
        for (day, strategy_label), stats in sorted(
            groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")
        )
    ]
