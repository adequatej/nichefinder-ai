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

test: ## Run backend tests
	docker compose exec api pytest -q

psql: ## Open a Postgres shell
	docker compose exec db psql -U nichefinder nichefinder
