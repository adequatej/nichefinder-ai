"""Initial schema: channels, videos, snapshots, embeddings, niches, predictions, quota log.

Revision ID: 0001
Revises:
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "niches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("top_terms", ARRAY(sa.Text()), nullable=True),
        sa.Column("centroid", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("demand_score", sa.Float(), nullable=True),
        sa.Column("supply_score", sa.Float(), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=True),
        sa.Column("score_components", JSONB(), nullable=True),
        sa.Column("video_count", sa.Integer(), nullable=False),
        sa.Column("channel_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "channels",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("custom_url", sa.Text(), nullable=True),
        sa.Column("country", sa.String(8), nullable=True),
        sa.Column("uploads_playlist_id", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscriber_count", sa.BigInteger(), nullable=True),
        sa.Column("subs_hidden", sa.Boolean(), nullable=False),
        sa.Column("video_count", sa.BigInteger(), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("is_tracked", sa.Boolean(), nullable=False),
        sa.Column(
            "niche_id",
            sa.Integer(),
            sa.ForeignKey("niches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_channels_is_tracked", "channels", ["is_tracked"])
    op.create_index("ix_channels_niche_id", "channels", ["niche_id"])

    op.create_table(
        "videos",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column(
            "channel_id",
            sa.String(64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", ARRAY(sa.Text()), nullable=True),
        sa.Column("category_id", sa.String(8), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("detected_language", sa.String(16), nullable=True),
        sa.Column("is_short", sa.Boolean(), nullable=False),
        sa.Column("is_live_vod", sa.Boolean(), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "niche_id",
            sa.Integer(),
            sa.ForeignKey("niches.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_videos_channel_id", "videos", ["channel_id"])
    op.create_index("ix_videos_published_at", "videos", ["published_at"])
    op.create_index("ix_videos_niche_id", "videos", ["niche_id"])

    op.create_table(
        "video_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "video_id",
            sa.String(16),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column("like_count", sa.BigInteger(), nullable=True),
        sa.Column("comment_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "video_id", "snapshot_date", name="uq_video_snapshot_per_day"
        ),
    )
    op.create_index("ix_video_snapshots_video_id", "video_snapshots", ["video_id"])
    op.create_index(
        "ix_video_snapshots_snapshot_date", "video_snapshots", ["snapshot_date"]
    )

    op.create_table(
        "channel_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id",
            sa.String(64),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("subscriber_count", sa.BigInteger(), nullable=True),
        sa.Column("video_count", sa.BigInteger(), nullable=True),
        sa.Column("view_count", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "channel_id", "snapshot_date", name="uq_channel_snapshot_per_day"
        ),
    )
    op.create_index(
        "ix_channel_snapshots_channel_id", "channel_snapshots", ["channel_id"]
    )
    op.create_index(
        "ix_channel_snapshots_snapshot_date", "channel_snapshots", ["snapshot_date"]
    )

    op.create_table(
        "video_embeddings",
        sa.Column(
            "video_id",
            sa.String(16),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    # HNSW is overkill at 10K rows; kept to demonstrate the production pattern.
    op.execute(
        "CREATE INDEX ix_video_embeddings_embedding_hnsw "
        "ON video_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "video_id",
            sa.String(16),
            sa.ForeignKey("videos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("breakout_probability", sa.Float(), nullable=False),
        sa.Column(
            "predicted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("video_id", "model_version", name="uq_prediction_per_model"),
    )
    op.create_index("ix_predictions_video_id", "predictions", ["video_id"])

    op.create_table(
        "api_quota_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("run_label", sa.String(128), nullable=True),
        sa.Column("strategy_label", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_api_quota_log_created_at", "api_quota_log", ["created_at"])
    op.create_index(
        "ix_api_quota_log_strategy_label", "api_quota_log", ["strategy_label"]
    )


def downgrade() -> None:
    op.drop_table("api_quota_log")
    op.drop_table("predictions")
    op.drop_table("video_embeddings")
    op.drop_table("channel_snapshots")
    op.drop_table("video_snapshots")
    op.drop_table("videos")
    op.drop_table("channels")
    op.drop_table("niches")
