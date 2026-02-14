"""Application configuration using Pydantic Settings."""
import os
import json
from typing import Literal, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # App Info
    APP_NAME: str = "Ficshon"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False  # Default to production-safe value

    # Database
    DATABASE_URL: str = "sqlite:///./owlquill.db"
    DB_ECHO: bool = False

    # Security
    # In production (DEBUG=false), SECRET_KEY must be set via environment.
    # In dev (DEBUG=true), a safe default is allowed.
    SECRET_KEY: Optional[str] = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS - No wildcard by default. Set BACKEND_CORS_ORIGINS in env.
    # Accepts comma-separated URLs or JSON array string.
    # Dev default allows common localhost ports and Replit preview domains.
    BACKEND_CORS_ORIGINS: str = ""

    # Rate limiting
    RATE_LIMIT_AUTH: str = "5/minute"  # Auth endpoint rate limit

    # Redis (stubbed for now)
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI (stubbed)
    AI_PROVIDER: Literal["fake", "openai", "anthropic"] = "fake"
    AI_API_KEY: str = ""

    # Password reset
    RESET_TOKEN_EXPIRE_MINUTES: int = 60  # 1 hour
    FRONTEND_URL: str = "http://localhost:5173"

    # Explicit dev mode flag (alternative to DEBUG for reset-link fallback)
    DEV_MODE: bool = False

    # Email / SMTP (optional — logs to console when unconfigured)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_TLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "hello@ficshon.com"

    # Admin — comma-separated emails that bypass cooldowns etc.
    # Falls back to ADMIN_EMAIL env var for single-admin setups.
    ADMIN_EMAILS: str = ""

    # Image generation
    IMAGE_PROVIDER: str = "openai"
    IMAGE_MODEL: str = "gpt-image-1.5"
    OPENAI_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )

    def get_secret_key(self) -> str:
        """Get SECRET_KEY with validation based on DEBUG mode."""
        if self.SECRET_KEY:
            return self.SECRET_KEY
        if not self.DEBUG:
            raise ValueError(
                "SECRET_KEY environment variable is required in production (DEBUG=false). "
                "Set a secure random string via SECRET_KEY env var."
            )
        # Safe default for development only
        return "dev-only-insecure-secret-key-do-not-use-in-production"

    def get_admin_emails(self) -> set[str]:
        """Return the set of admin email addresses (lowercased).

        Reads ADMIN_EMAILS first; falls back to ADMIN_EMAIL env var.
        """
        raw = self.ADMIN_EMAILS.strip()
        if not raw:
            raw = os.environ.get("ADMIN_EMAIL", "")
        return {e.strip().lower() for e in raw.split(",") if e.strip()}

    def is_dev_mode(self) -> bool:
        """True when running in development / non-production context."""
        return self.DEBUG or self.DEV_MODE

    def get_frontend_url(self) -> str:
        """Return frontend URL, auto-detecting Replit domain when needed."""
        # Explicit env override wins
        if self.FRONTEND_URL != "http://localhost:5173":
            return self.FRONTEND_URL.rstrip("/")
        # Auto-detect Replit public domain
        replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
        if replit_domain:
            return f"https://{replit_domain}"
        return self.FRONTEND_URL

    def get_cors_origins(self) -> list[str]:
        """Parse CORS origins from env.

        Accepts:
        - Comma-separated: "http://localhost:3000,http://localhost:5173"
        - JSON array: '["http://localhost:3000","http://localhost:5173"]'
        """
        if not self.BACKEND_CORS_ORIGINS:
            if self.DEBUG:
                # Safe dev defaults for local development and Replit
                return [
                    "http://localhost:3000",
                    "http://localhost:5173",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:5173",
                ]
            # Production with no CORS configured - empty list (same-origin only)
            return []

        origins_str = self.BACKEND_CORS_ORIGINS.strip()

        # Try JSON array first
        if origins_str.startswith("["):
            try:
                origins = json.loads(origins_str)
                if isinstance(origins, list):
                    return [o.strip() for o in origins if o.strip()]
            except json.JSONDecodeError:
                pass

        # Fall back to comma-separated
        return [o.strip() for o in origins_str.split(",") if o.strip()]


settings = Settings()
