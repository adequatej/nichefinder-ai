"""Keyless sample mode: prove the pipeline end to end without an API key.

Generates deterministic fixture data shaped exactly like YouTube API
responses (12 fake channels across 4 topics, about 300 videos) and runs
it through the same persist path the real bootstrap uses: upserts,
language detection, snapshots, the gates report, and tracked-channel
selection. Gate thresholds are proportionally lower (200 and 10) since
the sample corpus is proportionally smaller.

Run inside the api container with: python -m app.ingest.sample_data
(or `make bootstrap-sample` from the repo root).
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timedelta, timezone

from app.ingest.bootstrap import DbSink, report_gates, select_tracked_channels

# Proportionally scaled-down gates for the ~300 video sample corpus.
SAMPLE_GATE_A_THRESHOLD = 200
SAMPLE_GATE_B_THRESHOLD = 10

# Fixed seed and anchor date so every run generates identical data.
RANDOM_SEED = 20260828
ANCHOR_DATE = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)

VIDEOS_PER_CHANNEL = 25

# Four topics, three channels each. The "language" field drives whether
# titles and descriptions are generated in English or Japanese, which
# exercises the language filter for real.
TOPICS: list[dict] = [
    {
        "name": "demo",
        "channels": [
            ("UCsampledemo0001", "JP Soccer Digest", "en"),
            ("UCsampledemo0002", "Takamado League Weekly", "en"),
            ("UCsampledemo0003", "Inter High Football EN", "en"),
        ],
    },
    {
        "name": "baseball",
        "channels": [
            ("UCsamplebase0001", "Koshien Chronicles", "en"),
            ("UCsamplebase0002", "Diamond Japan EN", "en"),
            # A Japanese-language channel, so the filter has real work.
            ("UCsamplebase0003", "Kokoyakyu Sokuho", "ja"),
        ],
    },
    {
        "name": "us_youth",
        "channels": [
            ("UCsampleusyt0001", "US Youth Soccer Hub", "en"),
            ("UCsampleusyt0002", "Academy Prospects USA", "en"),
            ("UCsampleusyt0003", "High School Kicks TV", "en"),
        ],
    },
    {
        "name": "generic",
        "channels": [
            ("UCsamplegen00001", "Goal Machine Highlights", "en"),
            ("UCsamplegen00002", "Matchday Replays", "en"),
            ("UCsamplegen00003", "Football Clips Daily", "en"),
        ],
    },
]

DEMO_TEAMS = [
    "Seiwa Gakuen",
    "Aomori Yamada",
    "Funabashi",
    "Ryutsu Keizai Kashiwa",
    "Higashi Fukuoka",
    "Maebashi Ikuei",
    "Teikyo Nagaoka",
    "Shizuoka Gakuen",
]

BASEBALL_TEAMS = ["Osaka Toin", "Sendai Ikuei", "Yokohama", "Chiben Wakayama"]
US_TEAMS = ["Dallas Texans", "Solar SC", "St. Benedict's Prep", "IMG Academy"]
GENERIC_MATCHES = [
    "Arsenal vs Chelsea",
    "Real Madrid vs Barcelona",
    "Bayern vs Dortmund",
    "Inter vs Milan",
]

# View count ranges per topic. Generic highlight channels are the
# oversupplied contrast, so they get the biggest numbers.
VIEW_RANGES = {
    "demo": (800, 40000),
    "baseball": (2000, 90000),
    "us_youth": (500, 25000),
    "generic": (20000, 900000),
}


def _demo_title(rng: random.Random, index: int) -> str:
    home, away = rng.sample(DEMO_TEAMS, 2)
    templates = [
        f"{home} vs {away} | Japanese High School Soccer Highlights",
        f"Inter High Semifinal: {home} vs {away}",
        f"Prince Takamado Trophy Matchday {index + 1}: {home} vs {away}",
        f"{home} Top Goals This Season | Japanese High School Soccer",
    ]
    return templates[index % len(templates)]


def _baseball_title(rng: random.Random, index: int, language: str) -> str:
    home, away = rng.sample(BASEBALL_TEAMS, 2)
    if language == "ja":
        return f"高校野球 準々決勝 {index + 1}日目 ハイライト"
    return f"Koshien Highlights: {home} vs {away} Full Recap"


def _us_title(rng: random.Random, index: int) -> str:
    home, away = rng.sample(US_TEAMS, 2)
    return f"US Youth Soccer Showcase: {home} vs {away} Highlights"


def _generic_title(rng: random.Random, index: int) -> str:
    match = rng.choice(GENERIC_MATCHES)
    return f"{match} {rng.randint(0, 4)}-{rng.randint(0, 4)} All Goals and Highlights"


def _title_for(topic: str, language: str, rng: random.Random, index: int) -> str:
    if topic == "demo":
        return _demo_title(rng, index)
    if topic == "baseball":
        return _baseball_title(rng, index, language)
    if topic == "us_youth":
        return _us_title(rng, index)
    return _generic_title(rng, index)


def _description_for(topic: str, language: str, title: str) -> str:
    if language == "ja":
        return "全国高等学校野球選手権大会のハイライト映像です。"
    return f"Full highlights and analysis. {title}."


def generate_channels() -> list[dict]:
    """Build channels.list-shaped items for the 12 sample channels."""
    rng = random.Random(RANDOM_SEED)
    items: list[dict] = []
    for topic in TOPICS:
        for channel_id, title, language in topic["channels"]:
            # One channel hides its subscriber count so the subs_hidden
            # path gets exercised end to end.
            hidden = channel_id == "UCsampleusyt0003"
            stats = {
                "hiddenSubscriberCount": hidden,
                "videoCount": str(VIDEOS_PER_CHANNEL),
                "viewCount": str(rng.randint(100000, 20000000)),
            }
            if not hidden:
                stats["subscriberCount"] = str(rng.randint(1000, 500000))
            items.append(
                {
                    "kind": "youtube#channel",
                    "id": channel_id,
                    "snippet": {
                        "title": title,
                        "description": f"Sample channel for the {topic['name']} topic.",
                        "publishedAt": "2022-01-15T00:00:00Z",
                        "country": "JP" if language == "ja" else "US",
                    },
                    "statistics": stats,
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": "UU" + channel_id[2:]}
                    },
                }
            )
    return items


def generate_videos() -> list[dict]:
    """Build videos.list-shaped items, about 300, spread over 24 months."""
    rng = random.Random(RANDOM_SEED + 1)
    items: list[dict] = []
    video_number = 0
    for topic in TOPICS:
        low, high = VIEW_RANGES[topic["name"]]
        for channel_id, _channel_title, language in topic["channels"]:
            for index in range(VIDEOS_PER_CHANNEL):
                video_number += 1
                title = _title_for(topic["name"], language, rng, index)
                published = ANCHOR_DATE - timedelta(
                    days=rng.randint(0, 729), hours=rng.randint(0, 23)
                )
                views = rng.randint(low, high)
                # Roughly one video in ten is a Short.
                if rng.random() < 0.1:
                    duration = f"PT{rng.randint(20, 59)}S"
                else:
                    duration = f"PT{rng.randint(4, 14)}M{rng.randint(0, 59)}S"
                item = {
                    "kind": "youtube#video",
                    "id": f"sv{video_number:09d}",
                    "snippet": {
                        "title": title,
                        "description": _description_for(
                            topic["name"], language, title
                        ),
                        "channelId": channel_id,
                        "publishedAt": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "categoryId": "17",
                    },
                    "statistics": {
                        "viewCount": str(views),
                        "likeCount": str(max(1, views // 40)),
                        "commentCount": str(max(0, views // 400)),
                    },
                    "contentDetails": {"duration": duration},
                }
                # Some tags on a minority of videos, mirroring reality
                # where most videos have none.
                if rng.random() < 0.2:
                    item["snippet"]["tags"] = ["soccer", "highlights"]
                # A few live-stream recordings.
                if rng.random() < 0.05:
                    item["liveStreamingDetails"] = {
                        "actualStartTime": item["snippet"]["publishedAt"]
                    }
                items.append(item)
    return items


async def main() -> int:
    from app.db.session import SessionLocal

    sink = DbSink(SessionLocal)
    channels = generate_channels()
    videos = generate_videos()
    print(f"Generated {len(channels)} sample channels and {len(videos)} videos.")

    # Same persist path as the real bootstrap: channel upserts plus
    # snapshots, then video upserts with language detection.
    await sink.save_channels(channels)
    await sink.save_videos(videos)

    video_rows = await sink.video_rows()
    report_gates(video_rows, SAMPLE_GATE_A_THRESHOLD, SAMPLE_GATE_B_THRESHOLD)
    tracked = select_tracked_channels(video_rows)
    await sink.mark_tracked(tracked)
    print(f"Marked {len(tracked)} channels as tracked.")
    print("Sample bootstrap complete. No API quota was used.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
