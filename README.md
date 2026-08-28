# NicheFinder AI

A YouTube analytics platform that scores and ranks low-competition content niches, predicts which new videos are likely to break out, and does it all inside the free YouTube API quota.

This repo is the open-sourced rebuild of tooling I used privately while growing a 60,000+ follower account in an underserved niche (English-language coverage of Japanese high school soccer).

**Status: Phase 0 (scaffold).** See the phase checklist in the project plan.

## Stack

Python, FastAPI, SQLAlchemy, PostgreSQL with pgvector, Redis, PyTorch, sentence-transformers, Next.js (TypeScript, Tailwind), Terraform (AWS ECS Fargate, RDS, ElastiCache).

## Quick start

```bash
cp .env.example .env   # add your YouTube API key (steps inside the file)
make up                # start Postgres, Redis, API, and frontend
make migrate           # apply database migrations
```

Then open http://localhost:3000. The homepage shows live connection status for the API, Postgres, and Redis.

## Repo layout

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service, YouTube ingestion, clustering, scoring |
| `frontend/` | Next.js dashboard |
| `ml/` | Breakout model: labels, features, training, evaluation |
| `benchmarks/` | Scripts that produce the latency and quota numbers |
| `infra/terraform/` | Deploy-ready AWS infrastructure definitions |
| `docs/` | Architecture, system design, data modeling, case study |
