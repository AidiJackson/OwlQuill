"""Style Shops API endpoints."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.character import Character as CharacterModel
from app.models.style_shop import (
    AttachmentModeEnum,
    CharacterStyleElement,
    PlacementEnum,
    ShopTypeEnum,
    StyleElementStatusEnum,
    StylePreset,
)
from app.models.user import User
from app.schemas.style_shop import (
    ApplyStyleElementRequest,
    StyleElementRead,
    StyleElementsResponse,
    StylePresetRead,
)
from app.services.pack_version import increment_pack_version, mark_slots_stale
from app.services.style_elements import (
    MAX_REMOVABLE_ACTIVE,
    count_active_removable,
    get_active_element_for_placement,
    get_active_style_elements,
    patch_identity_spec_with_hair,
)


logger = logging.getLogger(__name__)

router = APIRouter()


# ── GET /style-shops/presets ──────────────────────────────────────────

@router.get(
    "/style-shops/presets",
    response_model=list[StylePresetRead],
    summary="List all active style shop presets",
)
def list_presets(
    shop_type: Optional[ShopTypeEnum] = Query(None),
    placement: Optional[PlacementEnum] = Query(None),
    db: Session = Depends(get_db),
) -> list[StylePresetRead]:
    q = db.query(StylePreset).filter(StylePreset.is_active.is_(True))
    if shop_type:
        q = q.filter(StylePreset.shop_type == shop_type)
    if placement:
        q = q.filter(StylePreset.placement == placement)
    presets = q.order_by(StylePreset.shop_type, StylePreset.sort_order).all()
    logger.debug(
        "STYLE-SHOPS-DIAG list_presets shop_type=%s placement=%s count=%d",
        shop_type, placement, len(presets),
    )
    return [StylePresetRead.model_validate(p) for p in presets]


# ── GET /characters/{character_id}/style-elements ─────────────────────

@router.get(
    "/characters/{character_id}/style-elements",
    response_model=StyleElementsResponse,
    summary="List active style elements on a character",
)
def list_style_elements(
    character_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StyleElementsResponse:
    character = _get_owned_character(character_id, current_user, db)
    elements = get_active_style_elements(character.id, db)
    return StyleElementsResponse(
        character_id=character_id,
        elements=[StyleElementRead.model_validate(e) for e in elements],
    )


# ── POST /characters/{character_id}/style-elements ────────────────────

@router.post(
    "/characters/{character_id}/style-elements",
    response_model=StyleElementsResponse,
    summary="Apply a style preset to a character",
)
def apply_style_element(
    character_id: int,
    body: ApplyStyleElementRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StyleElementsResponse:
    character = _get_owned_character(character_id, current_user, db)

    preset = db.query(StylePreset).filter(
        StylePreset.id == body.preset_id,
        StylePreset.is_active.is_(True),
    ).first()
    if not preset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preset not found.")

    effective_placement = body.placement or preset.placement

    # ── Business rules ─────────────────────────────────────────────────

    if preset.attachment_mode == AttachmentModeEnum.REMOVABLE:
        # Max 3 removable active at once
        current_count = count_active_removable(character_id, db)
        existing = get_active_element_for_placement(
            character_id, effective_placement, preset.shop_type, db
        )
        if existing is None and current_count >= MAX_REMOVABLE_ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Maximum {MAX_REMOVABLE_ACTIVE} removable style elements already active. Archive one first.",
            )

    elif preset.attachment_mode == AttachmentModeEnum.PERMANENT:
        # One active per shop_type+placement combo — archive the old one
        existing = get_active_element_for_placement(
            character_id, effective_placement, preset.shop_type, db
        )
        if existing:
            if existing.preset_id == body.preset_id:
                # Already applied — idempotent
                elements = get_active_style_elements(character.id, db)
                return StyleElementsResponse(
                    character_id=character_id,
                    elements=[StyleElementRead.model_validate(e) for e in elements],
                )
            existing.status = StyleElementStatusEnum.ARCHIVED
            db.flush()

    # ── Apply ──────────────────────────────────────────────────────────

    new_element = CharacterStyleElement(
        character_id=character_id,
        preset_id=preset.id,
        placement=effective_placement,
        status=StyleElementStatusEnum.ACTIVE,
    )
    db.add(new_element)

    # ── Identity spec patch for permanent hair ─────────────────────────

    _spec_patched = False
    if preset.attachment_mode == AttachmentModeEnum.PERMANENT and preset.shop_type == ShopTypeEnum.BARBER:
        if preset.spec_patch_json:
            try:
                spec_patch = json.loads(preset.spec_patch_json)
                updated_spec = patch_identity_spec_with_hair(character, spec_patch)
                if updated_spec:
                    character.identity_spec_json = updated_spec
                    _spec_patched = True
                    logger.info(
                        "style_shop hair_spec_patched character_id=%s preset=%s",
                        character_id, preset.slug,
                    )
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "style_shop spec_patch_failed character_id=%s preset=%s error=%r",
                    character_id, preset.slug, str(exc),
                )

    # Style-shop tattoo items no longer auto-promote to body canon.
    # Body canon is managed exclusively through /identity-canon routes.
    # Tattoo style elements remain as styling records only.

    # ── Pack version increment + slot invalidation ─────────────────────
    # Increment once per canonical mutation, then mark affected slots stale.
    # Priority order: spec patch > tattoo (body_canon) > other permanent elements.
    # Removable elements reach none of these branches — state unchanged.
    if _spec_patched:
        increment_pack_version(character, reason="identity_spec_mutation")
        mark_slots_stale(character, "identity_spec_mutation")
    elif preset.shop_type == ShopTypeEnum.TATTOO:
        increment_pack_version(character, reason="body_canon_mutation")
        mark_slots_stale(character, "body_canon_mutation")
    elif preset.attachment_mode == AttachmentModeEnum.PERMANENT:
        increment_pack_version(character, reason="permanent_style_element")
        mark_slots_stale(
            character,
            "permanent_style_element",
            placement=effective_placement.value,
        )

    db.commit()

    logger.info(
        "STYLE-ELEMENTS applied character_id=%s preset=%s placement=%s mode=%s",
        character_id, preset.slug, effective_placement, preset.attachment_mode,
    )

    elements = get_active_style_elements(character.id, db)
    return StyleElementsResponse(
        character_id=character_id,
        elements=[StyleElementRead.model_validate(e) for e in elements],
    )


# ── DELETE /characters/{character_id}/style-elements/{element_id} ─────

@router.delete(
    "/characters/{character_id}/style-elements/{element_id}",
    response_model=StyleElementsResponse,
    summary="Archive (remove) a style element from a character",
)
def archive_style_element(
    character_id: int,
    element_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StyleElementsResponse:
    character = _get_owned_character(character_id, current_user, db)

    element = db.query(CharacterStyleElement).filter(
        CharacterStyleElement.id == element_id,
        CharacterStyleElement.character_id == character.id,
    ).first()
    if not element:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Style element not found.")

    element.status = StyleElementStatusEnum.ARCHIVED
    db.commit()

    logger.info(
        "STYLE-ELEMENTS archived character_id=%s element_id=%s",
        character_id, element_id,
    )

    elements = get_active_style_elements(character.id, db)
    return StyleElementsResponse(
        character_id=character_id,
        elements=[StyleElementRead.model_validate(e) for e in elements],
    )


# ── Helper ─────────────────────────────────────────────────────────────

def _get_owned_character(
    character_id: int, current_user: User, db: Session
) -> CharacterModel:
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this character.",
        )
    return character
