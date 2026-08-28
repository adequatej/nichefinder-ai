"""Integration tests for the P5 API endpoints against a real Postgres.

Unlike the rest of this test suite (pure functions, or respx-mocked
HTTP), these hit an actual pgvector-enabled Postgres: there is no way
to test "does /api/niches return niches sorted correctly" or
nearest-neighbor search without one, and SQLite has no vector column
type to fall back to.

Requires TEST_DATABASE_URL pointing at a running Postgres with the
schema migrated (pgvector extension enabled). The whole module is
skipped when that's unset, so `pytest -q` stays green with zero
infrastructure. To run it, against a *disposable* database:

    docker compose up -d db
    docker compose exec db createdb -U nichefinder nichefinder_test
    cd backend
    DATABASE_URL="postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder_test" \
        alembic upgrade head
    DATABASE_URL="postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder_test" \
    TEST_DATABASE_URL="postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder_test" \
        .venv/bin/pytest -q tests/test_api_endpoints.py

Set both to the *same* database, and that database's name must end in
"_test" (enforced below) — this module's cleanup fixture DELETEs every
row from channels/videos/niches/video_embeddings/predictions/
api_quota_log before and after every test. Pointed at the database a
real `make bootstrap` populated, that would silently destroy a corpus
that cost real quota to build. Never point either variable at the
plain "nichefinder" database from docker-compose.yml.

TEST_DATABASE_URL is read here, by the test module itself, to build
the session factory used to override FastAPI's get_session dependency
(deliberately, rather than relying on app.db.session's module-level
engine, which is built once at import time from DATABASE_URL/
get_settings() and cached via lru_cache). DATABASE_URL is also needed
because a couple of endpoints (admin refresh) call service functions
that import app.db.session.SessionLocal directly rather than going
through the overridden dependency; for those to see the same seeded
data, that module-level engine has to point at the same database,
which only happens if DATABASE_URL is set before the app is imported.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import ApiQuotaLog, Channel, Niche, Prediction, Video, VideoEmbedding
from app.db.session import get_session
from app.main import app
from app.services.api_cache import get_api_cache
from tests.conftest import FakeCache

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="requires TEST_DATABASE_URL pointing at a running Postgres with the schema migrated",
)

if TEST_DATABASE_URL:
    _db_name = make_url(TEST_DATABASE_URL).database or ""
    if not _db_name.endswith("_test"):
        raise RuntimeError(
            f"TEST_DATABASE_URL points at database {_db_name!r}, which does not "
            "end in '_test'. This test module wipes channels/videos/niches/"
            "video_embeddings/predictions before and after every test — refusing "
            "to run against anything that isn't an obviously disposable database. "
            "Create one (e.g. `createdb nichefinder_test`), migrate it, and point "
            "TEST_DATABASE_URL/DATABASE_URL at that instead."
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
            await session.execute(delete(ApiQuotaLog))
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
async def test_niche_videos_404_for_missing_niche(client):
    resp = await client.get("/api/niches/999999/videos")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_niche_videos_returns_only_that_niches_videos_paginated(client, db_session):
    niche = await _seed_niche(db_session, label="videos-niche", opportunity_score=10.0)
    other_niche = await _seed_niche(db_session, label="other-niche", opportunity_score=20.0)
    await _seed_channel(db_session, channel_id="UCnv")
    await _seed_video(
        db_session, "vidnv000001", "UCnv", niche_id=niche.id, published_at=NOW
    )
    await _seed_video(
        db_session,
        "vidnv000002",
        "UCnv",
        niche_id=niche.id,
        published_at=NOW - timedelta(days=1),
    )
    # Belongs to a different niche: must not show up here.
    await _seed_video(db_session, "vidnv000003", "UCnv", niche_id=other_niche.id)
    await db_session.commit()

    resp = await client.get(f"/api/niches/{niche.id}/videos")
    assert resp.status_code == 200
    body = resp.json()
    ids = [item["id"] for item in body["items"]]
    assert ids == ["vidnv000001", "vidnv000002"]  # newest published first

    resp = await client.get(f"/api/niches/{niche.id}/videos", params={"limit": 1, "offset": 1})
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids == ["vidnv000002"]


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
    assert resp.json() == {"window_days": 30, "by_day": []}


@pytest.mark.asyncio
async def test_quota_stats_groups_by_day_and_strategy_from_real_rows(client, db_session):
    """Seeds through the actual ApiQuotaLog table (not hand-built dicts)
    so this exercises the func.date()-over-asyncpg boundary that the
    pure aggregate_quota_rows unit tests (tests/test_quota_stats.py)
    cannot: those hand-construct `date` objects and never touch the DB.
    """
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    db_session.add_all(
        [
            ApiQuotaLog(
                endpoint="channels.list", units=1, cache_hit=False,
                strategy_label="optimized", created_at=today,
            ),
            ApiQuotaLog(
                endpoint="channels.list", units=1, cache_hit=False,
                strategy_label="optimized", created_at=today,
            ),
            ApiQuotaLog(
                endpoint="search.list", units=0, cache_hit=True,
                strategy_label="optimized", created_at=today,
            ),
            ApiQuotaLog(
                endpoint="search.list", units=100, cache_hit=False,
                strategy_label="naive", created_at=yesterday,
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/stats/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 30

    by_key = {(row["day"], row["strategy_label"]): row for row in body["by_day"]}
    today_key = (today.date().isoformat(), "optimized")
    yesterday_key = (yesterday.date().isoformat(), "naive")

    assert today_key in by_key
    assert today_key[0] == today.date().isoformat()  # a plain "YYYY-MM-DD", not a timestamp
    assert by_key[today_key]["units_spent"] == 2
    assert by_key[today_key]["calls_uncached"] == 2
    assert by_key[today_key]["calls_cached"] == 1
    assert by_key[today_key]["units_saved"] == 100  # reconstructed from UNIT_COSTS

    assert by_key[yesterday_key]["units_spent"] == 100
    assert by_key[yesterday_key]["calls_cached"] == 0


@pytest.mark.asyncio
async def test_quota_stats_excludes_rows_outside_the_window(client, db_session):
    old = datetime.now(timezone.utc) - timedelta(days=100)
    db_session.add(
        ApiQuotaLog(
            endpoint="videos.list", units=1, cache_hit=False,
            strategy_label="optimized", created_at=old,
        )
    )
    await db_session.commit()

    resp = await client.get("/api/stats/quota", params={"days": 30})
    assert resp.json() == {"window_days": 30, "by_day": []}


@pytest.mark.asyncio
async def test_admin_refresh_denies_when_admin_token_is_unset(client, monkeypatch):
    """The default, unset admin_token must refuse every request rather
    than defaulting to open — the whole point of the guard.
    """
    monkeypatch.setattr(
        "app.api.admin.get_settings", lambda: type("S", (), {"admin_token": ""})()
    )
    resp = await client.post("/api/admin/refresh", headers={"X-Admin-Token": ""})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_refresh_requires_matching_token(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.admin.get_settings", lambda: type("S", (), {"admin_token": "secret"})()
    )
    resp = await client.post("/api/admin/refresh")
    assert resp.status_code == 403

    resp = await client.post("/api/admin/refresh", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_refresh_makes_no_outbound_http_calls(client, monkeypatch):
    """The dev-only refresh must only recompute scores from data already
    in Postgres — never reach the ingestion/bootstrap path, which is the
    whole point of "(dev only)". respx with no routes registered and
    assert_all_mocked=True makes any outbound HTTP call raise, so this
    catches a future regression regardless of which module it comes
    through (unlike patching YouTubeClient directly, which only proves
    admin.py itself doesn't import it today).
    """
    import respx

    monkeypatch.setattr(
        "app.api.admin.get_settings", lambda: type("S", (), {"admin_token": "secret"})()
    )

    with respx.mock(assert_all_mocked=True, assert_all_called=False):
        resp = await client.post("/api/admin/refresh", headers={"X-Admin-Token": "secret"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
