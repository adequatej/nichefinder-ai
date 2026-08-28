"""Sentence embeddings for video text.

Uses sentence-transformers' all-MiniLM-L6-v2 (384 dimensions, matching
EMBEDDING_DIM in models.py and VideoEmbedding.model_name's default).
The model is loaded once, lazily, and runs on CPU: the containers this
runs in have no GPU, and a one-time bulk backfill onto faster hardware
is an optimization explicitly deferred to later, not something this
module needs to anticipate.
"""

from __future__ import annotations

MODEL_NAME = "all-MiniLM-L6-v2"

# Most videos have no tags; the first 500 characters of the description
# is enough for topical signal without letting a long description
# dominate the title.
DESCRIPTION_CHARS = 500

# Videos are embedded in batches so one run doesn't hold the whole
# corpus in memory or in a single model.encode() call.
EMBED_BATCH_SIZE = 256

_model = None


def _get_model():
    """Lazy singleton so importing this module never touches torch."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME, device="cpu")
    return _model


def build_embedding_text(
    title: str, tags: list[str] | None, description: str
) -> str:
    """Text fed to the encoder: title, tags (if any), then a description snippet."""
    tag_text = " ".join(tags) if tags else ""
    snippet = (description or "")[:DESCRIPTION_CHARS]
    return " ".join(part for part in (title or "", tag_text, snippet) if part).strip()


def embed_query(text: str) -> list[float]:
    """Embed a single free-text search query with the same model as videos.

    Kept as its own function (rather than inlined in the search endpoint)
    so the endpoint's "did it actually re-embed or reuse a cached vector"
    behavior can be tested by monkeypatching this one call.
    """
    model = _get_model()
    vector = model.encode([text], convert_to_numpy=True, show_progress_bar=False)
    return vector[0].tolist()


def embed_videos(rows: list[dict]) -> dict[str, list[float]]:
    """Embed a batch of videos. Each row needs id, title, tags, description.

    Returns {video_id: embedding}. Rows may be plain dicts or anything
    with the same keys (for example a mapping from an ORM row).
    """
    if not rows:
        return {}
    texts = [
        build_embedding_text(row["title"], row.get("tags"), row.get("description"))
        for row in rows
    ]
    model = _get_model()
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return {row["id"]: vectors[i].tolist() for i, row in enumerate(rows)}


async def upsert_embeddings(session, embeddings: dict[str, list[float]]) -> int:
    """Insert or update video_embeddings rows. Caller owns the transaction."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.db.models import VideoEmbedding

    if not embeddings:
        return 0
    rows = [
        {"video_id": video_id, "embedding": vector, "model_name": MODEL_NAME}
        for video_id, vector in embeddings.items()
    ]
    stmt = pg_insert(VideoEmbedding).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[VideoEmbedding.video_id],
        set_={
            "embedding": stmt.excluded.embedding,
            "model_name": stmt.excluded.model_name,
        },
    )
    await session.execute(stmt)
    return len(rows)


async def embed_missing_videos(
    session_factory, video_ids: list[str] | None = None
) -> int:
    """Embed every video without an embedding yet.

    When `video_ids` is given the search is restricted to those ids
    (still filtered to ones missing an embedding), which is how the
    daily refresh embeds only its newly-seen videos. With no ids, every
    video in the corpus missing an embedding is picked up, which is
    what the standalone clustering entry point needs on a cold start.
    """
    from sqlalchemy import select

    from app.db.models import Video, VideoEmbedding

    async with session_factory() as session:
        stmt = (
            select(Video.id, Video.title, Video.tags, Video.description)
            .outerjoin(VideoEmbedding, VideoEmbedding.video_id == Video.id)
            .where(VideoEmbedding.video_id.is_(None))
        )
        if video_ids is not None:
            if not video_ids:
                return 0
            stmt = stmt.where(Video.id.in_(video_ids))
        result = await session.execute(stmt)
        rows = [dict(row._mapping) for row in result]

    total = 0
    for start in range(0, len(rows), EMBED_BATCH_SIZE):
        batch = rows[start : start + EMBED_BATCH_SIZE]
        embeddings = embed_videos(batch)
        async with session_factory() as session:
            total += await upsert_embeddings(session, embeddings)
            await session.commit()
    return total
