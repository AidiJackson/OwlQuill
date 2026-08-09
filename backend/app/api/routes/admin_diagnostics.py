"""Admin-only diagnostics endpoint for beta operational confidence."""
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User
from app.services.image_providers.google_provider import google_effective_config
from app.services.model_profiles import (
    supports_input_fidelity as _supports_input_fidelity,
)

router = APIRouter()


# ── Admin guard ──────────────────────────────────────────────────────────────

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency: raises 403 unless current user is in ADMIN_EMAILS."""
    if current_user.email.lower() not in settings.get_admin_emails():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── Helpers ───────────────────────────────────────────────────────────────────

def _redact_db_url(url: str) -> str:
    """Return scheme://host/dbname — credentials stripped."""
    try:
        p = urlparse(url)
        if p.hostname:
            return f"{p.scheme}://{p.hostname}{p.path}"
        # SQLite (no hostname): preserve the path portion only
        return f"{p.scheme}://{p.path}"
    except Exception:
        return "[redacted]"


def _get_db_revision(db: Session) -> Optional[str]:
    """Return current alembic version_num from DB, or None if unavailable."""
    try:
        result = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _get_alembic_head() -> Optional[str]:
    """Return the HEAD revision string from the migrations directory."""
    try:
        from alembic.config import Config as AlembicConfig
        from alembic.script import ScriptDirectory

        backend_dir = Path(__file__).resolve().parent.parent.parent.parent
        ini_path = backend_dir / "alembic.ini"
        cfg = AlembicConfig(str(ini_path))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        script_dir = ScriptDirectory.from_config(cfg)
        heads = script_dir.get_heads()
        return heads[0] if heads else None
    except Exception:
        return None


def _resolve_model(tier_val: str) -> str:
    """Return the effective model slug for a tier (fall back to base model)."""
    return tier_val if tier_val else settings.STORYLAB_MODEL


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/diagnostics")
def admin_diagnostics(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
) -> dict:
    """Return operational status snapshot for beta readiness review.

    All credential values are redacted; only presence is reported.
    Key presence is read from the live environment (os.getenv) so it reflects
    the runtime process rather than a cached settings snapshot.
    """
    # ── DB ──
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    db_rev = _get_db_revision(db)
    expected_head = _get_alembic_head()
    alembic_head_ok = (
        db_rev is not None
        and expected_head is not None
        and db_rev == expected_head
    )

    # ── StoryLab ──
    storylab_info = {
        "provider": settings.STORYLAB_PROVIDER,
        "daily_limit": settings.STORYLAB_DAILY_LIMIT,
        "openrouter_key_present": bool(os.getenv("OPENROUTER_API_KEY")),
        "models": {
            "sfw": _resolve_model(settings.STORYLAB_MODEL_SFW),
            "fade": _resolve_model(settings.STORYLAB_MODEL_FADE),
            "sensual": _resolve_model(settings.STORYLAB_MODEL_SENSUAL),
        },
    }

    # ── Images ──
    images_info = {
        "provider": settings.IMAGE_PROVIDER,
        "weekly_limit": settings.IMAGE_WEEKLY_LIMIT,
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "fal_key_present": bool(os.getenv("FAL_KEY")),
        # Effective model ids for BOTH image providers, so a dev-vs-prod model
        # diff is one diagnostics call (env vars override the code defaults —
        # this reports what the running process actually uses).
        "model": settings.IMAGE_MODEL,
        "google_model": settings.GOOGLE_IMAGE_MODEL,
        # Model-profile facts consumed by the pipeline (model_profiles.py).
        "openai_input_fidelity_supported": _supports_input_fidelity(settings.IMAGE_MODEL),
    }

    # ── Google (Gemini) — dev-vs-production comparison surface ──
    # A workspace and its Replit deployment are separate secret scopes, so
    # deployment secrets cannot be read from the workspace shell. This block is
    # the only way to establish whether the two runtimes authenticate to Google
    # as the same project. The credential is reported ONLY as a one-way
    # fingerprint and its length — never the key, never a recoverable prefix.
    google_info = google_effective_config()

    # ── Email ──
    email_info = {
        "smtp_configured": bool(settings.SMTP_HOST),
        "from_email": settings.SMTP_FROM,
        "host": settings.SMTP_HOST or None,
        "port": settings.SMTP_PORT,
    }

    # ── Safety — capabilities present in this codebase ──
    safety_info = {
        "reports_enabled": True,
        "blocks_enabled": True,
        "ban_enabled": True,
    }

    return {
        "ok": db_ok,
        "db": {
            "ok": db_ok,
            "database_url_redacted": _redact_db_url(settings.DATABASE_URL),
            "current_revision": db_rev,
            "expected_head": expected_head,
            "alembic_head_ok": alembic_head_ok,
        },
        "storylab": storylab_info,
        "images": images_info,
        "google": google_info,
        "email": email_info,
        "safety": safety_info,
    }
