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
    DATABASE_URL: str = "sqlite:///./ficshon.db"
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
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"

    # Fallback image provider (used when primary blocks/fails in tier C)
    IMAGE_PROVIDER_FALLBACK: str = "fal"
    FAL_KEY: Optional[str] = None
    FAL_MODEL_CHARACTER_PACK: str = "fal-ai/flux/dev"

    # Google AI image provider (optional — for identity pack A/B testing)
    GOOGLE_AI_API_KEY: Optional[str] = None
    GOOGLE_IMAGE_MODEL: str = "imagen-3.0-generate-001"
    GOOGLE_IMAGE_TIMEOUT_S: int = 180
    # If set, identity pack generation uses this provider instead of IMAGE_PROVIDER.
    # Valid values: "openai" | "google" | "openrouter" | "" (empty = inherit IMAGE_PROVIDER)
    # When set, it overrides both IDENTITY_SEED_PROVIDER and IDENTITY_ANGLES_PROVIDER.
    IDENTITY_IMAGE_PROVIDER: str = ""

    # B7: Forced hybrid identity pack — per-phase provider selection.
    # IDENTITY_SEED_PROVIDER: provider used to generate the front anchor (seed) image.
    # IDENTITY_ANGLES_PROVIDER: provider used to generate the 3 grounded angle shots.
    # Both are ignored when IDENTITY_IMAGE_PROVIDER is set (legacy override takes precedence).
    IDENTITY_SEED_PROVIDER: str = "openai"
    IDENTITY_ANGLES_PROVIDER: str = "google"

    # OpenRouter image provider (optional — for identity pack A/B testing)
    # OPENROUTER_API_KEY is shared with StoryLab; set above under StoryLab config.
    # OPENROUTER_IMAGE_MODEL selects the image-generation model on OpenRouter.
    OPENROUTER_IMAGE_MODEL: str = "openai/gpt-image-1"

    # Grok Imagine via OpenRouter — Editor Studio (E2) image-to-image editing.
    # Uses the shared OPENROUTER_API_KEY; admin-only in the editor provider selector.
    OPENROUTER_GROK_IMAGE_MODEL: str = "x-ai/grok-imagine-image-quality"

    # FLUX via OpenRouter — admin/internal testing only (option3 / option4).
    # FLUX does NOT support multi-reference image conditioning; generation is
    # text-to-image only.  Set these to the exact OpenRouter model slugs.
    OPENROUTER_FLUX_PRO_MODEL: str = "black-forest-labs/flux-pro-v1.1"
    OPENROUTER_FLUX_MAX_MODEL: str = "black-forest-labs/flux-pro-v1.1-ultra"

    # Together AI FLUX.2 — admin/internal testing only (option5).
    # References are supported via public HTTPS URLs (refs_support_level="url_required").
    # Local static paths are not accessible by Together's backend — they are filtered
    # before the payload is sent.
    TOGETHER_API_KEY: Optional[str] = None
    TOGETHER_FLUX_MODEL: str = "black-forest-labs/FLUX.1-schnell-Free"

    # Vision model used for identity pack front-anchor validation (B6).
    # Must support image input (vision). Defaults to gpt-4o-mini (cheap + capable).
    OPENAI_VISION_MODEL: str = "gpt-4o-mini"

    # ── Closed-loop face verification (identity consistency gate) ──────
    # After a character-inclusive scene image is generated, compare the
    # generated face against the locked canon face_front. If similarity is
    # below the threshold, regenerate with escalated grounding (up to N tries)
    # and keep the best-scoring result. Best-effort: silently skipped when there
    # is no OPENAI_API_KEY, no canon face reference, or a stub provider is used,
    # so it never affects tests or offline runs. Disable with =false in prod.
    IDENTITY_FACE_VERIFY: bool = True
    IDENTITY_FACE_VERIFY_THRESHOLD: float = 0.6
    IDENTITY_FACE_VERIFY_MAX_RETRIES: int = 1

    # Grammar engine — LanguageTool
    # Self-host: docker run -p 8010:8010 erikvl87/languagetool
    #            then set LANGUAGETOOL_URL=http://localhost:8010/v2
    # Public fallback: https://api.languagetool.org/v2 (rate-limited, no key needed)
    LANGUAGETOOL_URL: str = "https://api.languagetool.org/v2"

    # Image quota — rolling 7-day window per user
    IMAGE_WEEKLY_LIMIT: int = 10

    # Identity pack rate limit — per character, rolling 24-hour window
    IDENTITY_PACK_DAILY_LIMIT: int = 10

    # StoryLab narrative engine
    # STORYLAB_PROVIDER: "stub" (deterministic, no key needed) | "openrouter"
    # STORYLAB_MODEL: any OpenRouter-supported model slug.
    # Default uses qwen/qwen-2.5-72b-instruct — a confirmed working non-Bedrock route.
    # Claude short slugs (anthropic/claude-3.5-sonnet, anthropic/claude-3.7-sonnet) are
    # NOT auto-corrected; configure the exact working slug in .env instead.
    STORYLAB_PROVIDER: str = "stub"
    OPENROUTER_API_KEY: str = ""
    STORYLAB_MODEL: str = "qwen/qwen-2.5-72b-instruct"
    # Per-boundary model overrides (empty = fall back to STORYLAB_MODEL)
    STORYLAB_MODEL_SFW: str = ""
    STORYLAB_MODEL_FADE: str = ""
    STORYLAB_MODEL_SENSUAL: str = ""
    # Explicit inferno model override — must be a permissive model (not Claude).
    # When empty, falls back to the INFERNO_ALLOWED_MODELS priority list in rp_models.py.
    STORYLAB_MODEL_INFERNO: str = ""
    # Per-user daily chapter generation quota (0 = unlimited)
    STORYLAB_DAILY_LIMIT: int = 20

    # B17: Simplified image generator provider toggle.
    # When True, the frontend toggle (Option 1 / Option 2) is active and respected.
    # Set to False to collapse to Option 1 (OpenAI) only for production.
    IMAGE_GENERATOR_PROVIDER_TOGGLE: bool = True

    # Closed-beta invite gate (B46)
    # BETA_INVITE_REQUIRED: set True to require an invite code at registration.
    #   Set False to open registration (e.g. after public launch).
    # BETA_INVITE_CODES: comma-separated list of codes to seed at startup.
    #   Each entry is either "CODE" (unlimited uses) or "CODE:N" (N max uses).
    #   Existing codes are never modified; only missing ones are created.
    #   Example: BETA_INVITE_CODES="FICBETA-LAUNCH:50,FICBETA-PRESS:10,FICBETA-DEV"
    BETA_INVITE_REQUIRED: bool = True
    BETA_INVITE_CODES: str = ""

    # Object storage — set true to write new images to Cloudflare R2
    USE_OBJECT_STORAGE: bool = False

    # ── Adult Studio (18+) — Phase 2 flags ────────────────────────────────
    # Real GPU training/generation providers stay OFF by default. With the
    # defaults below the /train and /generate endpoints return 409 and NO
    # provider is constructed and NO external call is made. See
    # docs/ADULT_STUDIO_PHASE2_DESIGN.md §5.
    ADULT_STUDIO_TRAINING_ENABLED: bool = False
    ADULT_STUDIO_GENERATION_ENABLED: bool = False
    # Provider selector. "disabled" → none; "fake" → in-memory FakeTrainingProvider
    # (tests/dev only); "replicate" → ReplicateTrainingProvider (Phase 3, real LoRA
    # training). A real provider is constructed ONLY when the selector is "replicate"
    # AND ADULT_STUDIO_TRAINING_ENABLED is true — otherwise no provider, no network.
    ADULT_STUDIO_PROVIDER: str = "disabled"

    # ── Adult Studio (18+) — Phase 3 Replicate training provider ──────────────
    # Only consulted when ADULT_STUDIO_PROVIDER=replicate AND training is enabled.
    # REPLICATE_API_TOKEN: Replicate API token (Bearer). Empty → provider refuses
    #   to construct, so no half-configured network calls are possible.
    # ADULT_STUDIO_REPLICATE_OWNER: account that owns the trained destination models.
    REPLICATE_API_TOKEN: str = ""
    ADULT_STUDIO_REPLICATE_OWNER: str = ""

    # ── Adult Studio (18+) — Replicate experimental img2img provider (Sprint E9) ─
    # A SEPARATE, experimental fourth provider that takes an existing canon source
    # image and runs pure image-to-image through Replicate. Does NOT replace the
    # OpenAI/Gemini/Grok generation paths and shares no mask/compositing/editor-job
    # logic. Reachable ONLY from the admin-only "Replicate Test" endpoint, and only
    # when REPLICATE_API_TOKEN is set — empty token → provider refuses to construct.
    #   ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL: primary "owner/name" (or "owner/name:version").
    #   ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL_FALLBACK: model tried if the primary fails.
    #   ADULT_STUDIO_REPLICATE_IMG2IMG_STRENGTH: prompt_strength for img2img (0..1).
    # Primary: asiryan/realistic-vision-v6.0-b1 (photoreal, NSFW-tolerant; uses the
    # ``strength`` input). Fallback stability-ai/sdxl uses ``prompt_strength`` — the
    # provider sends exactly one of the two based on the model slug.
    ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL: str = "asiryan/realistic-vision-v6.0-b1"
    ADULT_STUDIO_REPLICATE_IMG2IMG_MODEL_FALLBACK: str = "stability-ai/sdxl"
    ADULT_STUDIO_REPLICATE_IMG2IMG_STRENGTH: float = 0.58

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
