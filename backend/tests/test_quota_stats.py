"""Tests for the quota-log aggregation math. Plain dicts, no database."""

from __future__ import annotations

from datetime import date

from app.services.quota_stats import aggregate_quota_rows


def _row(day, strategy_label, endpoint, cache_hit, units):
    return {
        "day": day,
        "strategy_label": strategy_label,
        "endpoint": endpoint,
        "cache_hit": cache_hit,
        "units": units,
    }


DAY = date(2026, 8, 28)


def test_empty_ledger_returns_empty_list():
    assert aggregate_quota_rows([]) == []


def test_separates_spent_from_reconstructed_saved():
    rows = [
        _row(DAY, "optimized", "channels.list", False, 1),
        _row(DAY, "optimized", "channels.list", False, 1),
        # A cache hit is logged with units=0 (the real cost); "saved"
        # is reconstructed from UNIT_COSTS["search.list"], not read
        # off this row's own units field.
        _row(DAY, "optimized", "search.list", True, 0),
    ]
    result = aggregate_quota_rows(rows)
    assert result == [
        {
            "day": "2026-08-28",
            "strategy_label": "optimized",
            "units_spent": 2,
            "calls_uncached": 2,
            "calls_cached": 1,
            "units_saved": 100,
        }
    ]


def test_groups_by_day_and_strategy_label_separately():
    rows = [
        _row(DAY, "optimized", "videos.list", False, 1),
        _row(DAY, "naive", "search.list", False, 100),
    ]
    result = aggregate_quota_rows(rows)
    assert {r["strategy_label"] for r in result} == {"optimized", "naive"}
    assert len(result) == 2


def test_sorted_by_day_then_strategy_label():
    rows = [
        _row(date(2026, 8, 29), "optimized", "videos.list", False, 1),
        _row(date(2026, 8, 28), "naive", "videos.list", False, 1),
        _row(date(2026, 8, 28), "optimized", "videos.list", False, 1),
    ]
    result = aggregate_quota_rows(rows)
    assert [(r["day"], r["strategy_label"]) for r in result] == [
        ("2026-08-28", "naive"),
        ("2026-08-28", "optimized"),
        ("2026-08-29", "optimized"),
    ]


def test_unknown_endpoint_saves_zero_rather_than_raising():
    rows = [_row(DAY, "optimized", "not.a.real.endpoint", True, 0)]
    result = aggregate_quota_rows(rows)
    assert result[0]["units_saved"] == 0
