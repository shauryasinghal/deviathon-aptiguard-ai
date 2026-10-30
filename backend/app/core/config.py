"""Environment-driven application configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
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
    # Password for the seeded *synthetic* demo accounts. Only ever used by the seed script and shown on the login
    # page while demo mode is on outside production.
    demo_password: str = "AptiGuard-Demo-2026"
    login_max_failures: int = 8          # per client+email within the window
    login_window_seconds: int = 300
    max_request_mb: int = 12
    max_upload_mb: int = 10
    log_level: str = "INFO"
    # Seconds between background sweeps that finalise expired attempts (0 disables the in-process sweeper; the
    # scripts/finalize_expired.py command and the lazy checks still work). Safe with several workers.
    expiry_sweep_seconds: int = Field(default=60, ge=0, le=3600)

    # Public self-registration and Google sign-in. Self-registered users are ALWAYS candidates, and join only the
    # organisation named here (never one supplied by the client). Empty = self-registration disabled.
    registration_org_slug: str = ""
    frontend_url: str = "http://localhost:5173"  # where the OAuth callback sends the browser (fixed routes only)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"  # must match the Google console exactly
    # Password-reset delivery. No e-mail infrastructure exists: "none" sends nothing (the endpoint still answers
    # generically); "log" writes the reset link to the server log and is for local development only.
    password_reset_delivery: str = "none"  # none | log
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=120)

    # Optional LLM integration. Empty key => deterministic template fallback.
    llm_provider: str = "none"  # none | anthropic
    llm_api_key: str = ""
    llm_model: str = "claude-opus-5-5"
    llm_timeout_seconds: int = 60

    @field_validator("password_reset_delivery", mode="before")
    @classmethod
    def _known_delivery(cls, v):
        v = str(v).strip().lower()
        if v not in ("none", "log"):
            raise ValueError("PASSWORD_RESET_DELIVERY must be one of: none, log")
        return v

    @field_validator("app_env", mode="before")
    @classmethod
    def _known_env(cls, v):
        """Unknown values (e.g. 'prod', 'Production ') must not silently bypass the production guard."""
        v = str(v).strip().lower()
        if v not in ("development", "test", "production"):
            raise ValueError("APP_ENV must be one of: development, test, production")
        return v

    @model_validator(mode="after")
    def _production_guard(self):
        """Demo conveniences must never weaken a production deployment."""
        if self.app_env == "production":
            problems = []
            if self.demo_mode:
                problems.append("DEMO_MODE must be false")
            if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
                problems.append("JWT_SECRET must be set to a random value of at least 32 characters")
            if "*" in self.cors_origins:
                problems.append("CORS_ORIGINS must list explicit origins")
            if self.password_reset_delivery == "log":
                problems.append("PASSWORD_RESET_DELIVERY=log is development-only")
            if self.google_client_id and not (self.google_redirect_uri.startswith("https://") and self.frontend_url.startswith("https://")):
                problems.append("GOOGLE_REDIRECT_URI and FRONTEND_URL must be https when Google sign-in is enabled")
            if problems:
                raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)

    @property
    def llm_configured(self) -> bool:
        return self.llm_provider != "none" and bool(self.llm_api_key)

    @property
    def using_insecure_secret(self) -> bool:
        return self.jwt_secret.startswith("dev-only")


class ConfigurationError(RuntimeError):
    pass


@lru_cache
def get_settings() -> Settings:
    from pydantic import ValidationError

    try:
        return Settings()
    except ValidationError as e:
        # Report only the rule messages: pydantic's default text echoes input values (could include secrets).
        msgs = "; ".join(str(err.get("msg", "invalid value")).removeprefix("Value error, ") for err in e.errors())
        raise ConfigurationError(f"Invalid configuration: {msgs}") from None
