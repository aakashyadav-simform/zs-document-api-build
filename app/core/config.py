from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Connections
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "document_insights"
    redis_url: str = "redis://localhost:6379/0"

    # Rate limiting
    rate_limit_max: int = 3
    rate_limit_ttl_seconds: int = 300

    # Content cache
    cache_ttl_seconds: int = 86400

    # Worker
    worker_poll_interval: float = 1.0
    worker_min_processing_seconds: float = 10.0
    worker_max_processing_seconds: float = 30.0
    failure_rate: float = 0.1
    max_attempts: int = 3
    stale_timeout_seconds: int = 120
    summary_char_limit: int = 500

    # Logging
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
