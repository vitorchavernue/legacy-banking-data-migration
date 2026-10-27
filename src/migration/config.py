"""Runtime settings, read from environment variables (or a local .env file).

Nothing secret lives in the code: connection strings, the API key and the alert webhook
come from the environment, so the same code runs on a laptop, in CI and in production.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Legacy core banking database (SQL Server in production and CI)
    legacy_db_url: str = "mssql+pymssql://sa:change-me@localhost:1433/legacy"
    # New relational database used by the applications (PostgreSQL)
    target_db_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/core"
    # Document store with the customer profile read by the web and mobile apps (MongoDB)
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "app"

    # Rows read from the legacy system per round trip
    batch_size: int = 5_000
    # Incremental runs re-read this many minutes before the last watermark, so rows committed
    # late with an older timestamp are not missed (upserts make the overlap harmless)
    watermark_overlap_minutes: int = 5
    # Time zone of the legacy timestamps (stored without offset)
    legacy_timezone: str = "America/Sao_Paulo"

    # Read-only API protection and failure alerts (Slack / Teams incoming webhook)
    api_key: str = "change-me"
    alert_webhook_url: str | None = None

    reports_dir: str = "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
