"""Standalone P3 entry point: embed, cluster, score.

Embeds every video that doesn't have one yet, clusters the embedded
English-language corpus into candidate niches, scores the eligible
ones, and prints a short summary. Safe to rerun: embedding only
touches videos missing one, and clustering/scoring both recompute from
scratch each time.

Run inside the api container with: python -m app.ingest.cluster
(or `make cluster` from the repo root).
"""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    from app.db.session import SessionLocal
    from app.services.clustering import run_clustering
    from app.services.embeddings import embed_missing_videos
    from app.services.scoring import run_scoring

    embedded = await embed_missing_videos(SessionLocal)
    print(f"Embedded {embedded} videos.")

    algorithm = os.environ.get("CLUSTERING_ALGORITHM", "hdbscan")
    cluster_summary = await run_clustering(SessionLocal, algorithm=algorithm)
    print(f"Clustering summary: {cluster_summary}")

    score_summary = await run_scoring(SessionLocal)
    print(
        f"Scored {score_summary['niches_eligible']} of "
        f"{score_summary['niches_total']} niches as eligible."
    )
    print(f"Top 3 by opportunity score: {score_summary['top_by_opportunity']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
