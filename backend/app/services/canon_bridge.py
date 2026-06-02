"""Pack → Canon bridge.

Populates and locks ``CharacterIdentityCanon`` from a character's locked
identity pack so the canon-routed scene generator (``image_generator.py`` →
``canon_compiler`` + ``scene_router``) has a real identity to ground on for
self-serve characters.

Why this exists
---------------
Before this bridge the canon (the single source of truth for scene generation)
was only ever populated by the admin upload endpoints. A normal user who
generated and *locked* an identity pack wrote ``identity_anchor_json`` on the
Character row but left ``CharacterIdentityCanon`` empty — so scene generation
returned ``409 Character canon incomplete``. This module closes that gap: at
lock time we seed the canon face/body slots from the pack anchors and migrate
any legacy body markings, then lock face + body canon.

Design rules
------------
* **Best-effort, never fatal.** The lock is already committed before this runs;
  any failure here is caught and logged, and the character proceeds.
* **Idempotent + non-destructive.** A slot is only filled when empty, so an
  admin-curated canon (manually uploaded references / hand-authored marks) is
  never clobbered. Re-running is a no-op.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from app.core.storage import file_path_to_url
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
)
from app.schemas.body_canon import BodyMarking
from app.schemas.canon import PermanentBodyMark
from app.services.body_canon import (
    build_compact_token,
    get_arm_side,
    get_canonical_body_front,
    load_markings,
)
from app.services.canon_service import (
    get_or_create_canon,
    lock_body_canon,
    lock_face_canon,
    load_body_canon,
    load_face_canon,
)
from app.schemas.canon import BodyCanonData, FaceCanonData

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# Legacy MarkingType → canon PermanentBodyMark.type. "burn" has no direct canon
# type so it degrades to the generic "body_marking" bucket.
_MARK_TYPE_MAP: dict[str, str] = {
    "tattoo": "tattoo",
    "scar": "scar",
    "birthmark": "birthmark",
    "mole": "mole",
    "burn": "body_marking",
    "body_marking": "body_marking",
}


def _derive_side(placement: str) -> str:
    """Map a marking placement to a canon side literal.

    left/right arm and limb placements resolve via the arm helper first; any
    other ``left_*`` / ``right_*`` placement (cheeks, hands, thighs) uses the
    prefix; everything else (chest, back, neck, abdomen) is centre.
    """
    arm = get_arm_side(placement)
    if arm in ("left", "right"):
        return arm
    p = (placement or "").lower()
    if p.startswith("left_"):
        return "left"
    if p.startswith("right_"):
        return "right"
    return "centre"


def _to_permanent_mark(m: BodyMarking) -> PermanentBodyMark:
    """Convert a legacy ``BodyMarking`` into a canon ``PermanentBodyMark``.

    body_region reuses the placement value verbatim — the scene router's
    exposure gate (``_mark_region_exposed``) already speaks this vocabulary
    (e.g. ``left_full_arm``, ``right_cheek``), so no remapping is needed.
    """
    placement = m.placement.value if hasattr(m.placement, "value") else str(m.placement)
    mark_type = m.type.value if hasattr(m.type, "value") else str(m.type)
    token = build_compact_token(m)
    label = (m.style or token or "permanent marking").strip()[:100]
    description = (m.description or token or label).strip()[:500]
    return PermanentBodyMark(
        label=label or "permanent marking",
        type=_MARK_TYPE_MAP.get(mark_type, "body_marking"),  # type: ignore[arg-type]
        body_region=placement[:80],
        side=_derive_side(placement),  # type: ignore[arg-type]
        description=description or label,
        reference_image_url=m.anchor_image_url,
        locked=True,
    )


def _face_front_url(character: CharacterModel, db: "Session") -> Optional[str]:
    """Best face-front reference for the canon.

    Prefers the tight IDENTITY_FACE_REF head crop produced at accept (clean,
    outfit-free), falling back to the raw front anchor URL.
    """
    face_ref = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character.id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .first()
    )
    if face_ref is not None and face_ref.file_path:
        return file_path_to_url(face_ref.file_path)

    # Fall back to the raw front anchor from identity_anchor_json.
    anchors = _anchors(character)
    front = anchors.get("front") or {}
    return front.get("url")


def _anchors(character: CharacterModel) -> dict:
    """Return the anchors dict from identity_anchor_json (empty on any error)."""
    if not character.identity_anchor_json:
        return {}
    try:
        data = json.loads(character.identity_anchor_json)
    except (ValueError, TypeError):
        return {}
    return data.get("anchors") or {}


def _anchor_meta(character: CharacterModel) -> dict:
    if not character.identity_anchor_json:
        return {}
    try:
        return json.loads(character.identity_anchor_json) or {}
    except (ValueError, TypeError):
        return {}


def seed_canon_from_pack(character: CharacterModel, db: "Session") -> dict:
    """Populate + lock CharacterIdentityCanon from the locked identity pack.

    Best-effort and non-destructive: only empty slots are filled, and an
    already-locked face/body canon is left untouched. Commits its own
    transaction. Never raises — returns a summary dict for logging/audit.
    """
    summary: dict = {
        "face_front_set": False,
        "face_3q_set": False,
        "body_front_set": False,
        "final_card_set": False,
        "marks_migrated": 0,
        "face_locked": False,
        "body_locked": False,
        "skipped": False,
        "error": None,
    }
    try:
        canon = get_or_create_canon(character.id, db)
        meta = _anchor_meta(character)
        anchors = meta.get("anchors") or {}

        # ── Face canon ────────────────────────────────────────────────
        face = load_face_canon(canon) or FaceCanonData()
        if not face.face_front_image_url:
            ff = _face_front_url(character, db)
            if ff:
                face.face_front_image_url = ff
                summary["face_front_set"] = True
        # Single 3/4 anchor → left-3q slot only. The turn direction is not
        # tracked, so we never populate the right-3q slot with a possibly
        # left-turned face; the router falls back gracefully when it is absent.
        if not face.face_left_3q_image_url:
            tq = (anchors.get("three_quarter") or {}).get("url")
            if tq:
                face.face_left_3q_image_url = tq
                summary["face_3q_set"] = True

        # ── Body canon ────────────────────────────────────────────────
        body = load_body_canon(canon) or BodyCanonData()
        if not body.body_front_image_url:
            bf_url, _src = get_canonical_body_front(character)
            if bf_url:
                body.body_front_image_url = bf_url
                summary["body_front_set"] = True
        # The full-body anchor is already a clean head-to-toe character image, so
        # it serves as the router's holistic grounding card (final_character_card)
        # at zero extra generation cost — but only when it is distinct from the
        # body_front slot, to avoid sending the provider the same ref twice.
        if not body.final_character_card_image_url:
            fb_url = (anchors.get("full_body") or {}).get("url")
            if fb_url and fb_url != body.body_front_image_url:
                body.final_character_card_image_url = fb_url
                summary["final_card_set"] = True
        # Morphology snapshot stored at lock.
        if body.height is None and meta.get("height"):
            body.height = meta.get("height")
        if body.build is None and meta.get("build"):
            body.build = meta.get("build")
        # Migrate legacy markings only when the canon has none of its own.
        if not body.permanent_body_marks:
            legacy = load_markings(character)
            migrated = [_to_permanent_mark(m) for m in legacy]
            if migrated:
                body.permanent_body_marks = migrated
                summary["marks_migrated"] = len(migrated)

        # Persist slot assignments before locking (lock_* validators read them).
        from app.services.canon_service import _save_face, _save_body

        _save_face(canon, face)
        _save_body(canon, body)

        # ── Lock (validators require front images, now set above) ──────
        if not canon.face_locked and face.face_front_image_url:
            try:
                lock_face_canon(canon)
                summary["face_locked"] = True
            except ValueError:
                pass
        if not canon.body_locked and body.body_front_image_url:
            try:
                lock_body_canon(canon)
                summary["body_locked"] = True
            except ValueError:
                pass

        db.commit()
    except Exception as exc:  # never break the (already-committed) lock
        db.rollback()
        summary["error"] = type(exc).__name__
        logger.warning(
            "CANON_BRIDGE_FAILED character_id=%s error=%s",
            getattr(character, "id", "?"), type(exc).__name__,
        )
        return summary

    logger.info(
        "CANON_BRIDGE character_id=%s face_front=%s face_3q=%s body_front=%s "
        "final_card=%s marks=%d face_locked=%s body_locked=%s",
        character.id, summary["face_front_set"], summary["face_3q_set"],
        summary["body_front_set"], summary["final_card_set"],
        summary["marks_migrated"], summary["face_locked"], summary["body_locked"],
    )
    return summary
