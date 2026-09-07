"""
Candidate Slot Replacement API — Identity Evolution Phase 2.

Endpoints for the controlled slot-replacement workflow:
  POST   /{character_id}/identity-evolution/candidate-slot          — create
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/validate — validate
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/promote  — promote
  POST   /{character_id}/identity-evolution/candidate-slot/{id}/reject   — reject

Promotion takes a snapshot before mutating identity_anchor_json so rollback
is always available via the existing snapshot endpoints.

``image_url`` on the create route is RESOLVED against the caller's own image
library rather than trusted — see :func:`_resolve_owned_active_asset`.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate_slot import CandidateSlot
from app.models.character import Character
from app.models.character_image import CharacterImage, ImageStatusEnum
from app.models.user import User
from app.schemas.candidate_slot import CandidateSlotCreate, CandidateSlotRead
from app.schemas.identity_snapshot import IdentitySnapshotRead
from app.services.candidate_slot import (
    create_candidate,
    validate_candidate,
    promote_candidate,
    reject_candidate,
)
from app.services.character_home_media import candidate_file_paths

router = APIRouter()


# ── Guards ────────────────────────────────────────────────────────────────────

def _require_own_locked_character(
    character_id: int,
    current_user: User,
    db: Session,
) -> Character:
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your character")
    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Character identity is not locked. Lock an identity pack before using evolution features.",
        )
    return character


def _resolve_owned_active_asset(
    db: Session,
    character: Character,
    current_user: User,
    image_url: str,
) -> str:
    """Resolve *image_url* to the canonical ``file_path`` of an asset the caller
    may legitimately use — or refuse the request.

    THE INVARIANT: a candidate slot may only ever name a real, ACTIVE
    ``CharacterImage`` that belongs to THIS character and to THIS account. The
    stored value is that row's own ``file_path``, not the string the client
    sent, so what promotion later writes into ``identity_anchor_json`` is the
    asset's canonical storage identity and nothing else.

    WHY THIS IS A RESOLUTION AND NOT A ROLE CHECK. ``image_url`` used to be
    stored verbatim after a single "not empty" check, and promotion copied it
    into ``anchors[slot].url`` — which
    ``character_accessory.get_identity_anchor_urls`` reads and
    ``storage.load_image_bytes`` fetches before the bytes go to an image
    provider. An arbitrary string there is therefore three separate primitives
    at once: an off-platform image becomes the character's identity evidence;
    with local storage the server performs an attacker-directed HTTP GET; and
    with object storage the string is interpreted as a bucket key, so a bare
    filename reads somebody else's stored object. A founder check would close
    the first for ordinary users and leave the other two open for everyone, so
    this applies to EVERY caller including founders — they have upload routes
    that create real rows, and a row is exactly what this asks for.

    ``candidate_file_paths`` performs the inversion, shared with the public
    media resolver rather than reimplemented: ``file_path_to_url`` is not
    injective, so a client may honestly send ``/static/generated/a.png`` for a
    row stored as ``static/generated/a.png`` and both must resolve.

    Refuses with 422, not 403: the caller owns the character, and the request
    is not "forbidden for you" — it names an image that is not theirs, is not
    this character's, is not active, or does not exist at all. The four are
    deliberately indistinguishable in the response, so the endpoint cannot be
    used to probe which asset ids or storage paths exist.
    """
    candidates = list(candidate_file_paths(image_url))
    record = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.file_path.in_(candidates),
            CharacterImage.character_id == character.id,
            CharacterImage.user_id == current_user.id,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .first()
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "image_url must name one of this character's own active images. "
                "External image links and other characters' images aren't accepted."
            ),
        )
    return record.file_path


def _require_own_candidate(
    candidate_id: int,
    character: Character,
    db: Session,
) -> CandidateSlot:
    candidate = (
        db.query(CandidateSlot)
        .filter(
            CandidateSlot.id == candidate_id,
            CandidateSlot.character_id == character.id,
        )
        .first()
    )
    if not candidate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    return candidate


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/{character_id}/identity-evolution/candidate-slot",
    response_model=CandidateSlotRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a candidate slot replacement",
)
def create_candidate_slot(
    character_id: int,
    payload: CandidateSlotCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """
    Propose one of this character's own images as a replacement for a specific
    identity anchor slot.

    ``image_url`` is RESOLVED, not trusted: it must name an ACTIVE
    ``CharacterImage`` belonging to this character and this account, and what is
    stored is that row's canonical ``file_path``. An external link, another
    character's image, another account's image, or an archived one is refused
    with 422 — see :func:`_resolve_owned_active_asset` for why this is a
    resolution rather than a role check.

    The candidate is created with status='candidate' and validation_status='pending'.
    Run /validate next to check it before promoting.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    file_path = _resolve_owned_active_asset(
        db, character, current_user, payload.image_url
    )
    return create_candidate(db, character, payload.slot, file_path)


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/validate",
    response_model=CandidateSlotRead,
    summary="Validate a candidate slot replacement",
)
def validate_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """
    Run v1 validation on the candidate:
    - Check character is locked and candidate image is present.
    - Compare immutable spec fields (text only; face embedding deferred to Phase 3).
    - Warn if slot has no existing anchor to replace.
    Sets validation_status on the candidate; does not mutate the character.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)
    return validate_candidate(db, character, candidate)


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/promote",
    summary="Promote a candidate into the live identity anchor",
)
def promote_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Promote the candidate to canon:
    1. Takes an automatic snapshot (rollback always available).
    2. Replaces only the selected slot's URL in identity_anchor_json.
    3. Preserves accessories and all other anchor slots.
    4. Marks candidate as promoted.

    Returns the snapshot record and the updated candidate.
    """
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)

    try:
        snapshot, updated_candidate = promote_candidate(db, character, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return {
        "snapshot": IdentitySnapshotRead.model_validate(snapshot),
        "candidate": CandidateSlotRead.model_validate(updated_candidate),
    }


@router.post(
    "/{character_id}/identity-evolution/candidate-slot/{candidate_id}/reject",
    response_model=CandidateSlotRead,
    summary="Reject a candidate slot replacement",
)
def reject_candidate_slot(
    character_id: int,
    candidate_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CandidateSlot:
    """Mark the candidate as rejected. No changes are made to the character."""
    character = _require_own_locked_character(character_id, current_user, db)
    candidate = _require_own_candidate(candidate_id, character, db)

    try:
        return reject_candidate(db, candidate)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
