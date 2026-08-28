"""Tests for the pure transform functions in persist.py. No database."""

from __future__ import annotations

from datetime import date, timezone

import pytest

from app.ingest.persist import (
    channel_row,
    channel_snapshot_row,
    parse_duration_seconds,
    parse_timestamp,
    video_row,
    video_snapshot_row,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("PT8M30S", 510),
        ("PT1H2M3S", 3723),
        ("PT45S", 45),
        ("PT2H", 7200),
        ("P1DT2H", 93600),
        ("P1W", 604800),
        ("P0D", 0),
        ("PT0S", 0),
        (None, None),
        ("", None),
        ("garbage", None),
        ("8M30S", None),
    ],
)
def test_parse_duration_seconds(value, expected):
    assert parse_duration_seconds(value) == expected


def test_parse_timestamp_handles_z_suffix_and_bad_input():
    parsed = parse_timestamp("2026-08-01T12:00:00Z")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.astimezone(timezone.utc).hour == 12
    assert parse_timestamp(None) is None
    assert parse_timestamp("not a date") is None


def _video_item(**overrides) -> dict:
    item = {
        "id": "vid00000001",
        "snippet": {
            "title": "Seiwa Gakuen vs Aomori Yamada Highlights",
            "description": "Japanese high school soccer match highlights.",
            "channelId": "UCabc123",
            "publishedAt": "2026-08-01T12:00:00Z",
            "categoryId": "17",
        },
        "statistics": {"viewCount": "1234", "likeCount": "56", "commentCount": "7"},
        "contentDetails": {"duration": "PT8M30S"},
    }
    item.update(overrides)
    return item


def test_video_row_basic_fields():
    row = video_row(_video_item(), "en")
    assert row["id"] == "vid00000001"
    assert row["channel_id"] == "UCabc123"
    assert row["duration_seconds"] == 510
    assert row["detected_language"] == "en"
    assert row["is_short"] is False
    assert row["is_live_vod"] is False
    assert row["view_count"] == 1234
    assert row["like_count"] == 56
    assert row["comment_count"] == 7
    # Most videos have no tags; missing stays None, not [].
    assert row["tags"] is None


def test_video_row_short_detection_boundary():
    assert video_row(_video_item(contentDetails={"duration": "PT45S"}), "en")["is_short"]
    assert video_row(_video_item(contentDetails={"duration": "PT61S"}), "en")["is_short"]
    assert not video_row(_video_item(contentDetails={"duration": "PT62S"}), "en")["is_short"]
    # A zero duration (live placeholder) is not a Short.
    assert not video_row(_video_item(contentDetails={"duration": "P0D"}), "en")["is_short"]


def test_video_row_live_vod_flag():
    item = _video_item()
    item["liveStreamingDetails"] = {"actualStartTime": "2026-08-01T12:00:00Z"}
    assert video_row(item, "en")["is_live_vod"] is True


def test_video_row_missing_statistics_and_duration():
    item = _video_item()
    del item["statistics"]
    del item["contentDetails"]
    row = video_row(item, "en")
    assert row["view_count"] is None
    assert row["like_count"] is None
    assert row["comment_count"] is None
    assert row["duration_seconds"] is None
    assert row["is_short"] is False


def test_video_row_keeps_tags_when_present():
    item = _video_item()
    item["snippet"]["tags"] = ["soccer", "japan"]
    assert video_row(item, "en")["tags"] == ["soccer", "japan"]


def _channel_item(**stats_overrides) -> dict:
    stats = {
        "subscriberCount": "60000",
        "hiddenSubscriberCount": False,
        "videoCount": "150",
        "viewCount": "9000000",
    }
    stats.update(stats_overrides)
    return {
        "id": "UCabc123",
        "snippet": {
            "title": "JP Soccer Digest",
            "description": "English coverage of Japanese high school soccer.",
            "publishedAt": "2020-01-15T00:00:00Z",
            "country": "US",
        },
        "statistics": stats,
        "contentDetails": {"relatedPlaylists": {"uploads": "UUabc123"}},
    }


def test_channel_row_basic_fields():
    row = channel_row(_channel_item())
    assert row["id"] == "UCabc123"
    assert row["uploads_playlist_id"] == "UUabc123"
    assert row["subscriber_count"] == 60000
    assert row["subs_hidden"] is False
    assert row["video_count"] == 150
    assert row["view_count"] == 9000000
    assert row["country"] == "US"


def test_channel_row_hidden_subscribers():
    row = channel_row(_channel_item(hiddenSubscriberCount=True))
    # Hidden counts become None plus a flag, never zero.
    assert row["subscriber_count"] is None
    assert row["subs_hidden"] is True


def test_channel_row_missing_statistics():
    item = _channel_item()
    del item["statistics"]
    row = channel_row(item)
    assert row["subscriber_count"] is None
    assert row["subs_hidden"] is False
    assert row["video_count"] is None


def test_snapshot_rows():
    snapshot_date = date(2026, 8, 28)
    vrow = video_snapshot_row(_video_item(), snapshot_date)
    assert vrow == {
        "video_id": "vid00000001",
        "snapshot_date": snapshot_date,
        "view_count": 1234,
        "like_count": 56,
        "comment_count": 7,
    }
    crow = channel_snapshot_row(_channel_item(hiddenSubscriberCount=True), snapshot_date)
    assert crow["channel_id"] == "UCabc123"
    assert crow["snapshot_date"] == snapshot_date
    assert crow["subscriber_count"] is None
    assert crow["view_count"] == 9000000
