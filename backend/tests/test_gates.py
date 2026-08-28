"""Tests for gate counting, tracked-channel selection, and sample data.

All of these are pure functions over plain dicts, so no database is
needed.
"""

from __future__ import annotations

from app.ingest.bootstrap import (
    collect_channel_ids,
    dedupe_keep_order,
    gate_a_count,
    gate_b_count,
    is_demo_topic_title,
    select_tracked_channels,
)
from app.ingest.langfilter import detect_language
from app.ingest.sample_data import generate_channels, generate_videos
from app.ingest.seeds import DEMO_TOPIC_TERMS, SEED_CHANNEL_IDS, SEED_KEYWORDS


def _row(channel_id, title, language="en", views=100):
    return {
        "id": "vid",
        "channel_id": channel_id,
        "title": title,
        "detected_language": language,
        "view_count": views,
    }


def test_seed_lists_shape():
    assert len(SEED_KEYWORDS) >= 28
    assert "japanese high school soccer" in SEED_KEYWORDS
    assert all(kw == kw.lower() for kw in SEED_KEYWORDS)
    # Filled during the first real bootstrap run, so empty here.
    assert SEED_CHANNEL_IDS == []
    assert all(term == term.lower() for term in DEMO_TOPIC_TERMS)


def test_demo_topic_title_matching():
    assert is_demo_topic_title("Seiwa Gakuen vs Aomori Yamada Highlights")
    assert is_demo_topic_title("Prince Takamado Trophy Matchday 3")
    assert is_demo_topic_title("INTER HIGH Semifinal Recap")
    assert not is_demo_topic_title("Premier League Highlights Week 4")
    assert not is_demo_topic_title("")


def test_gate_counts():
    rows = [
        _row("UC1", "Seiwa Gakuen vs Funabashi", "en"),
        _row("UC1", "Inter High Final", "en"),
        _row("UC2", "Premier League Highlights", "en"),
        # Demo-topic title but not English, so Gate B ignores it.
        _row("UC3", "seiwa gakuen highlights", "ja"),
        _row("UC3", "Random clip", "other"),
    ]
    assert gate_a_count(rows) == 3
    assert gate_b_count(rows) == 2


def test_select_tracked_prefers_demo_channels_then_views():
    rows = [
        # UC_demo2 owns two demo videos, UC_demo1 owns one.
        _row("UC_demo1", "Seiwa Gakuen match", views=10),
        _row("UC_demo2", "Inter High semifinal", views=5),
        _row("UC_demo2", "Prince Takamado Trophy recap", views=5),
        # Big generic channels, no demo content.
        _row("UC_big1", "Premier League Highlights", views=1000000),
        _row("UC_big2", "Champions League goals", views=500000),
        # Non-English channel never qualifies.
        _row("UC_jp", "seiwa gakuen", language="ja", views=999999999),
    ]
    picked = select_tracked_channels(rows, limit=3)
    assert picked == ["UC_demo2", "UC_demo1", "UC_big1"]


def test_select_tracked_respects_limit_and_handles_empty():
    assert select_tracked_channels([], limit=5) == []
    rows = [_row(f"UC{i}", "video", views=i) for i in range(10)]
    assert len(select_tracked_channels(rows, limit=4)) == 4


def test_collect_channel_ids_from_untyped_search():
    response = {
        "items": [
            {"id": {"kind": "youtube#video", "videoId": "v1"},
             "snippet": {"channelId": "UCa"}},
            {"id": {"kind": "youtube#channel", "channelId": "UCb"},
             "snippet": {}},
            {"id": {"kind": "youtube#playlist", "playlistId": "p1"},
             "snippet": {"channelId": "UCa"}},
        ]
    }
    assert collect_channel_ids(response) == ["UCa", "UCb", "UCa"]
    assert dedupe_keep_order(["UCa", "UCb", "UCa"]) == ["UCa", "UCb"]


def test_sample_data_is_deterministic_and_realistic():
    channels = generate_channels()
    videos = generate_videos()
    assert len(channels) == 12
    assert len(videos) == 300
    assert generate_videos() == videos
    assert len({v["id"] for v in videos}) == 300
    # One channel hides its subscriber count.
    hidden = [c for c in channels if c["statistics"].get("hiddenSubscriberCount")]
    assert len(hidden) == 1


def test_sample_data_passes_scaled_gates():
    # Run the generated corpus through the same language filter and
    # gate math the pipeline uses, without a database.
    rows = []
    for item in generate_videos():
        snippet = item["snippet"]
        rows.append(
            {
                "id": item["id"],
                "channel_id": snippet["channelId"],
                "title": snippet["title"],
                "detected_language": detect_language(
                    snippet["title"], snippet["description"]
                ),
                "view_count": int(item["statistics"]["viewCount"]),
            }
        )
    assert gate_a_count(rows) >= 200
    assert gate_b_count(rows) >= 10
    # The Japanese-language channel must not sail through the filter.
    assert gate_a_count(rows) < 300
    # Demo channels get tracked ahead of the big generic channels.
    picked = select_tracked_channels(rows, limit=12)
    assert picked[0].startswith("UCsampledemo")
