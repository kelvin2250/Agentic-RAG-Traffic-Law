import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # ── Database & Redis ─────────────────────────────────────────────────────
    database_url: str = Field(
        "postgresql+asyncpg://postgres:postgres@localhost:5432/traffic_law",
        validation_alias="DATABASE_URL"
    )
    redis_url: str = Field(
        "redis://localhost:6379/0",
        validation_alias="REDIS_URL"
    )

    # ── Security & Auth ──────────────────────────────────────────────────────
    jwt_secret_key: str = Field(
        "super-secret-key-change-in-production-1234567890",
        validation_alias="JWT_SECRET_KEY"
    )
    access_token_expire_minutes: int = Field(
        20,
        validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    refresh_token_expire_days: int = Field(
        7,
        validation_alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # ── AI Service Connection ────────────────────────────────────────────────
    ai_service_url: str = Field(
        "http://localhost:8001",
        validation_alias="AI_SERVICE_URL"
    )


settings = Settings()
