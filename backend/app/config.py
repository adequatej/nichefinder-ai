from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://nichefinder:nichefinder@localhost:5432/nichefinder"
    redis_url: str = "redis://localhost:6379/0"
    youtube_api_key: str = ""
    cache_enabled: bool = True
    # Shared secret for POST /api/admin/refresh. Empty means the route
    # refuses every request rather than defaulting to open.
    admin_token: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
