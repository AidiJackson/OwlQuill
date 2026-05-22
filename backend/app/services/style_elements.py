"""Style Elements service — prompt injection for Style Shop elements.

Scope after body-canon migration:
  PERMANENT BARBER  — hair tokens, always injected (compact).
  REMOVABLE         — masks, jewellery, weapons; trigger-based injection.

Tattoos and scars are no longer handled here. They live in body_canon_json
on the Character and are compiled into the identity lock string at generation
time via app.services.body_canon.
"""
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character import Character as CharacterModel
from app.models.style_shop import (
    AttachmentModeEnum,
    CharacterStyleElement,
    PlacementEnum,
    ShopTypeEnum,
    StyleElementStatusEnum,
    StylePreset,
)

logger = logging.getLogger(__name__)

# ── Neck-context signals — jewellery auto-inject for NECK placements ─
# "portrait" removed: too broad — fires on "portrait in a black jacket"
# where the jacket covers the neck. Only retain signals that reliably
# expose the collarbone / neck area.

_NECK_CONTEXT_SIGNALS = frozenset({
    "close-up", "closeup", "close up", "headshot", "face shot",
    "upper body", "chest up", "chest-up", "waist up", "waist-up",
    "half body", "half-body", "bust", "shoulder",
})

# ── Removable trigger keywords by shop type ───────────────────────────

_MASK_TRIGGERS = frozenset({
    "mask", "masked", "wearing mask", "wearing his mask", "wearing her mask",
    "phantom", "demon wolf", "demon wolf mask", "lower-face mask", "lower face mask",
    "face mask", "urban phantom",
})

_JEWELLERY_TRIGGERS = frozenset({
    "necklace", "chain", "jewellery", "jewelry", "ring", "signet ring",
    "bracelet", "cross necklace", "silver chain", "wearing jewellery",
    "accessories",
})

_WEAPON_TRIGGERS = frozenset({
    "weapon", "gun", "pistol", "handgun", "revolver", "knife", "blade",
    "katana", "sword", "armed", "holding a", "wielding", "draws",
    "pulls out",
})

_SHOP_TRIGGERS: dict[ShopTypeEnum, frozenset] = {
    ShopTypeEnum.MASK: _MASK_TRIGGERS,
    ShopTypeEnum.JEWELLERY: _JEWELLERY_TRIGGERS,
    ShopTypeEnum.WEAPON: _WEAPON_TRIGGERS,
}

# ── Placement enforcement suffixes ────────────────────────────────────
# Full-form used in build_style_injection() for verbose/DIAG output.
# Compact-form used in injection tokens — short parenthetical so they
# remain modifiers and do not become composition subjects.

_PLACEMENT_ENFORCEMENT: dict[PlacementEnum, str] = {
    PlacementEnum.RIGHT_ARM: (
        " Visible on the character's right arm. Not mirrored, not moved to the left arm."
    ),
    PlacementEnum.LEFT_ARM: (
        " Visible on the character's left arm. Not mirrored, not moved to the right arm."
    ),
    PlacementEnum.NECK: (
        " Visible around the neck, above the shirt collar."
    ),
    PlacementEnum.LOWER_FACE: (
        " Worn on the lower face only. Eyes and forehead remain visible."
    ),
    PlacementEnum.FACE: (
        " Covering the face. Eyes visible through cutouts."
    ),
}

_COMPACT_PLACEMENT: dict[PlacementEnum, str] = {
    PlacementEnum.RIGHT_ARM: " (right arm, not mirrored)",
    PlacementEnum.LEFT_ARM: " (left arm, not mirrored)",
    PlacementEnum.NECK: " (neck)",
    PlacementEnum.LOWER_FACE: " (lower face, eyes visible)",
    PlacementEnum.FACE: " (full face, eyes through cutouts)",
}


