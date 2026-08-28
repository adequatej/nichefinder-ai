"""Export a flat per-video training dataset from Postgres to
ml/data/dataset.parquet (gitignored: this is a local artifact, rebuilt
from the live database, never committed).

Runs on the HOST, not inside a container, so it uses a synchronous
SQLAlchemy engine (psycopg2) against localhost:5432 rather than the
asyncpg URL the api/worker containers use internally. Override with
the ML_DATABASE_URL env var if Postgres isn't at the default location.

Exports ALL English-language videos (detected_language == 'en'), not
just the ones aged 7-180 days that labels.py can ultimately score.
That's a deliberate choice over exporting only the labeling window:
labels.py needs a channel's videos aged 30-180 days to compute that
channel's baseline, and features.py needs a channel's *whole* recent
upload history to compute uploads_per_week — both are channel-level
aggregates computed in-process (see dataset.py), so the export has to
carry every English video per channel or those aggregates would be
silently wrong for any video whose channel-mates got filtered out
before reaching Python. The extra rows cost is small (this repo's
gates already limit the corpus to one tracked-channel cohort) and it
avoids a second round-trip to Postgres to backfill "oh, also fetch
these other videos for aggregate purposes."

video_embeddings is a LEFT JOIN: a video can be English-detected
before it's been through the embedding step, and such a row is still
useful for the channel-level aggregates above even though it can't
become a training example itself (dataset.assemble_dataset drops rows
with no embedding).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

DEFAULT_DATABASE_URL = "postgresql://nichefinder:nichefinder@localhost:5432/nichefinder"

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "dataset.parquet"

QUERY = """
SELECT
    v.id AS video_id,
    v.channel_id,
    v.title,
    v.tags,
    v.category_id,
    v.published_at,
    v.duration_seconds,
    v.is_short,
    v.is_live_vod,
    v.view_count,
    v.like_count,
    v.comment_count,
    ve.embedding AS embedding,
    c.subscriber_count,
    c.subs_hidden,
    c.video_count AS channel_video_count
FROM videos v
JOIN channels c ON c.id = v.channel_id
LEFT JOIN video_embeddings ve ON ve.video_id = v.id
WHERE v.detected_language = 'en'
"""


def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or os.environ.get("ML_DATABASE_URL", DEFAULT_DATABASE_URL)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _register_vector(dbapi_connection, connection_record):  # noqa: ARG001
        # Registered per-connection so psycopg2 hands back numpy arrays
        # for the pgvector column instead of its raw text
        # representation ("[0.1,0.2,...]").
        from pgvector.psycopg2 import register_vector

        register_vector(dbapi_connection)

    return engine


def export_dataset(
    database_url: str | None = None,
    output_path: str | Path = OUTPUT_PATH,
) -> pd.DataFrame:
    """Query Postgres and write the flat parquet dataset. Idempotent:
    safe to rerun, it always overwrites `output_path` from scratch."""
    engine = get_engine(database_url)
    with engine.connect() as conn:
        df = pd.read_sql(text(QUERY), conn)

    # register_vector gives back a pgvector.Vector per row that has an
    # embedding (installed pgvector-python version: 0.5.0 — this is
    # its object, not a raw numpy array or list), and None for the
    # LEFT JOIN misses; store as a plain list so it round-trips
    # through parquet as a nested list column.
    df["embedding"] = df["embedding"].apply(
        lambda value: value.to_list() if value is not None else None
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Exported {len(df)} English-language video rows to {output_path}")
    return df


if __name__ == "__main__":
    export_dataset()
