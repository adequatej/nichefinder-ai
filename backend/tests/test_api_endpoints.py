"""Integration tests for the P5 API endpoints against a real Postgres.

Unlike the rest of this test suite (pure functions, or respx-mocked
HTTP), these hit an actual pgvector-enabled Postgres: there is no way
to test "does /api/niches return niches sorted correctly" or
nearest-neighbor search without one, and SQLite has no vector column
type to fall back to.

Requires TEST_DATABASE_URL pointing at a running Postgres with the
schema migrated (pgvector extension enabled). The whole module is
skipped when that's unset, so `pytest -q` stays green with zero
infrastructure. To run it:

    docker compose up -d db          # or point at any pgvector Postgres
    cd backend
    alembic upgrade head             # against that same database
    DATABASE_URL="postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder" \
    TEST_DATABASE_URL="postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder" \
        .venv/bin/pytest -q tests/test_api_endpoints.py

Set both to the *same* database. TEST_DATABASE_URL is read here, by
the test module itself, to build the session factory used to override
FastAPI's get_session dependency (deliberately, rather than relying on
app.db.session's module-level engine, which is built once at import
time from DATABASE_URL/get_settings() and cached via lru_cache).
DATABASE_URL is also needed because a couple of endpoints (admin
refresh) call service functions that import app.db.session.SessionLocal
directly rather than going through the overridden dependency; for
those to see the same seeded data, that module-level engine has to
point at the same database, which only happens if DATABASE_URL is set
before the app is imported.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import Channel, Niche, Prediction, Video, VideoEmbedding
from app.db.session import get_session
from app.main import app
from app.services.api_cache import get_api_cache
from tests.conftest import FakeCache

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="requires TEST_DATABASE_URL pointing at a running Postgres with the schema migrated",
)

EMBEDDING_DIM = 384


def _vector(seed: float) -> list[float]:
    """A deterministic, distinguishable 384-dim vector for a given seed."""
    return [seed] + [0.0] * (EMBEDDING_DIM - 1)


@pytest.fixture
async def engine():
    # Function-scoped (not module-scoped): pytest-asyncio gives each test
    # function its own event loop, and asyncpg connections are bound to
    # the loop that created them, so a shared engine breaks on the
    # second test with "attached to a different loop."
    eng = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture(autouse=True)
async def _clean_tables(session_factory):
    """Wipe the tables this module touches, in FK order, before and after."""

    async def _wipe():
        async with session_factory() as session:
            await session.execute(delete(Prediction))
            await session.execute(delete(VideoEmbedding))
            await session.execute(delete(Video))
            await session.execute(delete(Channel))
            await session.execute(delete(Niche))
            await session.commit()

    await _wipe()
    yield
    await _wipe()


@pytest.fixture
async def client(session_factory):
    async def _override_get_session():
        async with session_factory() as session:
            yield session

    async def _override_get_api_cache():
        # A fresh in-memory cache per test, not a real Redis: these
        # tests are about Postgres-backed behavior, and a shared real
        # Redis persisting keys across test runs made an earlier
        # version of this suite flaky (a stale cached search-query
        # embedding survived between runs and hid a broken assertion).
        yield FakeCache()

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_api_cache] = _override_get_api_cache
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


async def _seed_niche(session, *, label, opportunity_score, video_count=30, channel_count=5):
    niche = Niche(
        label=label,
        top_terms=["term1", "term2"],
        opportunity_score=opportunity_score,
        demand_score=0.1 if opportunity_score is not None else None,
        supply_score=0.1 if opportunity_score is not None else None,
        score_components={"video_count": video_count} if opportunity_score is not None else None,
        video_count=video_count,
        channel_count=channel_count,
    )
    session.add(niche)
    await session.flush()
    return niche


async def _seed_channel(session, channel_id="UCtest0001", niche_id=None):
    channel = Channel(id=channel_id, title="Test Channel", niche_id=niche_id)
    session.add(channel)
    await session.flush()
    return channel


async def _seed_video(session, video_id, channel_id, niche_id=None, published_at=NOW):
    video = Video(
        id=video_id,
        channel_id=channel_id,
        title=f"Video {video_id}",
        niche_id=niche_id,
        published_at=published_at,
        view_count=1000,
    )
    session.add(video)
    await session.flush()
    return video


async def _seed_embedding(session, video_id, seed):
    session.add(VideoEmbedding(video_id=video_id, embedding=_vector(seed)))
    await session.flush()


@pytest.mark.asyncio
async def test_niches_list_orders_by_opportunity_score_nulls_last(client, db_session):
    await _seed_niche(db_session, label="low", opportunity_score=10.0)
    await _seed_niche(db_session, label="high", opportunity_score=90.0)
    # Ineligible niche: score fields are NULL, per scoring.py's floor.
    await _seed_niche(db_session, label="ineligible", opportunity_score=None)
    await db_session.commit()

    resp = await client.get("/api/niches")
    assert resp.status_code == 200
    labels = [item["label"] for item in resp.json()["items"]]
    assert labels == ["high", "low", "ineligible"]


@pytest.mark.asyncio
async def test_niche_detail_404_for_missing_id(client):
    resp = await client.get("/api/niches/999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_niche_detail_includes_score_components(client, db_session):
    niche = await _seed_niche(db_session, label="detail-me", opportunity_score=55.5)
    await db_session.commit()

    resp = await client.get(f"/api/niches/{niche.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["label"] == "detail-me"
    assert body["score_components"] == {"video_count": 30}


@pytest.mark.asyncio
async def test_channel_detail_includes_niche(client, db_session):
    niche = await _seed_niche(db_session, label="channel-niche", opportunity_score=42.0)
    await _seed_channel(db_session, channel_id="UCchan1", niche_id=niche.id)
    await db_session.commit()

    resp = await client.get("/api/channels/UCchan1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "UCchan1"
    assert body["niche"]["id"] == niche.id


@pytest.mark.asyncio
async def test_channel_detail_404_for_missing_id(client):
    resp = await client.get("/api/channels/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_similar_videos_excludes_self(client, db_session):
    await _seed_channel(db_session, channel_id="UCsim")
    await _seed_video(db_session, "vidself0001", "UCsim")
    await _seed_video(db_session, "vidnear0001", "UCsim")
    await _seed_video(db_session, "vidfar00001", "UCsim")
    await db_session.commit()
    # vidnear is close to vidself; vidfar is far away.
    await _seed_embedding(db_session, "vidself0001", seed=1.0)
    await _seed_embedding(db_session, "vidnear0001", seed=1.01)
    await _seed_embedding(db_session, "vidfar00001", seed=-5.0)
    await db_session.commit()

    resp = await client.get("/api/videos/vidself0001/similar?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["items"]]
    assert "vidself0001" not in ids
    assert ids[0] == "vidnear0001"


@pytest.mark.asyncio
async def test_similar_videos_404_when_no_embedding(client, db_session):
    await _seed_channel(db_session, channel_id="UCnoemb")
    await _seed_video(db_session, "vidnoembed1", "UCnoemb")
    await db_session.commit()

    resp = await client.get("/api/videos/vidnoembed1/similar")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_search_embeds_query_text_and_returns_nearest(client, db_session, monkeypatch):
    await _seed_channel(db_session, channel_id="UCsearch")
    await _seed_video(db_session, "vidsearch01", "UCsearch")
    await db_session.commit()
    await _seed_embedding(db_session, "vidsearch01", seed=2.0)
    await db_session.commit()

    calls = []

    def fake_embed_query(text: str) -> list[float]:
        calls.append(text)
        return _vector(2.0)

    monkeypatch.setattr("app.api.search.embed_query", fake_embed_query)

    resp = await client.get("/api/search", params={"q": "some query"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "some query"
    assert body["items"][0]["id"] == "vidsearch01"
    assert calls == ["some query"]


@pytest.mark.asyncio
async def test_search_missing_query_is_400(client):
    resp = await client.get("/api/search")
    assert resp.status_code == 400

    resp = await client.get("/api/search", params={"q": "   "})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_breakouts_handles_empty_predictions_table(client, db_session):
    # No Prediction rows seeded at all: this is the expected state
    # until ml/'s pipeline has trained on real bootstrap data.
    resp = await client.get("/api/predictions/breakouts")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_breakouts_orders_by_probability_desc(client, db_session):
    await _seed_channel(db_session, channel_id="UCpred")
    await _seed_video(db_session, "vidpred0001", "UCpred")
    await _seed_video(db_session, "vidpred0002", "UCpred")
    await db_session.commit()
    db_session.add(Prediction(video_id="vidpred0001", model_version="v1", breakout_probability=0.2))
    db_session.add(Prediction(video_id="vidpred0002", model_version="v1", breakout_probability=0.9))
    await db_session.commit()

    resp = await client.get("/api/predictions/breakouts")
    body = resp.json()
    assert [item["video_id"] for item in body["items"]] == ["vidpred0002", "vidpred0001"]


@pytest.mark.asyncio
async def test_quota_stats_empty_ledger(client):
    resp = await client.get("/api/stats/quota")
    assert resp.status_code == 200
    assert resp.json() == {"by_day": []}


@pytest.mark.asyncio
async def test_admin_refresh_requires_token(client, monkeypatch):
    monkeypatch.setattr("app.api.admin.get_settings", lambda: type(
        "S", (), {"admin_token": "secret"}
    )())
    resp = await client.post("/api/admin/refresh")
    assert resp.status_code == 403

    resp = await client.post("/api/admin/refresh", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_refresh_does_not_touch_youtube_client(client, monkeypatch):
    """The dev-only refresh must only recompute scores from data already
    in Postgres. It must never construct a YouTubeClient or reach the
    ingestion/bootstrap path, which is the whole point of "(dev only)".
    """
    monkeypatch.setattr("app.api.admin.get_settings", lambda: type(
        "S", (), {"admin_token": "secret"}
    )())

    called = {"youtube_client": False}

    class ExplodingYouTubeClient:
        def __init__(self, *args, **kwargs):
            called["youtube_client"] = True
            raise AssertionError("admin refresh must not construct a YouTubeClient")

    monkeypatch.setattr("app.services.youtube.YouTubeClient", ExplodingYouTubeClient)

    resp = await client.post("/api/admin/refresh", headers={"X-Admin-Token": "secret"})
    assert resp.status_code == 200
    assert called["youtube_client"] is False
    assert resp.json()["status"] == "ok"
