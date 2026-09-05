"""Scene image generation endpoints — anchored to a character's locked identity."""
import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import save_image, load_image_bytes
from app.models.user import User
from app.models.character import Character as CharacterModel
from app.models.character_image import CharacterImage, ImageKindEnum, ImageStatusEnum, ImageVisibilityEnum
from app.schemas.character_image import CharacterImageRead
from app.services.image_provider import get_image_provider, get_fallback_provider, is_moderation_block
from app.services.image_quota import check_weekly_quota
from app.services.stub_image_generator import generate_placeholder_png
from app.services.style_elements import apply_style_elements_to_image_prompt
from app.services.body_canon import load_markings, build_body_canon_lock_string

logger = logging.getLogger(__name__)

router = APIRouter()

_VALID_STYLES = {"realistic", "anime", "cartoon", "illustration", "comic", "pixel"}

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"

_PROVIDER_PROMPT_CAP = 500

# Prepended to the prompt when a face-reference image is used as grounding seed.
# Tells the model to preserve only facial identity, not outfit/pose from the reference.
_FACE_REF_INSTRUCTION = (
    "Use the reference image ONLY for facial identity. "
    "Do NOT copy clothing; outfit must follow the scene prompt. "
)


# ── Request / helpers ────────────────────────────────────────────────

class SceneImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/scene-images/generate."""
    prompt: str = Field(..., min_length=1, max_length=800)
    style: str = "realistic"

    @field_validator("style")
    @classmethod
    def _coerce_style(cls, v: str) -> str:
        normed = v.strip().lower()
        return normed if normed in _VALID_STYLES else "realistic"




def _is_moderation_block(exc: BaseException) -> bool:
    return is_moderation_block(exc)


def _v2_canon_front_url(character_id: int, db: Session) -> str | None:
    """Front identity reference from a fully-locked v2 canon, or None.

    v2 characters carry no legacy identity_anchor_json — their identity truth is
    the CharacterIdentityCanon. Returns the face-front reference URL only when the
    canon is fully locked AND has both a face_front and body_front image (a valid
    v2 identity), so scene generation can ground on it (S24AU.3). Returns None for
    legacy/unlocked/incomplete canons, letting the caller fall back to anchors.
    """
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.services import canon_service as cs

    canon = (
        db.query(CharacterIdentityCanon)
        .filter(CharacterIdentityCanon.character_id == character_id)
        .first()
    )
    if canon is None or not (canon.face_locked and canon.body_locked):
        return None
    face = cs.load_face_canon(canon)
    body = cs.load_body_canon(canon)
    face_url = face.face_front_image_url if face else None
    body_url = body.body_front_image_url if body else None
    if not (face_url and body_url):
        return None
    return face_url


# ── Endpoint ─────────────────────────────────────────────────────────

@router.post(
    "/{character_id}/scene-images/generate",
    response_model=CharacterImageRead,
    summary="Generate a scene image anchored to the character's locked identity",
)
def generate_scene_image(
    character_id: int,
    body: SceneImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CharacterImageRead:
    """Generate a single scene image for a locked character.

    Uses the character's front anchor as a reference image when possible,
    falling back to text-only generation and finally to a stub placeholder.
    """
    # ── Auth + ownership ──────────────────────────────────────────
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to modify this character.")

    # ── S24AZ T2-C: weekly image allowance (admins bypass; deducted on success) ──
    # Scene images call the paid Google Gemini API; they must consume the same
    # rolling 7-day quota as the other image generators. Deduction happens by
    # stamping user_id on the saved CharacterImage below (counted by image_quota).
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Preconditions ─────────────────────────────────────────────
    if not character.visual_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Lock your character's identity before generating scene images.",
        )

    # Identity reference may come from either source: legacy identity_anchor_json
    # OR a fully-locked v2 canon (S24AU.3). Require at least one.
    anchor_data = _parse_anchor_json(character.identity_anchor_json)
    v2_front_url = _v2_canon_front_url(character_id, db)
    if anchor_data is None and v2_front_url is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="We couldn't find your character's identity reference. Please complete and lock the character's identity.",
        )
    # Normalise so the legacy-shaped .get() calls below stay safe on the v2 path.
    anchor_data = anchor_data or {}

    # Generation source: prefer the v2 canon reference when present; the legacy
    # front anchor is the fallback (Task 4).
    legacy_front = anchor_data.get("anchors", {}).get("front")
    legacy_front_url = legacy_front.get("url") if legacy_front else None
    front_url: str | None = v2_front_url or legacy_front_url

    # ── Build prompt ──────────────────────────────────────────────
    identity_lock = anchor_data.get("identity_lock_string") or ""
    identity_hash = anchor_data.get("identity_prompt_hash")
    style = body.style

    # ── Body canon — append to identity lock ──────────────────────
    # Persistent anatomical markings are part of the identity layer,
    # not conditional style modifiers.
    body_canon_str = build_body_canon_lock_string(load_markings(character))
    if body_canon_str:
        identity_lock = f"{identity_lock}, {body_canon_str}" if identity_lock else body_canon_str

    # ── Style Shops element injection (hair + removables only) ────
    # Tattoos and scars are now in body_canon — not injected here.
    enriched_user_prompt = apply_style_elements_to_image_prompt(character, body.prompt, db)

    # Combine enriched prompt + identity lock (includes body canon)
    if identity_lock:
        combined = f"{enriched_user_prompt}, {identity_lock}"
        if len(combined) > 800:
            budget = 800 - len(enriched_user_prompt) - 2
            combined = f"{enriched_user_prompt}, {identity_lock[:max(budget, 0)]}" if budget > 0 else enriched_user_prompt
    else:
        combined = enriched_user_prompt

    # Provider prompt capped at 500 chars
    provider_prompt = combined[:_PROVIDER_PROMPT_CAP]

    # ── Resolve front anchor URL for reference-image edits ────────
    front_ref_url: str | None = None
    if front_url:
        # Convert stored path to a full URL the provider can download
        if front_url.startswith("/static/"):
            base = settings.BACKEND_PUBLIC_URL.rstrip("/")
            front_ref_url = f"{base}{front_url}"
        elif front_url.startswith("http"):
            front_ref_url = front_url

    # ── Resolve face reference bytes from DB ──────────────────────
    # Prefer identity_face_ref (tight head crop) over front anchor for grounding.
    # Face ref gives the provider a face-only cue so it preserves identity without
    # copying outfit or pose from the anchor image.
    face_ref_bytes: bytes | None = None
    face_ref_img = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .order_by(CharacterImage.created_at.desc())
        .first()
    )
    if face_ref_img is not None:
        try:
            face_ref_bytes = load_image_bytes(face_ref_img.file_path)
        except Exception:
            logger.warning(
                "scene_image face_ref_load_failed character_id=%s", character_id
            )

    # v2 fallback (S24AU.3): v2 characters have no IDENTITY_FACE_REF row — ground
    # Tier A on the locked v2 canon front reference instead so identity holds.
    if face_ref_bytes is None and v2_front_url:
        try:
            face_ref_bytes = load_image_bytes(v2_front_url)
        except Exception:
            logger.warning(
                "scene_image v2_face_ref_load_failed character_id=%s", character_id
            )

    # ── Generate image (tiered fallback) ──────────────────────────
    provider_name = "stub"
    used_anchor = False
    used_face_ref = False

    try:
        provider = get_image_provider()
        logger.info("image_provider provider=%s context=scene", settings.IMAGE_PROVIDER.lower())
    except (RuntimeError, ValueError):
        provider = None

    png_bytes: bytes | None = None

    # Inject face signature into Tier A prompt when available.
    # Placed before the user prompt so the model sees identity constraints first.
    _face_sig_text = (anchor_data.get("face_signature") or {}).get("text", "")
    _face_sig_prefix = (
        f"FACE SIGNATURE (canonical): {_face_sig_text}. " if _face_sig_text else ""
    )

    # DIAG: full identity payload snapshot before provider call
    _diag_spec_hair: dict = {}
    if character.identity_spec_json:
        try:
            _sd = _json.loads(character.identity_spec_json)
            _id = _sd.get("identity") or {}
            _diag_spec_hair = {
                "hair_color": _id.get("hair_color"),
                "hair_length": _id.get("hair_length"),
                "hair_style": _sd.get("hair_style"),
                "hair_texture": _sd.get("hair_texture"),
                "hairline_type": _sd.get("hairline_type"),
            }
        except Exception:
            pass
    _HAIR_PATTERNS = ["long hair", "shoulder-length", "shoulder length", "flowing hair",
                      "ponytail", "tied back", "waist-length", "waist length"]
    _kw_hits = [p for p in _HAIR_PATTERNS if p in provider_prompt.lower()]
    logger.info(
        "DIAG scene_identity_payload character_id=%s provider=%s "
        "lock_string=%r spec_hair=%s face_ref_available=%s "
        "provider_prompt_len=%d hair_kw_hits=%s",
        character_id, settings.IMAGE_PROVIDER.lower(),
        (identity_lock or "")[:120],
        _diag_spec_hair,
        face_ref_bytes is not None,
        len(provider_prompt),
        _kw_hits,
    )
    if _kw_hits:
        logger.warning(
            "DIAG hair_keyword_in_scene_prompt character_id=%s hits=%s snippet=%r",
            character_id, _kw_hits, provider_prompt[:200],
        )

    # Tier A: grounded generation from face reference (facial identity only)
    if provider is not None and face_ref_bytes is not None:
        grounded_prompt = f"{_face_sig_prefix}{_FACE_REF_INSTRUCTION}{provider_prompt}"
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=grounded_prompt,
                reference_image_bytes=face_ref_bytes,
            )
            provider_name = settings.IMAGE_PROVIDER.lower()
            used_anchor = True
            used_face_ref = True
        except (ValueError, RuntimeError, NotImplementedError):
            logger.info(
                "scene_image face_ref_grounded_failed character_id=%s, falling back",
                character_id,
            )

    # Tier B: edit with front anchor URL (preserves full identity but may copy outfit)
    if png_bytes is None and provider is not None and front_ref_url:
        try:
            png_bytes = provider.generate_image(
                prompt=provider_prompt,
                reference_image_url=front_ref_url,
            )
            provider_name = settings.IMAGE_PROVIDER.lower()
            used_anchor = True
        except (ValueError, RuntimeError, NotImplementedError):
            logger.info("scene_image edit_failed character_id=%s, falling back to text-to-image", character_id)

    # Tier C: text-to-image via primary provider
    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=provider_prompt)
            provider_name = settings.IMAGE_PROVIDER.lower()
        except (ValueError, RuntimeError):
            logger.info("scene_image text_to_image_failed character_id=%s, trying fallback", character_id)

    # Tier C: fallback provider (fal.ai)
    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=provider_prompt)
                provider_name = "fal"
            except (ValueError, RuntimeError):
                logger.info("scene_image fallback_failed character_id=%s, using stub", character_id)

    # Tier D: stub placeholder
    if png_bytes is not None:
        file_path = save_image(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=f"{character.name} — scene",
            sublabel=body.prompt[:80],
            role="generated",
        )
        provider_name = "stub"

    # ── Save CharacterImage ───────────────────────────────────────
    # Identity OS Beta: scene images are SCENE_ONLY by default.
    # They do not contaminate canon. Promotion is explicit via promote_to_canon.
    img = CharacterImage(
        character_id=character_id,
        # Owner, not requester. This route is owner-only (403 above), so the
        # two are the same account; naming the owner states the rule. The
        # weekly quota still counts this column — see the note on
        # ``CharacterImage.user_id`` about that legacy accounting.
        user_id=character.owner_id,
        kind=ImageKindEnum.SCENE_ONLY,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json={
            "library": True,
            "scene": True,
            "scene_only": True,
            "prompt": body.prompt,
            "style": style,
            "used_anchor": used_anchor,
            "used_face_ref": used_face_ref,
            "identity_hash": identity_hash,
        },
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    return CharacterImageRead.model_validate(img)


# ── Promote-to-Canon endpoint ────────────────────────────────────────

# Allowed promotion targets — must specify what canon layer is being promoted.
_VALID_PROMOTION_TARGETS = frozenset({
    "face_canon",     # promote as face identity reference
    "body_canon",     # promote as body/anatomy reference
    "final_card",     # promote as final character card (support only)
    "accessory_fit",  # promote as accessory fit reference
})

# Target → new ImageKindEnum value
_PROMOTION_TARGET_KIND: dict[str, ImageKindEnum] = {
    "face_canon": ImageKindEnum.ANCHOR_FRONT,
    "body_canon": ImageKindEnum.IDENTITY_BODY_FRONT,
    "final_card": ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
    "accessory_fit": ImageKindEnum.ACCESSORY_FIT,
}


class PromoteToCanonRequest(BaseModel):
    """Request body for POST /characters/{id}/images/{image_id}/promote-to-canon."""
    target: str = Field(
        ...,
        description=(
            "What canon layer to promote to: "
            "face_canon | body_canon | final_card | accessory_fit"
        ),
    )


class PromoteToCanonResponse(BaseModel):
    image_id: int
    previous_kind: str
    new_kind: str
    target: str


@router.post(
    "/{character_id}/images/{image_id}/promote-to-canon",
    response_model=PromoteToCanonResponse,
    summary="Explicitly promote a scene image to a canon layer",
)
def promote_to_canon(
    character_id: int,
    image_id: int,
    body: PromoteToCanonRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PromoteToCanonResponse:
    """Explicitly promote a scene image to a canon layer.

    Scene images are SCENE_ONLY by default — they do not contaminate canon.
    Promotion is the ONLY way a generated image becomes part of canon.
    The caller must choose which canon layer is being promoted.
    """
    if body.target not in _VALID_PROMOTION_TARGETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid target {body.target!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_PROMOTION_TARGETS))}"
            ),
        )

    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )

    img = db.query(CharacterImage).filter(
        CharacterImage.id == image_id,
        CharacterImage.character_id == character_id,
    ).first()
    if not img:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found.")

    previous_kind = img.kind.value if hasattr(img.kind, "value") else str(img.kind)
    new_kind = _PROMOTION_TARGET_KIND[body.target]
    img.kind = new_kind

    # Stamp promotion in metadata so audit trail is preserved
    meta = dict(img.metadata_json or {})
    meta["promoted_to_canon"] = True
    meta["promotion_target"] = body.target
    meta["scene_only"] = False
    img.metadata_json = meta

    db.commit()
    db.refresh(img)

    logger.info(
        "promote_to_canon image_id=%s character_id=%s target=%s "
        "previous_kind=%s new_kind=%s",
        image_id, character_id, body.target, previous_kind, new_kind.value,
    )

    return PromoteToCanonResponse(
        image_id=image_id,
        previous_kind=previous_kind,
        new_kind=new_kind.value,
        target=body.target,
    )


def _parse_anchor_json(raw: str | None) -> dict | None:
    """Parse identity_anchor_json, returning None if missing/invalid or has no front anchor."""
    if not raw:
        return None
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return None
    # Must have anchors.front.url at minimum
    front = (data.get("anchors") or {}).get("front")
    if not front or not front.get("url"):
        return None
    return data
