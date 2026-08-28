# YouTube API quota math

The YouTube Data API gives every project 10,000 free quota units per day. Different calls cost very different amounts, so the whole ingestion design comes down to one rule: avoid search, batch everything else.

## What each call costs

| Call | Cost | What you get back |
|---|---|---|
| `search.list` | 100 units | Up to 50 search results (videos or channels) |
| `channels.list` | 1 unit | Full details for up to 50 channels in one call |
| `videos.list` | 1 unit | Full details and statistics for up to 50 videos in one call |
| `playlistItems.list` | 1 unit | One page (up to 50) of a channel's uploads |

The gap matters: one search costs as much as fetching details for 5,000 videos. So search is used exactly once per seed keyword, to discover channels. Everything after that flows through each channel's uploads playlist at 1 unit per page.

## One-time bootstrap budget

The bootstrap collects the initial corpus. Rough budget for about 30 seed keywords and 200 to 250 channels:

| Step | Calls | Units |
|---|---|---|
| Seed searches | 30 searches | 3,000 |
| Channel details | 250 channels / 50 per call | 5 |
| Uploads pages | about 2 to 3 pages per channel | 500 to 750 |
| Video details | about 12,000 videos / 50 per call | 240 |
| Total | | about 3,750 to 4,000 |

That fits inside one free day with room to spare. If the corpus needs more channels to pass its size gates, the bootstrap resumes the next day, and every call it already made is answered from the Redis response cache at a cost of 0 units.

## Daily refresh budget

The daily job tracks 100 channels:

| Step | Calls | Units |
|---|---|---|
| Channel stats | 100 channels / 50 per call | 2 |
| New-upload check | 1 uploads page per channel | 100 |
| Stats for recent videos | a few hundred videos / 50 per call | 5 to 20 |
| Total | | about 110 to 125 |

Just over 1 percent of the daily allowance. The expensive part is the new-upload check, and it is already as cheap as the API allows: there is no way to ask "what did these 100 channels upload since yesterday" in one call.

## The naive alternative, for comparison

A straightforward implementation of the same daily job would run one search per tracked topic to find new videos, and fetch video statistics one call per video:

| Strategy | Daily units |
|---|---|
| Naive: search per topic plus one call per video | several thousand |
| This design: playlist diffing plus 50-id batching | about 110 to 125 |

The benchmark script `benchmarks/bench_quota.py` runs both strategies against the real quota ledger and reports the measured saving. The saving comes from the architecture, not from caching: even with every cache empty, the optimized strategy costs a small fraction of the naive one.

## Where the ledger lives

Every API call, cached or not, writes a row to the `api_quota_log` table: which endpoint, how many units, whether it was a cache hit, and which run and strategy it belonged to. All quota numbers quoted in this repo come from summing that table, never from estimates.
