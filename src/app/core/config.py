"""Application settings — loaded from env via Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === App ===
    app_env: Literal["local", "dev", "staging", "prod"] = "local"
    app_name: str = "coachai-backend"
    app_debug: bool = True
    app_timezone: str = "Asia/Tashkent"

    # === Database ===
    database_url: str = "postgresql+asyncpg://coachai:coachai@localhost:5432/coachai"

    # === Redis ===
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # === Security ===
    jwt_secret: str = "change-me-in-prod-please-use-a-real-secret-min-32-chars"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 30

    # === CORS ===
    cors_origins: str = "*"

    # === Gemini ===
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash-exp"

    # === Battle ===
    battle_rate_limit_per_day: int = 30
    battle_disconnect_grace_seconds: int = 30
    battle_question_timeout_seconds: int = 30
    battle_matchmaking_timeout_seconds: int = 30

    # === Locale ===
    default_locale: Literal["uz", "ru", "en"] = "uz"

    @field_validator("cors_origins")
    @classmethod
    def _normalize_cors(cls, v: str) -> str:
        return v.strip()

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "prod"

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
