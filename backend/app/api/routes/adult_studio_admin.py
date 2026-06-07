"""Adult Studio (18+) admin diagnostics — read-only operational visibility.

Admin-only. Exposes WHY a character's Adult Studio identity is in its current
lifecycle state (prepared / stale / training / ready / failed): fingerprints,
versions, training jobs, mark-render routes, last error, and — for stale models —
the current-vs-trained canon fingerprint comparison.

Strictly read-only: no writes, no provider construction, no training, no generation,
no Canon Studio access. SEPARATE from the Canon Studio admin surface.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.routes.admin import require_admin
from app.core.database import get_db
from app.models.character import Character as CharacterModel
from app.models.user import User
from app.services.adult_identity_diagnostics import build_diagnostics

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────


class AdultStudioMarkRouteDiag(BaseModel):
    canon_mark_id: str
    mark_type: Optional[str] = None
    body_region: Optional[str] = None
    side: Optional[str] = None
    route: str
    reason: Optional[str] = None
    mark_fingerprint: Optional[str] = None


class AdultStudioVersionDiag(BaseModel):
    id: int
    version_index: int
    state: str
    canon_fingerprint: Optional[str] = None
    lora_weights_uri: Optional[str] = None
    created_at: Optional[str] = None


class FingerprintComparison(BaseModel):
    current_fingerprint: Optional[str] = None
    trained_fingerprint: Optional[str] = None
    mismatch: bool = False


class AdultStudioDiagnosticsResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    character_id: int
    exists: bool
    status: Optional[str] = None
    model_status: Optional[str] = None
    stale: bool = False
    canon_fingerprint: Optional[str] = None
    active_version_id: Optional[int] = None
    version_count: int = 0
    training_job_count: int = 0
    mark_render_count: int = 0
    last_error: Optional[str] = None
    trigger_token: Optional[str] = None
    provider: Optional[str] = None
    base_model: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    mark_routes: list[AdultStudioMarkRouteDiag] = []
    versions: list[AdultStudioVersionDiag] = []
    fingerprint_comparison: FingerprintComparison = FingerprintComparison()


# ── Endpoint ───────────────────────────────────────────────────────────────


@router.get(
    "/characters/{character_id}/diagnostics",
    response_model=AdultStudioDiagnosticsResponse,
    summary="Admin: read-only Adult Studio identity diagnostics for a character",
)
def get_adult_studio_diagnostics(
    character_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return the diagnostics payload. 404 only if the character itself is missing."""
    character = db.get(CharacterModel, character_id)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Character not found."
        )
    _ = admin  # admin identity already enforced by the dependency
    return build_diagnostics(character_id, db)
