"""Environment-driven application configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

APP_VERSION = "0.9.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="development", description="development | test | production")
    database_url: str = Field(default=f"sqlite:///{BACKEND_DIR / 'var' / 'aptiguard.db'}")
    jwt_secret: str = Field(default="dev-only-insecure-secret-change-me")
    jwt_expire_minutes: int = 8 * 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    demo_mode: bool = True
    max_upload_mb: int = 10
    log_level: str = "INFO"

    # Optional LLM integration. Empty key => deterministic template fallback.
    llm_provider: str = "none"  # none | anthropic
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def using_insecure_secret(self) -> bool:
        return self.jwt_secret.startswith("dev-only")


@lru_cache
def get_settings() -> Settings:
    return Settings()
