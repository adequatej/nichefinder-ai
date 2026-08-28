"""POST /api/admin/refresh — dev-only trigger for recomputing scores.

Deliberately narrow: it calls scoring.run_scoring (recompute demand/
supply/opportunity from data already in Postgres), which costs zero
YouTube quota. It must NOT call anything in app/ingest/bootstrap.py or
the daily refresh path — those make real YouTube API calls and belong
behind `make bootstrap` / the worker's cron job, not an HTTP route.

It also does not trigger a full clustering pass (app/ingest/cluster.py,
clustering.run_clustering): per that module's own docstring, a full run
deletes and rebuilds every niche's id, which is disruptive enough that
it belongs to the standalone `make cluster` entry point, not something
an HTTP call should be able to kick off casually.

Guarded by a shared-secret header rather than real auth, because this
phase doesn't call for a user/session model — see config.admin_token.
An empty admin_token (the default) refuses every request rather than
defaulting to open, so an operator has to opt in deliberately.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.db.session import SessionLocal
from app.services.scoring import run_scoring

router = APIRouter()


@router.post("/api/admin/refresh")
async def admin_refresh(x_admin_token: str | None = Header(default=None)) -> dict:
    settings = get_settings()
    if not settings.admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Not authorized")

    stats = await run_scoring(SessionLocal)
    return {"status": "ok", "scoring": stats}