def get_active_style_elements(character_id: int, db: Session) -> list[CharacterStyleElement]:
    """Return all active CharacterStyleElement rows with their presets loaded."""
    return (
        db.query(CharacterStyleElement)
        .join(StylePreset)
        .filter(
            CharacterStyleElement.character_id == character_id,
            CharacterStyleElement.status == StyleElementStatusEnum.ACTIVE,
            StylePreset.is_active.is_(True),
        )
        .order_by(StylePreset.sort_order, CharacterStyleElement.id)
        .all()
    )


def _prompt_contains(prompt_lower: str, signals: frozenset) -> bool:
    return any(sig in prompt_lower for sig in signals)


def _build_token(element: CharacterStyleElement) -> str:
    """Build full verbose token with placement enforcement (used for DIAG)."""
    token = element.preset.prompt_token
    suffix = _PLACEMENT_ENFORCEMENT.get(element.placement, "")
    return (token + suffix).strip()


def _build_compact_token(element: CharacterStyleElement) -> str:
    """Build a compact scene-subordinate modifier token.

    Takes only the first comma-clause of the preset prompt_token so the
    injected text reads as a short modifier rather than a composition subject.
    Placement constraint appended as a parenthetical to preserve anti-drift
    without adding sentence weight.
    """
    first_clause = element.preset.prompt_token.split(",")[0].strip()
    suffix = _COMPACT_PLACEMENT.get(element.placement, "")
    return (first_clause + suffix).strip()


def _removable_triggered(element: CharacterStyleElement, prompt_lower: str) -> bool:
    """Return True if a removable element is referenced in the prompt."""
    shop_type = element.preset.shop_type
    triggers = _SHOP_TRIGGERS.get(shop_type, frozenset())
    if _prompt_contains(prompt_lower, triggers):
        return True
    # Exact preset name match
    if element.preset.name.lower() in prompt_lower:
        return True
    return False


def _jewellery_neck_context_trigger(element: CharacterStyleElement, prompt_lower: str) -> bool:
    """Auto-inject neck jewellery when the neck/collarbone area is visibly exposed.

    Only fires for NECK-placed jewellery — rings/bracelets (HAND placement)
    require explicit prompt reference via _removable_triggered instead.
    """
    if element.preset.shop_type != ShopTypeEnum.JEWELLERY:
        return False
    if element.placement != PlacementEnum.NECK:
        return False
    return _prompt_contains(prompt_lower, _NECK_CONTEXT_SIGNALS)


def build_style_injection(
    character: CharacterModel,
    user_prompt: str,
    db: Session,
) -> tuple[list[str], list[str], list[str], bool]:
    """Compute all style tokens for a prompt.

    Returns:
        permanent_tokens   — hair, always included
        conditional_tokens — removables triggered by prompt
        skipped_slugs      — elements not triggered
        tattoo_hint_added  — always False (kept for API compat; tattoos are body canon)
    """
    elements = get_active_style_elements(character.id, db)
    prompt_lower = user_prompt.lower()

    permanent_tokens: list[str] = []
    conditional_tokens: list[str] = []
    skipped: list[str] = []

    for el in elements:
        mode = el.preset.attachment_mode
        shop = el.preset.shop_type

        if mode == AttachmentModeEnum.PERMANENT and shop == ShopTypeEnum.BARBER:
            permanent_tokens.append(_build_token(el))

        elif mode == AttachmentModeEnum.REMOVABLE:
            if _jewellery_neck_context_trigger(el, prompt_lower):
                conditional_tokens.append(_build_token(el))
            elif _removable_triggered(el, prompt_lower):
                conditional_tokens.append(_build_token(el))
            else:
                skipped.append(el.preset.slug)

    return permanent_tokens, conditional_tokens, skipped, False


