"""Minimal recorded-style YouTube API response fixtures."""

from __future__ import annotations


def video_item(video_id: str) -> dict:
    return {
        "kind": "youtube#video",
        "id": video_id,
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


def videos_response(video_ids: list[str]) -> dict:
    return {
        "kind": "youtube#videoListResponse",
        "items": [video_item(vid) for vid in video_ids],
        "pageInfo": {"totalResults": len(video_ids), "resultsPerPage": 50},
    }


def channel_item(channel_id: str) -> dict:
    return {
        "kind": "youtube#channel",
        "id": channel_id,
        "snippet": {
            "title": "JP Soccer Digest",
            "description": "English coverage of Japanese high school soccer.",
            "publishedAt": "2020-01-15T00:00:00Z",
            "country": "US",
        },
        "statistics": {
            "subscriberCount": "60000",
            "hiddenSubscriberCount": False,
            "videoCount": "150",
            "viewCount": "9000000",
        },
        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + channel_id[2:]}},
    }


def channels_response(channel_ids: list[str]) -> dict:
    return {
        "kind": "youtube#channelListResponse",
        "items": [channel_item(cid) for cid in channel_ids],
        "pageInfo": {"totalResults": len(channel_ids), "resultsPerPage": 50},
    }


def search_response() -> dict:
    return {
        "kind": "youtube#searchListResponse",
        "items": [
            {
                "kind": "youtube#searchResult",
                "id": {"kind": "youtube#video", "videoId": "vid00000001"},
                "snippet": {
                    "title": "Japanese High School Soccer Final",
                    "channelId": "UCabc123",
                },
            }
        ],
        "pageInfo": {"totalResults": 1, "resultsPerPage": 50},
    }


def playlist_items_response(playlist_id: str) -> dict:
    return {
        "kind": "youtube#playlistItemListResponse",
        "items": [
            {
                "kind": "youtube#playlistItem",
                "contentDetails": {
                    "videoId": "vid00000001",
                    "videoPublishedAt": "2026-08-01T12:00:00Z",
                },
            }
        ],
        "nextPageToken": "CAUQAA",
        "pageInfo": {"totalResults": 120, "resultsPerPage": 50},
    }
