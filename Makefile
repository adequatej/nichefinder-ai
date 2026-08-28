.DEFAULT_GOAL := help

help: ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

up: ## Start all services (db, redis, api, frontend)
	docker compose up -d --build

down: ## Stop all services
	docker compose down

logs: ## Tail logs from all services
	docker compose logs -f

migrate: ## Apply database migrations
	docker compose exec api alembic upgrade head

revision: ## Create a new migration (usage: make revision m="add foo table")
	docker compose exec api alembic revision --autogenerate -m "$(m)"

bootstrap: ## Run the real YouTube bootstrap (needs YOUTUBE_API_KEY in .env)
	docker compose exec api python -m app.ingest.bootstrap

bootstrap-sample: ## Load deterministic sample data, no API key needed
	docker compose exec api python -m app.ingest.sample_data

cluster: ## Embed videos, cluster into niches, and score opportunity
	docker compose exec api python -m app.ingest.cluster

test: ## Run backend tests
	docker compose exec api pytest -q

bench-quota: ## Compare naive vs optimized YouTube quota strategies
	docker compose exec api python -m benchmarks.bench_quota

bench-latency: ## Measure cold/warm latency for /api/search and /api/niches
	docker compose exec api python -m benchmarks.bench_latency

psql: ## Open a Postgres shell
	docker compose exec db psql -U nichefinder nichefinder
