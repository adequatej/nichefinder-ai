"""SQLAlchemy models for NicheFinder AI.

YouTube channel and video ids are the natural primary keys because the
API guarantees them unique and stable.
"""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

EMBEDDING_DIM = 384


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    custom_url: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(String(8))
    uploads_playlist_id: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscriber_count: Mapped[int | None] = mapped_column(BigInteger)
    # True when the channel hides its subscriber count in the API.
    subs_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    video_count: Mapped[int | None] = mapped_column(BigInteger)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    niche_id: Mapped[int | None] = mapped_column(
        ForeignKey("niches.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    videos: Mapped[list[Video]] = relationship(back_populates="channel")


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (
        Index("ix_videos_channel_id", "channel_id"),
        Index("ix_videos_published_at", "published_at"),
        Index("ix_videos_niche_id", "niche_id"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    # Most videos have no tags; the feature code handles that explicitly.
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    category_id: Mapped[str | None] = mapped_column(String(8))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    detected_language: Mapped[str | None] = mapped_column(String(16))
    # Derived from duration since the API has no direct Shorts flag.
    is_short: Mapped[bool] = mapped_column(Boolean, default=False)
    # Live-stream recordings are excluded from velocity math.
    is_live_vod: Mapped[bool] = mapped_column(Boolean, default=False)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    niche_id: Mapped[int | None] = mapped_column(
        ForeignKey("niches.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    channel: Mapped[Channel] = relationship(back_populates="videos")


class VideoSnapshot(Base):
    __tablename__ = "video_snapshots"
    __table_args__ = (
        UniqueConstraint("video_id", "snapshot_date", name="uq_video_snapshot_per_day"),
        Index("ix_video_snapshots_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    # Calendar date set by the app so one snapshot per video per day is enforced.
    snapshot_date: Mapped[date] = mapped_column(Date)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChannelSnapshot(Base):
    __tablename__ = "channel_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "channel_id", "snapshot_date", name="uq_channel_snapshot_per_day"
        ),
        Index("ix_channel_snapshots_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[str] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date)
    subscriber_count: Mapped[int | None] = mapped_column(BigInteger)
    video_count: Mapped[int | None] = mapped_column(BigInteger)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VideoEmbedding(Base):
    __tablename__ = "video_embeddings"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    model_name: Mapped[str] = mapped_column(String(128), default="all-MiniLM-L6-v2")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Niche(Base):
    __tablename__ = "niches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(Text)
    top_terms: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    centroid: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    demand_score: Mapped[float | None] = mapped_column(Float)
    supply_score: Mapped[float | None] = mapped_column(Float)
    opportunity_score: Mapped[float | None] = mapped_column(Float)
    # Raw inputs behind each score so the ranking is auditable.
    score_components: Mapped[dict | None] = mapped_column(JSONB)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    channel_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("video_id", "model_version", name="uq_prediction_per_model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    model_version: Mapped[str] = mapped_column(String(64))
    breakout_probability: Mapped[float] = mapped_column(Float)
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ApiQuotaLog(Base):
    __tablename__ = "api_quota_log"
    __table_args__ = (
        Index("ix_api_quota_log_created_at", "created_at"),
        Index("ix_api_quota_log_strategy_label", "strategy_label"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(64))
    units: Mapped[int] = mapped_column(Integer)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    # Groups calls from one job run, for example "bootstrap-2026-08-28".
    run_label: Mapped[str | None] = mapped_column(String(128))
    # Names the quota strategy under test, read by bench_quota.py.
    strategy_label: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