def apply_style_elements_to_image_prompt(
    character: CharacterModel, user_prompt: str, db: Session,
    include_permanent: bool = True,
) -> str:
    """Build a style-enriched prompt with user scene prioritised over style modifiers.

    Assembly order:
      1. User scene / environment / clothing prompt  ← highest priority
      2. Hair canon token (compact, appended only when include_permanent=True)
      3. Triggered removable style modifiers (mask, jewellery, weapon)

    Tattoos and scars are handled at the identity-lock layer via body_canon_json,
    not injected here.

    include_permanent=False skips permanent (barber/hair) tokens. Use this when
    include_character=True so the identity lock string's hair spec is authoritative
    and permanent tokens don't create conflicting signals that cause drift.
    """
    elements = get_active_style_elements(character.id, db)
    prompt_lower = user_prompt.lower()

    hair_tokens: list[str] = []
    style_tokens: list[str] = []
    skipped: list[str] = []

    for el in elements:
        mode = el.preset.attachment_mode
        shop = el.preset.shop_type

        if mode == AttachmentModeEnum.PERMANENT and shop == ShopTypeEnum.BARBER:
            if include_permanent:
                hair_tokens.append(_build_compact_token(el))
            else:
                skipped.append(el.preset.slug + " [skipped:identity_mode]")

        elif mode == AttachmentModeEnum.REMOVABLE:
            if _jewellery_neck_context_trigger(el, prompt_lower):
                style_tokens.append(_build_compact_token(el))
            elif _removable_triggered(el, prompt_lower):
                style_tokens.append(_build_compact_token(el))
            else:
                skipped.append(el.preset.slug)

    # ── Assemble: scene FIRST, then compact style modifiers ───────────
    all_style = hair_tokens + style_tokens
    final_prompt = user_prompt

    if all_style:
        style_block = ", ".join(all_style)
        final_prompt = f"{user_prompt}, {style_block}"

    # ── DIAG ─────────────────────────────────────────────────────────
    logger.info(
        "STYLE-ELEMENTS character_id=%s include_permanent=%s "
        "scene=%r hair_tokens=%s style_tokens=%s "
        "skipped=%s final_len=%d final=%r",
        character.id,
        include_permanent,
        user_prompt[:120],
        hair_tokens,
        style_tokens,
        skipped,
        len(final_prompt),
        final_prompt[:300],
    )

    return final_prompt


def patch_identity_spec_with_hair(
    character: CharacterModel, spec_patch: dict
) -> Optional[str]:
    """Patch hair fields in character.identity_spec_json and return updated JSON string.

    Returns None if identity_spec_json is not set (no spec to patch).
    """
    if not character.identity_spec_json:
        return None

    try:
        spec_data = json.loads(character.identity_spec_json)
    except (ValueError, TypeError):
        return None

    for field in ("hair_style", "hair_texture"):
        if field in spec_patch:
            spec_data[field] = spec_patch[field]

    if "identity" not in spec_data or spec_data["identity"] is None:
        spec_data["identity"] = {}
    for field in ("hair_color", "hair_length"):
        if field in spec_patch:
            spec_data["identity"][field] = spec_patch[field]

    return json.dumps(spec_data)


# ── Business rule enforcement ─────────────────────────────────────────

MAX_REMOVABLE_ACTIVE = 3


def count_active_removable(character_id: int, db: Session) -> int:
    return (
        db.query(CharacterStyleElement)
        .join(StylePreset)
        .filter(
            CharacterStyleElement.character_id == character_id,
            CharacterStyleElement.status == StyleElementStatusEnum.ACTIVE,
            StylePreset.attachment_mode == AttachmentModeEnum.REMOVABLE,
        )
        .count()
    )


def get_active_element_for_placement(
    character_id: int, placement: PlacementEnum, shop_type: ShopTypeEnum, db: Session
) -> Optional[CharacterStyleElement]:
    """Return the active element for a given placement + shop_type combo, if any."""
    return (
        db.query(CharacterStyleElement)
        .join(StylePreset)
        .filter(
            CharacterStyleElement.character_id == character_id,
            CharacterStyleElement.status == StyleElementStatusEnum.ACTIVE,
            CharacterStyleElement.placement == placement,
            StylePreset.shop_type == shop_type,
        )
        .first()
    )
