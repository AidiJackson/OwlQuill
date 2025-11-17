"""Application configuration using Pydantic Settings."""
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    # App Info
    APP_NAME: str = "OwlQuill"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite:///./owlquill.db"
    DB_ECHO: bool = False

    # Security
    SECRET_KEY: str = "owlquill-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

    # CORS - allow all origins in dev mode for Replit compatibility
    BACKEND_CORS_ORIGINS: list[str] = ["*"]  # Restrict in production via .env

    # Redis (stubbed for now)
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI (stubbed)
    AI_PROVIDER: Literal["fake", "openai", "anthropic"] = "fake"
    AI_API_KEY: str = ""

    # Media uploads
    MEDIA_ROOT: str = "./media"
    MEDIA_BASE_URL: str = "/media"
    MAX_IMAGE_SIZE_BYTES: int = 5 * 1024 * 1024  # 5 MB
    ALLOWED_IMAGE_CONTENT_TYPES: list[str] = [
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp"
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore"
    )


settings = Settings()
