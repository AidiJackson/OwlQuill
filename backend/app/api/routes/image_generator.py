"""Simplified image generator endpoint with provider toggle (B17).

Replaces the mental model of 'scene generator' with a plain image generator:
  - Always tied to a character for ownership/auth
  - include_character controls whether identity references are injected
  - provider_option selects the backend provider (option1=OpenAI, option2=Google)

B18: Strict identity mode is automatically enabled when include_character=True.
  - Blocks silent fallback to plain generic generation or stub placeholder
  - Allows at most one retry with escalated wording before controlled failure

B19: Anchor-image conditioning.
  - Loads identity pack images (front, three-quarter, torso, full-body) from disk
  - Passes them as real provider inputs via generate_with_anchors when supported
  - Falls back to single-image grounded generation (face-ref crop) when not
  - Tightens the strict identity text wrapper to be short and punchy
"""
import json as _json
import logging
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.storage import save_image, load_image_bytes
from app.models.user import User
from app.services.image_quota import check_weekly_quota
from app.models.character import Character as CharacterModel
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.character_image import CharacterImageRead
from app.services.image_provider import get_provider_for_option, get_fallback_provider
from app.services.stub_image_generator import generate_placeholder_png
from app.services.character_accessory import build_accessory_prompt_block, get_triggered_accessory
from app.services.style_elements import apply_style_elements_to_image_prompt
from app.services.body_canon import (
    load_markings,
    build_compact_token,
    build_body_canon_lock_string,
    build_passive_body_canon_string,
    build_arm_side_binding_str,
    build_short_arm_side_str,
    is_sleeve_marking,
    get_arm_side,
    build_sleeve_enforcement_str,
    sync_tattoo_style_elements_to_body_canon,
)
from app.api.routes.body_identity import _load_body_slots
from app.services.body_identity_refs import get_body_identity_references
from app.services.identity_evolution import compute_pack_stages

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERATED_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "generated"

# B17 provider option → internal provider name (not exposed to end users).
_OPTION_PROVIDER_NAMES: dict[str, str] = {
    "option1": "openai",
    "option2": "google",
}

# ── B18/B19 strict identity prompt constants ──────────────────────────
# Shorter, punchier wording — actual images carry the visual identity;
# the text wrapper confirms the requirement without bloat.

_STRICT_IDENTITY_PREFIX = (
    "The subject must be the same person as the reference images. "
    "Match their exact face shape, nose, jaw, and eye shape precisely. "
    "Preserve facial structure, hair, and body build. "
    "Do not use a generic or average face. Do not generate a different person."
)

_STRICT_IDENTITY_RETRY_PREFIX = (
    "CRITICAL: Reproduce the exact person from the reference images only. "
    "Same face shape, jaw, nose, eye shape, hair, and build. "
    "No generic or average faces. No substitution permitted."
)

# Preferred anchor load order: widest-identity coverage first
_ANCHOR_LOAD_ORDER = ("front", "three_quarter", "torso", "full_body")

# ── Cover-generation prompt directives ────────────────────────────────
#
# _COVER_BANNER_PREFIX   — always prepended when is_cover=True (~225 chars).
# _COVER_CHARACTER_FRAMING — appended additionally when is_cover=True AND
#                            include_character=True (~140 chars).
#
# Combined budget: up to ~365 chars of cover instructions.
# When include_character=True, _build_strict_identity_prompt wraps the result;
# cover instructions travel at the tail of the prompt where image models weight them well.

_COVER_BANNER_PREFIX = (
    "PROFILE HEADER BANNER — ultra-wide 2.84:1 panoramic ratio. Not a portrait, not centered. "
    "COMPOSITION: subject in LEFT THIRD only. "
    "RIGHT two-thirds: open background, sky, or environment — no subject there. "
    "Full face and head completely visible. No head or face cropping. "
    "Intentional website profile banner layout. "
)

# Applied additionally when the character is included in the cover image.
# Enforces medium-shot framing so the face is reliably visible at banner scale.
_COVER_CHARACTER_FRAMING = (
    "CHARACTER: chest-up or waist-up framing. Full face clearly visible. No full-body shot. "
)

# Used for the single deterministic retry issued when a character-inclusive
# cover is generated. The retry escalates framing language and re-anchors
# the composition rule to give the model a second chance at banner layout.
# Kept to ~230 chars — travels comfortably inside _build_strict_identity_prompt.
_COVER_RETRY_PROMPT = (
    "COVER RETRY — PROFILE HEADER BANNER, ultra-wide 2.84:1. "
    "Subject in LEFT THIRD, chest-up or waist-up ONLY, full face visible. "
    "Right two-thirds: open background — no subject. "
    "No full-body shot. No face crop. Intentional banner layout. "
)


# ── Request schema ────────────────────────────────────────────────────


class ImageGenerateRequest(BaseModel):
    """Request body for POST /characters/{id}/image-generator/generate."""

    prompt: str = Field(..., min_length=1, max_length=800)
    include_character: bool = False
    provider_option: Literal["option1", "option2"] = "option1"
    is_cover: bool = False  # When True, saves with kind=COVER for use as a character cover banner


# ── Helpers ───────────────────────────────────────────────────────────


def _parse_anchor_json(raw: str | None) -> dict | None:
    """Parse identity_anchor_json; return None if missing, invalid, or has no front anchor."""
    if not raw:
        return None
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return None
    front = (data.get("anchors") or {}).get("front")
    if not front or not front.get("url"):
        return None
    return data


def _build_anchor_data_from_db(character_id: int, db: Session) -> dict | None:
    """Legacy compatibility: rebuild anchor_data from active anchor image rows.

    Characters locked before the identity_anchor_json field was introduced
    (pre-Feb 2026) may have valid anchor images in the DB but a null
    identity_anchor_json on the character record.  This helper reconstructs
    the minimal dict expected by _load_anchor_images so generation can proceed
    without requiring the user to re-lock their character.

    Returns None when no ANCHOR_FRONT image is found — that means the character
    genuinely has no usable anchors and must regenerate the identity pack.
    """
    kind_to_key = {
        ImageKindEnum.ANCHOR_FRONT: "front",
        ImageKindEnum.ANCHOR_THREE_QUARTER: "three_quarter",
        ImageKindEnum.ANCHOR_TORSO: "torso",
        ImageKindEnum.ANCHOR_FULL_BODY: "full_body",
    }

    rows = (
        db.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character_id,
            CharacterImage.kind.in_(list(kind_to_key.keys())),
            CharacterImage.status == ImageStatusEnum.ACTIVE,
        )
        .all()
    )

    if not rows:
        return None

    anchors_dict: dict[str, dict] = {}
    for img in rows:
        key = kind_to_key.get(img.kind)
        if key is None:
            continue
        path = img.file_path.lstrip("/")
        url = f"/{path}" if path.startswith("static/") else f"/static/{path}"
        anchors_dict[key] = {"id": img.id, "url": url}

    # Must have at least the front anchor to be usable for identity conditioning.
    if "front" not in anchors_dict:
        return None

    return {"version": 1, "anchors": anchors_dict}


def _load_anchor_images(
    anchor_data: dict,
    character_id: int,
) -> tuple[list[bytes], list[str]]:
    """Load identity anchor images in preferred order (B19).

    Works for both R2 (https://...) and local (/static/generated/...) URLs
    via load_image_bytes.  Preferred order: front → three_quarter → torso → full_body.

    Returns:
        (loaded_bytes, loaded_type_keys) — parallel lists.
        Entries for missing or unreadable files are silently skipped.
    """
    anchors = anchor_data.get("anchors") or {}
    loaded_bytes: list[bytes] = []
    loaded_keys: list[str] = []

    logger.info(
        "DIAG anchor_load_start character_id=%s anchors_in_json=%s",
        character_id,
        list(anchors.keys()),
    )

    for key in _ANCHOR_LOAD_ORDER:
        entry = anchors.get(key)
        if not entry:
            logger.info("DIAG anchor_skip character_id=%s key=%s reason=not_in_json", character_id, key)
            continue
        url = entry.get("url", "")
        if not url:
            logger.info("DIAG anchor_skip character_id=%s key=%s reason=empty_url", character_id, key)
            continue
        logger.info("DIAG anchor_attempt character_id=%s key=%s url=%s", character_id, key, url)
        try:
            img_bytes = load_image_bytes(url)
            loaded_bytes.append(img_bytes)
            loaded_keys.append(key)
            logger.info(
                "DIAG anchor_loaded character_id=%s key=%s bytes=%d",
                character_id, key, len(img_bytes),
            )
        except Exception as _exc:
            logger.warning(
                "DIAG anchor_load_failed character_id=%s key=%s url=%s error=%r",
                character_id, key, url, str(_exc),
            )

    logger.info(
        "DIAG anchor_load_done character_id=%s loaded=%d/%d keys=%s",
        character_id, len(loaded_bytes), len(anchors), loaded_keys,
    )
    return loaded_bytes, loaded_keys


def _prioritise_face_anchors(
    loaded_bytes: list[bytes],
    loaded_keys: list[str],
) -> tuple[list[bytes], list[str]]:
    """Boost face anchor signal by duplicating the front anchor (B21).

    Prepends a second copy of the front-facing anchor image so the provider
    sees it with higher effective weight. Face-forward shots carry the most
    facial geometry information (nose, jaw, cheekbones, eye shape) and are
    the primary defence against generic-face drift.

    Only the front anchor is duplicated; torso and full-body shots are not
    repeated since they add body/pose information, not face specificity.

    When no front anchor is available, returns the inputs unchanged —
    the existing fallback chain (grounded → text-only) remains intact.
    """
    if not loaded_bytes or "front" not in loaded_keys:
        return loaded_bytes, loaded_keys

    front_idx = loaded_keys.index("front")
    prioritised_bytes = [loaded_bytes[front_idx]] + list(loaded_bytes)
    prioritised_keys = ["front"] + list(loaded_keys)
    return prioritised_bytes, prioritised_keys


def _reorder_anchor_refs(
    anchor_images: list[bytes],
    anchor_types: list[str],
    *,
    tattoo_primary: bool = False,
) -> tuple[list[bytes], list[str]]:
    """Reorder collected anchor refs to enforce the generation contract priority order.

    ══════════════════════════════════════════════════════════════════════════
    GENERATION CONTRACT — when include_character=True, priority is:
      1. Face identity refs    (face anchor seed — front, three_quarter)
      2. Body identity refs    (body morphology + marking placement truth)
      3. Support refs          (accessories, final_character_card)
      4. Prompt text           (FALLBACK ONLY — not source of truth for markings)

    Visual refs are authoritative. Prompt text for body markings is secondary.
    ══════════════════════════════════════════════════════════════════════════

    Face-first mode (tattoo_primary=False) — normal generation:
      front → body_anchor:* → body_front → body_detail → three_quarter → torso
        → other → body_map → final_card

    Body-truth mode (tattoo_primary=True) — tattoo/body-visible generation:
      front (no dup) → body_front → body_detail → body_anchor:* → body_map
        → final_card → three_quarter → other → torso

      Face anchor is position 0 (identity seed).  body_front is position 1
      (primary body truth).  body_detail refs (left/right/back) immediately follow.
      final_character_card is SUPPORT ONLY — always last, never overrides body_front.
    """
    has_body_anchors = any(t.startswith("body_anchor:") for t in anchor_types)

    front_bucket: list[tuple[bytes, str]] = []
    three_quarter_bucket: list[tuple[bytes, str]] = []
    torso_bucket: list[tuple[bytes, str]] = []
    body_anchor_bucket: list[tuple[bytes, str]] = []
    body_front_bucket: list[tuple[bytes, str]] = []
    body_detail_bucket: list[tuple[bytes, str]] = []   # left/right/back detail refs
    body_map_bucket: list[tuple[bytes, str]] = []       # body_map + legacy tattoo_layout
    final_card_bucket: list[tuple[bytes, str]] = []
    other_bucket: list[tuple[bytes, str]] = []  # full_body, accessory_fit_anchor, …

    # body_identity: types that go into body_detail_bucket
    _BODY_DETAIL_TYPES = frozenset({
        "body_identity:body_left_detail",
        "body_identity:body_right_detail",
        "body_identity:body_back",
    })

    front_seen = False
    for img, t in zip(anchor_images, anchor_types):
        if t == "front":
            if not front_seen:
                front_bucket.append((img, t))
                front_seen = True
            elif not has_body_anchors and not tattoo_primary:
                # Keep face-boost dup only in face-first mode with no body anchors.
                front_bucket.append((img, t))
            # else: discard duplicate
        elif t.startswith("body_anchor:"):
            body_anchor_bucket.append((img, t))
        elif t == "body_identity:body_front":
            body_front_bucket.append((img, t))
        elif t in _BODY_DETAIL_TYPES:
            body_detail_bucket.append((img, t))
        elif t in ("body_identity:body_map", "body_identity:tattoo_layout"):
            body_map_bucket.append((img, t))
        elif t == "final_character_card":
            final_card_bucket.append((img, t))
        elif t == "three_quarter":
            three_quarter_bucket.append((img, t))
        elif t == "torso":
            torso_bucket.append((img, t))
        else:
            other_bucket.append((img, t))

    # Canonical anchor side ordering: right_arm before left_arm.
    # Matches the ARM BINDING text block order so image and text signals align.
    def _ba_sort(pair: tuple[bytes, str]) -> int:
        t = pair[1]
        if "right_arm" in t:
            return 0
        if "left_arm" in t:
            return 1
        return 2

    body_anchor_bucket.sort(key=_ba_sort)

    if tattoo_primary:
        # Body-truth mode: face anchor first (identity seed), body_front second (primary body truth).
        # body_detail (left/right/back) immediately follows for high-fidelity marking refs.
        # final_character_card is support only — always after face and body identity refs.
        ordered = (
            front_bucket           # 1. face anchor (single, no duplicate — identity seed)
            + body_front_bucket    # 2. body truth (body proportions + tattoo placement)
            + body_detail_bucket   # 3. detail crops (left/right side, back — marking fidelity)
            + body_anchor_bucket   # 4. per-arm close-up photos
            + body_map_bucket      # 5. abstract placement map (body_map / legacy tattoo_layout)
            + final_card_bucket    # 6. support only — must not override face or body identity
            + three_quarter_bucket # 7. face angle support
            + other_bucket         # 8. accessories etc.
            + torso_bucket         # 9. lowest priority in tattoo mode
        )
    else:
        # Face-first — normal character generation.
        # final_character_card is support only, always last.
        ordered = (
            front_bucket           # 1. face anchor (with possible boost dup)
            + body_anchor_bucket   # 2. per-arm tattoo close-ups
            + body_front_bucket    # 3. anatomical context
            + body_detail_bucket   # 4. detail crops
            + three_quarter_bucket # 5. face angle support
            + torso_bucket         # 6. body context
            + other_bucket         # 7. accessories etc.
            + body_map_bucket      # 8. abstract design map (lowest priority)
            + final_card_bucket    # 9. support only — always last
        )
    return [p[0] for p in ordered], [p[1] for p in ordered]


# ── Body visibility / identity anchor signals ─────────────────────────
# Signals that imply the torso / full body is meaningfully exposed.
# Used to decide whether to load body identity anchors.
_BODY_VISIBLE_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "no shirt", "topless",
    "sleeveless", "tank top", "vest", "crop top",
    "swimwear", "swimming", "pool", "beach", "paddling",
    "full body", "full-body", "standing", "walking", "running",
    "torso", "chest", "abs", "abdomen",
    # Short-sleeve garments expose arms — body_front needed for anatomical context.
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
})

_MAX_PROVIDER_REFS = 6  # hard cap on total reference images sent to provider

# Maximum characters for the final composed prompt sent to the provider.
# Raised from the original 800-char limit: identity lock + body canon + sleeve
# enforcement together exceeded that budget, silently dropping tattoo signal.
_STRICT_IDENTITY_PROMPT_MAX_CHARS = 2000

# Simplified body canon instruction used when tattoos/body are visible but no
# body_front reference image is stored. Describes markings from spec text — it must
# NOT claim a locked body reference image exists, because in this mode there is none.
_SIMPLIFIED_BODY_CANON_TEXT = (
    "Render the character's permanent body markings exactly as described. "
    "Tattoos appear only on exposed skin, never on clothing."
)

# Canonical body reference instruction — used when body_front is locked and tattoos are visible.
# body_front is the single source of truth; no per-arm essays needed.
_CANONICAL_BODY_REF_TEXT = (
    "Match the locked body reference image exactly. "
    "Preserve body shape, tattoo placement, sleeve coverage, hairstyle, and identity. "
    "Tattoos are skin markings only, never printed on clothing."
)

# Ref types allowed when canonical body-front mode is active.
# body_anchor:*, torso, and duplicate front are stripped.
# v2 body detail refs (left/right/back/map) are explicitly included — they are
# high-signal marking-fidelity refs that must survive the canonical filter.
_CANONICAL_BODY_REF_ALLOWED = frozenset({
    "front",
    "three_quarter",
    "body_identity:body_front",
    "body_identity:body_left_detail",
    "body_identity:body_right_detail",
    "body_identity:body_back",
    "body_identity:body_map",
})

# Hard anatomical invariant injected when any body markings exist.
# Prevents providers from migrating permanent markings onto clothing or swapping limbs.
# Injected as a suffix on the body canon text block — do not move or merge with prompt sections.
_CLOTHING_SAFETY_INVARIANT = (
    "Permanent body markings are skin-only. "
    "If clothing covers the marked skin, the marking is hidden — never show through fabric. "
    "Never print, draw, transfer, or duplicate tattoos/markings onto shirts, sleeves, jackets, "
    "fabric, armour, gloves, or accessories. "
    "No clothing graphics, logos, typography, biker slogans, printed wolf graphics, "
    "tribal prints, or decorative text unless the user explicitly asks for them. "
    "Never move tattoos between limbs. "
    "Never merge left and right arm tattoos."
)

# ── Body canon visibility detection ──────────────────────────────────
# Signals that EXPLICITLY expose bare arms/skin — tattoo anchors only sent when these match.
# A hidden tattoo is correct; a forced costume change is not.
_BOTH_ARMS_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "no shirt", "topless",
    "sleeveless", "tank top", "vest", "both arms", "both tattoos",
    "tattoos visible", "tattoos showing", "arms visible", "arms out",
    "both arms visible", "bare arms",
    "paddling pool", "swimming", "swimming pool", "beach", "poolside",
    "ice bath", "cold bath", "sitting in water", "submerged", "upper body visible",
    # Short-sleeve garments expose forearms and partial sleeves.
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
})

# Arm exposure mode: "full" = bare arms entirely (sleeveless/shirtless);
#                   "partial" = t-shirt / short-sleeve (forearm + partial upper arm).
# Used to tune prompt language and anchor selection.
_FULL_ARM_EXPOSURE_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "no shirt", "topless",
    "sleeveless", "tank top", "vest", "crop top",
    "swimwear", "swimming", "pool", "beach", "paddling",
    "both arms visible", "bare arms", "arms out", "arms visible",
    "paddling pool", "swimming pool", "poolside",
    "ice bath", "cold bath", "sitting in water", "submerged", "upper body visible",
})
_PARTIAL_ARM_EXPOSURE_SIGNALS = frozenset({
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
})

_RIGHT_ARM_SIGNALS = frozenset({
    "right arm", "right forearm", "right sleeve", "right bicep",
    "right hand", "right wrist",
})
_LEFT_ARM_SIGNALS = frozenset({
    "left arm", "left forearm", "left sleeve", "left bicep",
    "left hand", "left wrist",
})
# Placement groups: which body canon placement values count as each region
_BODY_REGION_PLACEMENTS: dict[str, frozenset[str]] = {
    "right_arm": frozenset({"right_arm", "right_upper_arm", "right_forearm", "right_full_arm", "right_hand"}),
    "left_arm": frozenset({"left_arm", "left_upper_arm", "left_forearm", "left_full_arm", "left_hand"}),
    "chest": frozenset({"chest", "abdomen", "ribs", "side"}),
    "back": frozenset({"upper_back", "lower_back", "full_back"}),
    "neck": frozenset({"neck", "throat"}),
}

# Clothing/costume signals that indicate arm and torso skin is covered.
# When detected and no explicit visibility request exists, tattoo tokens and
# anchors for arm/torso placements are suppressed entirely.
_CLOTHING_COVER_SIGNALS = frozenset({
    "costume", "superhero", "armor", "armour", "uniform",
    "jacket", "coat", "suit", "robe", "hoodie",
    "long sleeve", "long-sleeve", "sweater", "cardigan", "blazer",
})

# Face, neck, and hand placements are naturally visible regardless of clothing.
# Markings here are always included in the identity lock text.
_ALWAYS_VISIBLE_PLACEMENTS = frozenset({
    "neck", "throat", "right_cheek", "left_cheek", "forehead", "chin", "jaw",
    "left_hand", "right_hand", "knuckles",
})

# ── Per-region exposure signals (Task #18) ───────────────────────────
# Sleeves rolled up: forearm exposed, upper arm covered.
_ROLLED_SLEEVE_SIGNALS = frozenset({
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up", "pushed-up sleeves",
})

# Button / dress / plain shirt: upper arm AND forearm covered unless sleeves rolled.
_BUTTON_SHIRT_SIGNALS = frozenset({
    "button shirt", "button-up shirt", "button up shirt", "button-down shirt",
    "button down shirt", "button-up", "button up", "button-down", "button down",
    "dress shirt", "plain shirt", "collared shirt", "oxford shirt",
})

# Bare-torso signals: chest and back skin exposed.
_SHIRTLESS_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso",
})

# ── Scene complexity detection ────────────────────────────────────────
# Full-body anchor shows studio composition; gate it out for actioned scenes.
# These signals imply the character is doing something / somewhere specific.
_FULL_BODY_GATE_SIGNALS = frozenset({
    "sitting", "lying", "lying down", "sleeping", "leaning",
    "crouching", "kneeling", "running", "walking", "fighting",
    "jumping", "climbing", "driving", "riding", "holding", "hugging",
    "ice bath", "cold bath", "bath", "pool", "rooftop", "forest",
    "rain", "snow", "street", "alley", "city",
})

# Broader set for measuring complexity → triggers anti-studio-leak injection.
_SCENE_COMPLEXITY_SIGNALS = frozenset({
    "sitting", "lying", "sleeping", "leaning", "crouching", "kneeling",
    "running", "walking", "fighting", "jumping", "climbing", "driving",
    "riding", "holding", "hugging", "exhausted", "angry", "crying",
    "smiling", "laughing",
    "ice bath", "cold bath", "bath", "pool", "rooftop", "forest",
    "rain", "snow", "fire", "street", "alley", "city",
    "bed", "chair", "floor", "water",
    "vest", "hoodie", "sweater", "coat", "jacket",
})


def _detect_scene_complexity(prompt_lower: str) -> tuple[str, bool]:
    """Analyse the prompt for scene complexity.

    Returns:
        scene_complexity: "low" | "medium" | "high"
        full_body_gated: True when full_body anchor should be excluded to prevent
                         studio-composition bleed-through into actioned scenes.
    """
    gate_hits = sum(1 for sig in _FULL_BODY_GATE_SIGNALS if sig in prompt_lower)
    complexity_hits = sum(1 for sig in _SCENE_COMPLEXITY_SIGNALS if sig in prompt_lower)

    full_body_gated = gate_hits >= 1

    if complexity_hits >= 3:
        scene_complexity = "high"
    elif complexity_hits >= 1:
        scene_complexity = "medium"
    else:
        scene_complexity = "low"

    return scene_complexity, full_body_gated


def _detect_visible_body_regions(prompt_lower: str) -> set[str]:
    """Return set of body region names visible in the given prompt.

    Returns region keys that match _BODY_REGION_PLACEMENTS keys.
    """
    visible: set[str] = set()
    if any(sig in prompt_lower for sig in _BOTH_ARMS_SIGNALS):
        visible.add("right_arm")
        visible.add("left_arm")
    if any(sig in prompt_lower for sig in _RIGHT_ARM_SIGNALS):
        visible.add("right_arm")
    if any(sig in prompt_lower for sig in _LEFT_ARM_SIGNALS):
        visible.add("left_arm")
    return visible


def _detect_arm_visibility_mode(prompt_lower: str) -> str:
    """Return arm exposure mode for the given prompt.

    "full"    — sleeveless / shirtless / bare arms: full arm skin exposed
    "partial" — t-shirt / short-sleeve: forearm + partial upper arm exposed
    "covered" — hoodie / jacket / long-sleeve: arm skin is hidden
    "none"    — no arm-relevant garment signal detected
    """
    if any(sig in prompt_lower for sig in _CLOTHING_COVER_SIGNALS):
        return "covered"
    if any(sig in prompt_lower for sig in _FULL_ARM_EXPOSURE_SIGNALS):
        return "full"
    if any(sig in prompt_lower for sig in _PARTIAL_ARM_EXPOSURE_SIGNALS):
        return "partial"
    return "none"


# ── Visibility-aware marking partitioning (Task #18) ─────────────────
# Precise anatomical region per marking placement. Broad/legacy whole-arm
# placements map to a "broad_*_arm" region that triggers the safe fallback
# (hidden unless the whole arm is clearly exposed) — they span both upper arm
# and forearm and cannot be partially shown reliably.
_MARKING_REGION: dict[str, str] = {
    "right_upper_arm": "right_upper_arm",
    "left_upper_arm": "left_upper_arm",
    "right_forearm": "right_forearm",
    "left_forearm": "left_forearm",
    "shoulder": "shoulder",
    "left_shoulder": "shoulder",
    "right_shoulder": "shoulder",
    "chest": "chest",
    "abdomen": "chest",
    "ribs": "chest",
    "side": "chest",
    "upper_back": "back",
    "lower_back": "back",
    "full_back": "back",
    "neck": "neck",
    "throat": "neck",
    "right_cheek": "face",
    "left_cheek": "face",
    "forehead": "face",
    "chin": "face",
    "jaw": "face",
    "left_hand": "hand",
    "right_hand": "hand",
    "knuckles": "hand",
    "left_thigh": "left_leg",
    "right_thigh": "right_leg",
    "left_calf": "left_leg",
    "right_calf": "right_leg",
}

_BROAD_ARM_REGION: dict[str, str] = {
    "right_arm": "broad_right_arm",
    "right_full_arm": "broad_right_arm",
    "left_arm": "broad_left_arm",
    "left_full_arm": "broad_left_arm",
}


def _classify_marking_region(placement: str) -> str:
    """Map a marking placement to a precise anatomical region.

    Broad/legacy whole-arm placements map to 'broad_right_arm' / 'broad_left_arm'
    which trigger the safe fallback during exposure classification.
    """
    if placement in _BROAD_ARM_REGION:
        return _BROAD_ARM_REGION[placement]
    return _MARKING_REGION.get(placement, "other")


def _classify_region_exposure(region: str, prompt_lower: str) -> str:
    """Classify a body region as 'exposed', 'covered', or 'unknown' for this scene.

    Garment rules:
      sleeveless / tank / shirtless  → full arm exposed
      t-shirt / short sleeve         → forearm exposed, upper arm covered
      rolled sleeves                 → forearm exposed, upper arm covered
      button / dress / plain shirt   → upper arm + forearm covered (unless rolled)
      long sleeves / jacket / etc.   → all arm skin covered
      no garment signal              → unknown (treated as hidden by the caller)
    """
    full_arm = any(s in prompt_lower for s in _FULL_ARM_EXPOSURE_SIGNALS)
    short_sleeve = any(s in prompt_lower for s in _PARTIAL_ARM_EXPOSURE_SIGNALS)
    rolled = any(s in prompt_lower for s in _ROLLED_SLEEVE_SIGNALS)
    button_shirt = any(s in prompt_lower for s in _BUTTON_SHIRT_SIGNALS)
    covering = any(s in prompt_lower for s in _CLOTHING_COVER_SIGNALS)
    shirtless = any(s in prompt_lower for s in _SHIRTLESS_SIGNALS)
    covered_garment = button_shirt or covering

    # Always-visible regions.
    if region in ("face", "hand", "neck"):
        return "exposed"

    # Upper arm / shoulder: exposed only when the full arm is bare.
    if region in ("right_upper_arm", "left_upper_arm", "shoulder"):
        if full_arm:
            return "exposed"
        if short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    # Forearm: exposed with full arm exposure, short sleeve, or rolled sleeves.
    if region in ("right_forearm", "left_forearm"):
        if full_arm or short_sleeve or rolled:
            return "exposed"
        if covered_garment:
            return "covered"
        return "unknown"

    # Broad arm: only fully exposed when the whole arm is bare (safe fallback).
    if region in ("broad_right_arm", "broad_left_arm"):
        if full_arm:
            return "exposed"
        if short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    # Chest / abdomen: exposed only when the torso is bare.
    if region == "chest":
        if shirtless:
            return "exposed"
        if full_arm or short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    # Back: exposed when bare-backed.
    if region == "back":
        if shirtless or "backless" in prompt_lower or "bare back" in prompt_lower:
            return "exposed"
        if full_arm or short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    # Legs / other regions: no reliable garment signal here → unknown.
    return "unknown"


def _partition_markings_by_visibility(
    markings: list, prompt_lower: str
) -> tuple[list, list]:
    """Split markings into (visible, hidden) for the current scene.

    A marking is VISIBLE only when its region is clearly exposed; covered or
    uncertain regions fall to HIDDEN — the safe fallback that prevents the model
    from relocating a covered marking to nearby exposed skin.

    Sleeve exception: a full-sleeve tattoo on a broad-arm placement (left_full_arm /
    right_full_arm) definitively covers the forearm as well as the upper arm.  When
    the corresponding forearm is exposed (rolled sleeves, short sleeve, etc.) the
    forearm portion of the sleeve IS visible — override the broad-arm safe fallback
    so the sleeve renders on exposed forearm skin instead of being silently hidden.
    """
    visible: list = []
    hidden: list = []
    for m in markings:
        if m.placement in _ALWAYS_VISIBLE_PLACEMENTS:
            visible.append(m)
            continue
        region = _classify_marking_region(m.placement)
        exposure = _classify_region_exposure(region, prompt_lower)
        # Sleeve exception: broad-arm safe fallback is too conservative for
        # full-sleeve tattoos — the forearm portion is always part of the sleeve
        # and shows whenever the forearm is exposed.
        if exposure != "exposed" and region in ("broad_left_arm", "broad_right_arm"):
            if is_sleeve_marking(m):
                forearm_region = (
                    "left_forearm" if region == "broad_left_arm" else "right_forearm"
                )
                if _classify_region_exposure(forearm_region, prompt_lower) == "exposed":
                    exposure = "exposed"
        if exposure == "exposed":
            visible.append(m)
        else:
            hidden.append(m)
    return visible, hidden


def _build_partitioned_marking_blocks(
    visible_markings: list, hidden_markings: list
) -> str:
    """Build explicit VISIBLE / HIDDEN marking blocks for the prompt.

    Returns '' when there are no markings at all so unmarked characters emit no
    block. The HIDDEN block carries the hard relocation rules.
    """
    if not visible_markings and not hidden_markings:
        return ""
    parts: list[str] = []
    if visible_markings:
        v = "; ".join(build_compact_token(m) for m in visible_markings)
        parts.append(
            "VISIBLE BODY MARKINGS — render only these on exposed skin, in their "
            f"exact anatomical location: {v}"
        )
    if hidden_markings:
        h = "; ".join(build_compact_token(m) for m in hidden_markings)
        parts.append(
            "HIDDEN BODY MARKINGS — canonical but not visible in this scene because "
            f"clothing covers them: {h}. Do not render hidden markings. Do not "
            "relocate hidden markings to visible skin. Do not print hidden markings "
            "on clothing or fabric."
        )
    return ". ".join(parts)


def _reliably_visible_phase1(marking, prompt_lower: str) -> bool:
    """Phase 1 (#23) beta-safe visibility: a marking is reliably visible only
    when its WHOLE region is exposed, so the existing full-body / full-arm
    references match the scene exactly.

    Partial exposure (rolled / short sleeves showing only the forearm) is NOT
    reliably supported yet — we have no forearm-only reference — so it is treated
    as covered. Wrong tattoos are worse than missing tattoos.
    """
    if marking.placement in _ALWAYS_VISIBLE_PLACEMENTS:
        return True
    side = get_arm_side(marking.placement)
    if side is not None:
        # The whole arm must be bare (sleeveless / full arm exposed) for the
        # body_front / arm-detail references to depict the scene faithfully.
        return _classify_region_exposure(f"broad_{side}_arm", prompt_lower) == "exposed"
    region = _classify_marking_region(marking.placement)
    return _classify_region_exposure(region, prompt_lower) == "exposed"


def _partition_markings_phase1_safe(
    markings: list, prompt_lower: str
) -> tuple[list, list]:
    """Phase 1 partition: split markings into (visible, hidden) using the strict
    whole-region rule. Per arm side this is all-or-nothing, so a side is never
    simultaneously visible and hidden — which keeps reference selection safe.
    """
    visible: list = []
    hidden: list = []
    for m in markings:
        if _reliably_visible_phase1(m, prompt_lower):
            visible.append(m)
        else:
            hidden.append(m)
    return visible, hidden


def _excluded_body_slots_for_hidden(hidden_markings: list) -> set[str]:
    """Reference image slots to withhold because they depict a HIDDEN marking.

    - A per-side detail crop (body_left_detail / body_right_detail) is withheld
      when that side carries a hidden marking.
    - The whole-body refs (body_front / body_back / body_map / legacy
      tattoo_layout) depict every marking at once, so any hidden marking
      withholds all of them.
    - final_character_card is a rendered portrait that also depicts markings, so
      it is withheld whenever anything is hidden (it would re-introduce the
      hidden marking and risk relocation/mirroring).
    Face anchors (front / three_quarter) are never withheld here.
    """
    hidden_sides = {
        s for m in hidden_markings if (s := get_arm_side(m.placement)) is not None
    }
    excluded = {f"body_{side}_detail" for side in hidden_sides}
    if hidden_markings:
        excluded.update({
            "body_front", "body_back", "body_map", "tattoo_layout",
            "final_character_card",
        })
    return excluded


def _build_arm_side_lock_str(visible_markings: list, hidden_markings: list) -> str:
    """Phase 1 side-lock + negative-side text.

    Emitted only when at least one arm carries a visible marking AND the opposite
    arm has no visible marking — declares the marked arm and explicitly states the
    other arm is bare so the model does not mirror a tattoo onto bare skin.
    """
    visible_sides = {
        s for m in visible_markings if (s := get_arm_side(m.placement)) is not None
    }
    if not visible_sides:
        return ""
    bare_sides = {"left", "right"} - visible_sides
    if not bare_sides:
        return ""
    vis_txt = " and ".join(sorted(visible_sides))
    bare_txt = " and ".join(sorted(bare_sides))
    return (
        f"ARM SIDE LOCK: Only the {vis_txt} arm has visible tattoos. "
        f"The {bare_txt} arm is bare skin. "
        f"No tattoos, writing, symbols, or marks on the {bare_txt} arm."
    )


def _build_strict_identity_prompt(
    *,
    base_prompt: str,
    anchor_data: dict,
    character_name: str = "",
    retry: bool = False,
    body_canon_str: str = "",
    arm_side_binding_str: str = "",
    sleeve_enforcement_str: str = "",
    scene_complex: bool = False,
    character_id: int | None = None,
    arm_visibility_mode: str = "none",
    provider_name: str = "",
    tattoo_simplified: bool = False,
) -> str:
    """Build a scene-first strict-identity prompt.

    Scene dominates — WHO this person is wraps WHAT they are doing, not the reverse.

    Section order (all required — none are silently truncated):
      1. [SCENE]        user prompt — highest model weight
      2. [SCENE GUARD]  anti-studio note when scene has complexity
      3. [IDENTITY]     face/build directive + lock string
      4. [BODY CANON]   markings only where skin is naturally exposed
      5. [ARM BINDING]  hard left/right exclusivity rules (prevents arm swap)
      6. [SLEEVE]       hard enforcement for visible full sleeves

    Capped at _STRICT_IDENTITY_PROMPT_MAX_CHARS.  All sections are included
    in full; if the total still exceeds the cap a warning is logged but the
    complete string is returned so that tattoo/sleeve signal is never silently
    dropped mid-sentence.
    """
    _sep = ". "

    # 1. Scene first — model weights earlier tokens more heavily.
    section_scene = base_prompt

    # 2. Scene preservation guard.
    section_guard = (
        "Preserve the exact scene, pose, clothing, setting, and composition as described. "
        "Do not revert to studio portrait, neutral standing pose, or identity-pack composition."
    ) if scene_complex else ""

    # 3. Identity directive.
    prefix = _STRICT_IDENTITY_RETRY_PREFIX if retry else _STRICT_IDENTITY_PREFIX
    section_identity = prefix.rstrip()
    if character_name:
        section_identity = section_identity + _sep + f"Character: {character_name}"

    # 4. Identity lock: hair/eyes/skin/morphology.
    section_lock = (anchor_data.get("identity_lock_string") or "").strip()

    # 5. Body canon: markings where skin is naturally exposed.
    if body_canon_str:
        if tattoo_simplified:
            # Simplified mode: body_canon_str is already the complete instruction.
            # No extra skin-rule/arm-note/provider-note additions — body_front carries
            # the visual truth; extra text adds noise rather than signal.
            section_body_canon = body_canon_str.rstrip(". ")
        else:
            # Original mode: append skin rule, arm-mode qualifier, provider note.
            _skin_rule = (
                "Tattoos are permanent ink on exposed skin only — "
                "never printed on clothing or fabric"
            )
            _arm_note = {
                "partial": (
                    "only forearm and exposed upper arm are visible — "
                    "hide any portion beneath the shirt sleeve"
                ),
                "full": "render complete sleeve on bare skin",
            }.get(arm_visibility_mode, "render only where skin is naturally exposed")
            _provider_note = (
                "; do not render tattoo as a printed pattern on the shirt"
                if provider_name == "openai" else ""
            )
            section_body_canon = (
                body_canon_str.rstrip(". ")
                + f". {_skin_rule}; {_arm_note}{_provider_note}."
            )
    else:
        section_body_canon = ""

    # 6. Arm side binding: explicit left/right exclusivity rules.
    # This dedicated block prevents the provider from swapping tattoos between arms.
    section_arm_binding = arm_side_binding_str.strip() if arm_side_binding_str else ""

    # 7. Sleeve enforcement: hard identity for visible full-arm sleeves.
    if sleeve_enforcement_str:
        _base_sleeve = sleeve_enforcement_str.strip()
        _sleeve_mode_note = {
            "partial": (
                "Partial arm exposure only — render tattoo on exposed forearm and "
                "uncovered upper arm; hide any portion beneath the shirt sleeve."
            ),
            "full": "Do not print sleeve on shirt fabric.",
        }.get(arm_visibility_mode, "")
        section_sleeve = (
            _base_sleeve.rstrip(".") + ". " + _sleeve_mode_note
            if _sleeve_mode_note else _base_sleeve
        )
    else:
        section_sleeve = ""

    # Join all non-empty sections, stripping trailing punctuation per section.
    sections = [
        s.rstrip(". ")
        for s in [
            section_scene,
            section_guard,
            section_identity,
            section_lock,
            section_body_canon,
            section_arm_binding,
            section_sleeve,
        ]
        if s
    ]
    combined = _sep.join(sections)

    # Budget check: log but never silently truncate required sections.
    body_canon_preserved = not body_canon_str or body_canon_str.rstrip(". ") in combined
    sleeve_preserved = not sleeve_enforcement_str or sleeve_enforcement_str.strip() in combined
    if len(combined) > _STRICT_IDENTITY_PROMPT_MAX_CHARS:
        logger.warning(
            "PROMPT-BUDGET character_id=%s max_chars=%d final_chars=%d "
            "body_canon_preserved=%s sleeve_preserved=%s — over budget, returning full",
            character_id, _STRICT_IDENTITY_PROMPT_MAX_CHARS, len(combined),
            body_canon_preserved, sleeve_preserved,
        )
    logger.info(
        "PROMPT-BUDGET character_id=%s max_chars=%d final_chars=%d "
        "scene_chars=%d identity_chars=%d body_canon_chars=%d "
        "arm_binding_chars=%d sleeve_chars=%d "
        "body_canon_preserved=%s sleeve_preserved=%s",
        character_id,
        _STRICT_IDENTITY_PROMPT_MAX_CHARS,
        len(combined),
        len(section_scene),
        len(section_identity) + len(section_lock),
        len(section_body_canon),
        len(section_arm_binding),
        len(section_sleeve),
        body_canon_preserved,
        sleeve_preserved,
    )
    return combined


# ── Endpoint ─────────────────────────────────────────────────────────


@router.post(
    "/{character_id}/image-generator/generate",
    response_model=CharacterImageRead,
    summary="Generate an image with optional character identity and provider selection (B17-B19)",
)
def generate_image(
    character_id: int,
    body: ImageGenerateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a single image.

    When include_character=True, strict identity mode (B18) with anchor-image
    conditioning (B19) is automatically enabled:
      - All available identity pack images are loaded from disk
      - Passed as real provider inputs via generate_with_anchors (multi-image)
      - Falls back to single-image grounded generation when multi-image unsupported
      - Short, punchy identity directive is prepended to the prompt
      - Provider is required; stub fallback is blocked
      - At most one retry with escalated wording; then controlled 503 failure

    When include_character=False, normal generation applies (text → fallback → stub).

    provider_option:
      option1 → OpenAI  |  option2 → Google
    """
    # ── Auth + ownership ──────────────────────────────────────────
    character = db.query(CharacterModel).filter(CharacterModel.id == character_id).first()
    if not character:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Character not found.")
    if character.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to use this character.",
        )

    # ── B22: Weekly allowance check ────────────────────────────────
    # Checked before generation starts; deducted only on successful save.
    # Admin users bypass this check entirely.
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Provider resolution ────────────────────────────────────────
    effective_option = body.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]

    # ── Character inclusion ────────────────────────────────────────
    anchor_data: dict | None = None
    face_ref_bytes: bytes | None = None
    identity_hash: str | None = None
    base_prompt = body.prompt.strip()

    # Cover mode: prepend banner-composition directives before the user's prompt.
    # Character framing is added additionally when include_character=True so the
    # medium-shot instruction travels with the scene description inside the
    # strict-identity wrapper.
    if body.is_cover:
        cover_block = _COVER_BANNER_PREFIX
        if body.include_character:
            cover_block += _COVER_CHARACTER_FRAMING
        base_prompt = cover_block + base_prompt

    if body.include_character:
        if not character.visual_locked:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Your character's visual identity must be locked before "
                    "including them in an image. Complete the identity pack first."
                ),
            )

        anchor_data = _parse_anchor_json(character.identity_anchor_json)
        if anchor_data is None:
            # Legacy compatibility: character was locked before identity_anchor_json was
            # introduced (pre-Feb 2026).  Attempt to rebuild from active anchor rows.
            anchor_data = _build_anchor_data_from_db(character_id, db)
            if anchor_data is not None:
                # Persist the rebuilt snapshot so future requests use it directly.
                logger.info(
                    "anchor_json_repaired_from_db character_id=%s anchor_count=%d",
                    character_id,
                    len(anchor_data.get("anchors", {})),
                )
                character.identity_anchor_json = _json.dumps(anchor_data)
                db.commit()
                db.refresh(character)
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Character identity anchor not found. "
                        "Please regenerate and accept the identity pack."
                    ),
                )

        identity_hash = anchor_data.get("identity_prompt_hash")

        # Load face reference bytes (tight head crop — fallback for single-image path)
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
        if face_ref_img is None:
            logger.info(
                "DIAG face_ref_missing character_id=%s name=%r — no IDENTITY_FACE_REF in DB",
                character_id, character.name,
            )
        else:
            logger.info(
                "DIAG face_ref_found character_id=%s name=%r file_path=%s",
                character_id, character.name, face_ref_img.file_path,
            )
            try:
                face_ref_bytes = load_image_bytes(face_ref_img.file_path)
                logger.info(
                    "DIAG face_ref_loaded character_id=%s bytes=%d",
                    character_id, len(face_ref_bytes),
                )
            except Exception as _fre:
                logger.warning(
                    "DIAG face_ref_load_failed character_id=%s file_path=%s error=%r",
                    character_id, face_ref_img.file_path, str(_fre),
                )

    # ── Style Shops element injection (hair + removables only) ────────
    # Tattoos and scars are now body canon — injected via identity lock.
    # When include_character=True (identity mode) skip permanent/hair tokens:
    # the identity_lock_string already encodes hair from the identity spec, and
    # injecting a conflicting barber token causes visual drift from the anchor pack.
    try:
        base_prompt = apply_style_elements_to_image_prompt(
            character, base_prompt, db,
            include_permanent=not body.include_character,
        )
    except Exception as _se:
        logger.warning(
            "style_elements_injection_failed character_id=%s error=%r — skipping",
            character_id, str(_se),
        )

    # Body canon, sleeve enforcement, and scene complexity are computed inside the
    # include_character block. Initialise here so they're always in scope.
    _body_canon_str = ""
    _sleeve_enforcement_str = ""
    _scene_complexity = "low"
    _full_body_gated = False
    _full_body_anchor_used = False

    # ── Accessory slot injection (v1/v2) ──────────────────────────
    # When include_character=True, inject locked accessory block if the prompt
    # references the accessory type. Appended before the 800-char cap so it
    # travels with the scene description. No-op when character has no accessories
    # or prompt does not mention the accessory type.
    # v2: also track the triggered accessory for anchor image injection below.
    triggered_accessory: dict | None = None
    if body.include_character:
        accessory_block = build_accessory_prompt_block(character, base_prompt)
        if accessory_block:
            triggered_accessory = get_triggered_accessory(character.identity_anchor_json, base_prompt)
            base_prompt = base_prompt + "\n" + accessory_block

    provider_prompt = base_prompt[:800]

    # ── Resolve provider ──────────────────────────────────────────
    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError):
        logger.warning(
            "image_generator provider_unavailable option=%s provider=%s character_id=%s",
            effective_option,
            resolved_provider_name,
            character_id,
        )
        provider = None

    png_bytes: bytes | None = None
    actual_provider_name = "stub"
    used_face_ref = False
    retry_attempted = False
    multi_image_used = False

    # ── B18/B19 STRICT IDENTITY MODE (include_character=True) ─────
    if body.include_character:
        logger.info(
            "DIAG identity_mode_enter character_id=%s name=%r provider=%s "
            "face_ref_available=%s anchor_json_present=%s",
            character_id, character.name, resolved_provider_name,
            face_ref_bytes is not None,
            character.identity_anchor_json is not None,
        )

        # ── Scene complexity detection ────────────────────────────────
        # Compute before anchor loading so full_body gate can be applied.
        _scene_complexity, _full_body_gated = _detect_scene_complexity(provider_prompt.lower())

        # Arm visibility mode: full/partial/covered/none — governs prompt language
        # and anchor selection (tattoo_layout excluded for partial/none).
        _arm_visibility_mode = _detect_arm_visibility_mode(provider_prompt.lower())

        # B19: load actual anchor images from disk
        anchor_images, anchor_types = _load_anchor_images(
            anchor_data,  # type: ignore[arg-type]
            character_id,
        )

        # Gate: drop full_body anchor for actioned / environment scenes.
        # Full-body studio shots dominate pose and clothing when the user
        # has asked for a specific scene — face/torso refs are sufficient.
        _full_body_anchor_used = "full_body" in anchor_types
        if _full_body_gated and _full_body_anchor_used:
            _fb_filtered = [
                (b, t) for b, t in zip(anchor_images, anchor_types) if t != "full_body"
            ]
            anchor_images = [p[0] for p in _fb_filtered]
            anchor_types = [p[1] for p in _fb_filtered]
            _full_body_anchor_used = False
            logger.info(
                "DIAG full_body_anchor_suppressed character_id=%s "
                "reason=scene_action_detected scene_complexity=%s",
                character_id, _scene_complexity,
            )

        # ── Identity reference gate ───────────────────────────────────
        # If the character has identity anchors stored in JSON but none could
        # be loaded, do NOT silently proceed to text-only generation — that
        # produces a wrong face and destroys identity.  Fail loudly so the
        # operator/user knows there is a storage access problem.
        _anchors_in_json = anchor_data.get("anchors") or {}
        if _anchors_in_json and not anchor_images and face_ref_bytes is None:
            logger.error(
                "identity_reference_gate_failed character_id=%s name=%r "
                "anchors_in_json=%d anchors_loaded=0 face_ref=None "
                "— refusing text-only fallback to prevent wrong-face output",
                character_id, character.name, len(_anchors_in_json),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Character image generation failed: identity reference images "
                    "could not be loaded from storage. This prevents generating an "
                    "image with the wrong face. Please try again or contact support."
                ),
            )

        # B21: boost face anchor signal — duplicate front anchor for stronger conditioning.
        # Tracked separately so metadata accurately reflects the boost.
        _face_anchor_boosted = "front" in anchor_types
        anchor_images, anchor_types = _prioritise_face_anchors(anchor_images, anchor_types)

        provider_supports_multi = getattr(provider, "supports_multi_image_input", False)

        # v2: accessory fit anchor injection.
        # The standalone object anchor (anchor_image_url) is NEVER used as a scene
        # reference — it causes the model to paste/scale the mask over the head.
        # Only the fit anchor (character wearing the accessory correctly) is used.
        # Prompt hierarchy: identity anchors → fit anchor → accessory text → scene.
        if triggered_accessory is not None:
            _acc_id = triggered_accessory.get("id", "?")
            _fit_status = triggered_accessory.get("fit_anchor_status", "none")
            _fit_url = triggered_accessory.get("fit_anchor_image_url")

            logger.info(
                "DIAG accessory_object_anchor_not_used_for_scene character_id=%s accessory_id=%s",
                character_id, _acc_id,
            )

            if _fit_status == "locked" and _fit_url:
                if provider_supports_multi:
                    try:
                        _fit_img_bytes = load_image_bytes(_fit_url)
                        anchor_images = list(anchor_images) + [_fit_img_bytes]
                        anchor_types = list(anchor_types) + ["accessory_fit_anchor"]
                        logger.info(
                            "DIAG accessory_fit_anchor_used character_id=%s accessory_id=%s bytes=%d",
                            character_id, _acc_id, len(_fit_img_bytes),
                        )
                    except Exception as _fit_exc:
                        logger.warning(
                            "DIAG accessory_fit_anchor_load_failed character_id=%s accessory_id=%s error=%r",
                            character_id, _acc_id, str(_fit_exc),
                        )
                else:
                    logger.info(
                        "DIAG accessory_text_only_fallback character_id=%s accessory_id=%s "
                        "reason=provider_no_multi_image fit_status=%s",
                        character_id, _acc_id, _fit_status,
                    )
            else:
                logger.info(
                    "DIAG accessory_text_only_fallback character_id=%s accessory_id=%s fit_status=%s",
                    character_id, _acc_id, _fit_status,
                )

        # ── Body canon ─────────────────────────────────────────────────
        _bc_visible_regions = _detect_visible_body_regions(provider_prompt.lower())
        _bc_anchors_used: list[str] = []
        _bc_anchors_missing: list[str] = []

        # Lazy sync: backfill body_canon_json from active tattoo style elements.
        _bc_sync = sync_tattoo_style_elements_to_body_canon(character, db)
        if _bc_sync["created"] > 0 or _bc_sync["updated"] > 0:
            db.commit()
            db.refresh(character)

        _bc_markings = load_markings(character)

        _tattoo_visibility_requested = bool(_bc_visible_regions)
        _clothing_detected = any(sig in provider_prompt.lower() for sig in _CLOTHING_COVER_SIGNALS)

        # Peek at body slot status before text building — needed to choose canonical vs simplified.
        _bi_slots = _load_body_slots(character)
        _bf_entry_pre = _bi_slots.get("body_front") or {}
        _body_front_available = (
            _bf_entry_pre.get("status") == "locked"
            and bool(_bf_entry_pre.get("url"))
            and provider_supports_multi
        )
        # Canonical mode: body_front locked + (tattoos explicitly visible OR markings exist).
        # Markings on a character should always be governed by the locked body_front ref —
        # prompt keywords are an unreliable gate when the character has permanent markings.
        _body_front_canonical = _body_front_available and (
            _tattoo_visibility_requested or bool(_bc_markings)
        )

        # Filter markings to those whose skin area is naturally visible.
        _bc_text_markings = [
            m for m in _bc_markings
            if m.placement in _ALWAYS_VISIBLE_PLACEMENTS
            or any(
                m.placement in placements and region in _bc_visible_regions
                for region, placements in _BODY_REGION_PLACEMENTS.items()
            )
        ]

        # Visibility-aware marking partitioning (Task #18): classify each marking's
        # region exposure for THIS scene so covered markings are explicitly marked
        # HIDDEN instead of being relocated by the model to nearby exposed skin.
        # Phase 1 (#23) beta-safe partition: a marking is reliably visible only
        # when its whole region is exposed so the existing references match the
        # scene. Partial exposure normalizes to covered — wrong tattoos are worse
        # than missing tattoos.
        _bc_visible_markings, _bc_hidden_markings = _partition_markings_phase1_safe(
            _bc_markings, provider_prompt.lower()
        )
        _bc_partition_blocks = _build_partitioned_marking_blocks(
            _bc_visible_markings, _bc_hidden_markings
        )

        # Reference IMAGES are visibility-partitioned too: withhold any ref whose
        # content depicts a HIDDEN marking (face anchors are always retained).
        _excluded_body_slots = _excluded_body_slots_for_hidden(_bc_hidden_markings)
        _body_front_excluded = "body_front" in _excluded_body_slots

        # Arm sides carrying a reliably-visible marking (drives sleeve/binding text).
        _p1_visible_regions = {
            f"{_s}_arm" for _m in _bc_visible_markings
            if (_s := get_arm_side(_m.placement)) is not None
        }

        # Side-lock + negative-side text — stops mirroring onto a bare arm.
        _arm_side_lock_str = _build_arm_side_lock_str(
            _bc_visible_markings, _bc_hidden_markings
        )

        logger.info(
            "BODY-REF-VISIBILITY character_id=%s phase1=beta_safe "
            "visible_markings=%d hidden_markings=%d "
            "excluded_body_slots=%s body_front_excluded=%s side_lock=%s",
            character_id, len(_bc_visible_markings), len(_bc_hidden_markings),
            sorted(_excluded_body_slots), _body_front_excluded,
            bool(_arm_side_lock_str),
        )

        # Body canon text:
        #   canonical mode  → short ref instruction + explicit VISIBLE/HIDDEN blocks
        #   simplified mode → short instruction + compact arm side note (body_front absent)
        #   no tattoo visible → full per-marking token list
        if _body_front_canonical and not _body_front_excluded:
            _body_canon_str = _CANONICAL_BODY_REF_TEXT
            if _bc_partition_blocks:
                _body_canon_str = _body_canon_str + ". " + _bc_partition_blocks
        elif _body_front_excluded:
            # body_front withheld (it depicts a hidden marking) — do not claim a
            # locked body reference exists. Use the VISIBLE/HIDDEN partition blocks
            # only; covered markings stay covered (Phase 1 beta-safe).
            _body_canon_str = _SIMPLIFIED_BODY_CANON_TEXT
            if _bc_partition_blocks:
                _body_canon_str = _body_canon_str + ". " + _bc_partition_blocks
        elif _tattoo_visibility_requested and _bc_text_markings:
            _short_sides = build_short_arm_side_str(_bc_text_markings, _bc_visible_regions)
            _body_canon_str = _SIMPLIFIED_BODY_CANON_TEXT
            if _short_sides:
                _body_canon_str += " " + _short_sides + "."
        else:
            # Passive context: no body-exposure keyword present, so visibility
            # detection filtered _bc_text_markings to empty. Inject ALL markings
            # (_bc_markings) as passive "character has these permanent markings"
            # context so the model never invents bare, unmarked skin. The clothing
            # safety invariant below keeps covered markings hidden.
            _body_canon_str = build_passive_body_canon_string(_bc_markings)

        # Clothing safety invariant: injected when any body markings exist.
        # Hard rule preventing providers from migrating permanent markings to fabric or
        # swapping tattoos between limbs. Applied regardless of visibility mode.
        if _bc_markings:
            _body_canon_str = (
                _body_canon_str + ". " + _CLOTHING_SAFETY_INVARIANT
                if _body_canon_str
                else _CLOTHING_SAFETY_INVARIANT
            )

        # Phase 1 side-lock: explicitly declare the bare arm so a visible tattoo
        # is never mirrored onto the opposite (bare) arm.
        if _arm_side_lock_str:
            _body_canon_str = (
                _body_canon_str + ". " + _arm_side_lock_str
                if _body_canon_str else _arm_side_lock_str
            )

        # Body canon anchor refs: suppressed in simplified mode.
        # body_front provides coherent face/body/tattoo context in one image;
        # fragmented per-arm close-ups alongside it cause provider averaging/conflict.
        # (Per-arm anchors remain available in non-tattoo-visible paths.)

        logger.info(
            "BODY-CANON character_id=%s markings_count=%d "
            "visible_regions=%s canonical_mode=%s simplified_mode=%s "
            "visible_markings=%d hidden_markings=%d "
            "anchors_used=%s anchors_missing=%s "
            "text_token_len=%d provider_ref_count=%d",
            character_id,
            len(_bc_markings),
            sorted(_bc_visible_regions),
            _body_front_canonical,
            _tattoo_visibility_requested,
            len(_bc_visible_markings),
            len(_bc_hidden_markings),
            _bc_anchors_used,
            _bc_anchors_missing,
            len(_body_canon_str),
            len(anchor_images),
        )

        # ── Body identity anchor injection ────────────────────────────
        # GENERATION CONTRACT (visual refs are authoritative — prompt text is fallback):
        #   1. Face identity refs   loaded above by _prioritise_face_anchors
        #   2. Body identity refs   loaded here via get_body_identity_references
        #   3. Support refs         (accessories, final_character_card — always last)
        #   4. Prompt text          fallback description for body markings only
        #
        # Body identity refs are loaded from identity_anchor_json["body_slots"] in
        # priority order: body_front → body_left_detail → body_right_detail →
        # body_back → body_map (→ legacy tattoo_layout) → final_character_card.
        #
        # body_front is required when markings exist; its absence triggers
        # BODY_IDENTITY_MISSING — text-only placement will drift.
        _body_visible = any(sig in provider_prompt.lower() for sig in _BODY_VISIBLE_SIGNALS)
        _markings_visible = _tattoo_visibility_requested
        _bi_refs_used: list[str] = []
        _bi_refs_excluded: list[str] = []
        _tattoo_layout_used = False
        _bf_loaded = False
        _body_front_source = "n/a"

        if provider_supports_multi:
            if _tattoo_visibility_requested or _body_visible or _body_front_canonical:
                # Resolve all available body identity refs in canonical priority order.
                _body_id_result = get_body_identity_references(character)

                # BODY_IDENTITY_MISSING: markings exist but body_front is absent.
                if _body_id_result.missing_required and _tattoo_visibility_requested:
                    logger.warning(
                        "BODY_IDENTITY_MISSING character_id=%s marking_count=%d "
                        "body_front_slot_status=%s — visual body truth unavailable, "
                        "text-only tattoo placement may drift",
                        character_id,
                        len(_bc_markings),
                        _body_id_result.body_front_slot_status,
                    )

                # Load each ref in priority order (body_front first, final_card last).
                # Phase 1 (#23): skip any ref slot that depicts a HIDDEN marking.
                for _bref in _body_id_result.refs:
                    if _bref.slot in _excluded_body_slots:
                        _bi_refs_excluded.append(_bref.slot)
                        logger.info(
                            "BODY-REF-WITHHELD character_id=%s slot=%s "
                            "reason=depicts_hidden_marking",
                            character_id, _bref.slot,
                        )
                        continue
                    try:
                        _bref_bytes = load_image_bytes(_bref.url)
                        anchor_images = list(anchor_images) + [_bref_bytes]
                        anchor_types = list(anchor_types) + [_bref.ref_type]
                        _bi_refs_used.append(_bref.slot)
                        if _bref.slot == "body_front":
                            _bf_loaded = True
                            _body_front_source = _bref.source
                        if _bref.slot in ("tattoo_layout", "body_map"):
                            _tattoo_layout_used = True
                    except Exception as _bref_exc:
                        logger.warning(
                            "BODY-IDENTITY ref_load_failed character_id=%s "
                            "slot=%s error=%r",
                            character_id, _bref.slot, str(_bref_exc),
                        )

            else:
                # Body not visible in scene — still load final_character_card if present
                # (support-only ref, low signal cost, does not affect body truth).
                # Phase 1 (#23): withhold it when any marking is hidden — the card
                # depicts markings and would re-introduce a hidden one.
                _body_id_result = get_body_identity_references(character)
                for _bref in _body_id_result.refs:
                    if _bref.slot == "final_character_card":
                        if _bref.slot in _excluded_body_slots:
                            _bi_refs_excluded.append(_bref.slot)
                            logger.info(
                                "BODY-REF-WITHHELD character_id=%s slot=%s "
                                "reason=depicts_hidden_marking",
                                character_id, _bref.slot,
                            )
                            break
                        try:
                            _bref_bytes = load_image_bytes(_bref.url)
                            anchor_images = list(anchor_images) + [_bref_bytes]
                            anchor_types = list(anchor_types) + [_bref.ref_type]
                            _bi_refs_used.append(_bref.slot)
                            logger.info(
                                "BODY-IDENTITY final_card_loaded character_id=%s",
                                character_id,
                            )
                        except Exception as _fc_exc:
                            logger.warning(
                                "BODY-IDENTITY final_card_load_failed "
                                "character_id=%s error=%r",
                                character_id, str(_fc_exc),
                            )
                        break

        # Simplified tattoo mode: drop torso refs — low-signal noise alongside body_front.
        if _tattoo_visibility_requested and anchor_images:
            _filtered_pairs = [
                (img, t) for img, t in zip(anchor_images, anchor_types) if t != "torso"
            ]
            if _filtered_pairs:
                anchor_images, anchor_types = zip(*_filtered_pairs)
                anchor_images, anchor_types = list(anchor_images), list(anchor_types)
            else:
                anchor_images, anchor_types = [], []

        # Reorder anchor refs.  When tattoos are visible (tattoo_primary=True) the
        # body-canon reference becomes the dominant grounding signal — tattoo_layout /
        # body_front at position 0 so OpenAI's images.edit base and Google's attention
        # head both lock onto body canon before the face portrait.
        # Covered clothing falls through to face-first ordering unchanged.
        _tattoo_primary = _tattoo_visibility_requested
        anchor_images, anchor_types = _reorder_anchor_refs(
            anchor_images, anchor_types,
            tattoo_primary=_tattoo_primary,
        )

        # Canonical body-front mode: enforce strict ref whitelist.
        # body_front is the single visual truth — drop everything except body_front,
        # front, and three_quarter. This prevents provider averaging across too many refs.
        if _body_front_canonical and anchor_images:
            _canonical_pairs = [
                (img, t) for img, t in zip(anchor_images, anchor_types)
                if t in _CANONICAL_BODY_REF_ALLOWED
            ]
            if _canonical_pairs:
                anchor_images, anchor_types = zip(*_canonical_pairs)
                anchor_images, anchor_types = list(anchor_images), list(anchor_types)
            else:
                anchor_images, anchor_types = [], []

        # Apply provider ref cap — lowest-priority refs are cut first because
        # _reorder_anchor_refs already placed them at the tail.
        if len(anchor_images) > _MAX_PROVIDER_REFS:
            anchor_images = anchor_images[:_MAX_PROVIDER_REFS]
            anchor_types = anchor_types[:_MAX_PROVIDER_REFS]

        # BODY_REF_USED: final anchor_types actually sent to the provider.
        # Logged after canonical filtering AND provider cap — this is ground truth.
        logger.warning(
            "BODY_REF_USED character_id=%s final_anchor_types=%s "
            "canonical_mode=%s total_refs=%d "
            "body_front_present=%s left_right_detail_present=%s support_body_refs_present=%s",
            character_id,
            anchor_types,
            _body_front_canonical,
            len(anchor_images),
            any(t == "body_identity:body_front" for t in anchor_types),
            any(
                t in (
                    "body_identity:body_left_detail",
                    "body_identity:body_right_detail",
                )
                for t in anchor_types
            ),
            any(
                t in (
                    "body_identity:body_back",
                    "body_identity:body_map",
                )
                for t in anchor_types
            ),
        )

        logger.info(
            "BODY-IDENTITY-REFS character_id=%s body_visible=%s markings_visible=%s "
            "body_refs_used=%s tattoo_layout_used=%s body_canon_refs_used=%s total_refs=%d",
            character_id,
            _body_visible,
            _markings_visible,
            _bi_refs_used,
            _tattoo_layout_used,
            _bc_anchors_used,
            len(anchor_images),
        )

        # ── BODY-TRUTH-STATE structured diagnostic ────────────────────────
        logger.info(
            "BODY-TRUTH-STATE character_id=%s body_truth_mode=%s "
            "body_front_loaded=%s body_markings_present=%s body_front_source=%s",
            character_id,
            bool(_bc_markings),
            _bf_loaded,
            bool(_bc_markings),
            _body_front_source,
        )

        # ── BODY-CANON-VISIBILITY diagnostic ─────────────────────────────
        if not _tattoo_visibility_requested and _clothing_detected:
            _bc_skipped_reason = "covered_by_clothing"
        elif not _tattoo_visibility_requested:
            _bc_skipped_reason = "not_requested"
        elif _tattoo_visibility_requested and _clothing_detected:
            _bc_skipped_reason = "prompt_costume_priority"
        else:
            _bc_skipped_reason = "none"
        logger.info(
            "BODY-CANON-VISIBILITY character_id=%s "
            "clothing_detected=%s tattoo_visibility_requested=%s "
            "body_anchor_used=%s tattoo_layout_used=%s "
            "skipped_reason=%s",
            character_id,
            _clothing_detected,
            _tattoo_visibility_requested,
            bool(_bc_anchors_used),
            _tattoo_layout_used,
            _bc_skipped_reason,
        )

        # ── Sleeve enforcement ────────────────────────────────────────────
        _sleeve_left_required = False
        _sleeve_right_required = False
        _sleeve_missing_refs: list[str] = []

        for _bm in _bc_markings:
            if not is_sleeve_marking(_bm):
                continue
            _bm_side = get_arm_side(_bm.placement)
            if _bm_side == "left" and "left_arm" in _p1_visible_regions:
                _sleeve_left_required = True
                if _bm.anchor_status != "locked":
                    _sleeve_missing_refs.append(f"left_sleeve_anchor:status={_bm.anchor_status}({_bm.id})")
            elif _bm_side == "right" and "right_arm" in _p1_visible_regions:
                _sleeve_right_required = True
                if _bm.anchor_status != "locked":
                    _sleeve_missing_refs.append(f"right_sleeve_anchor:status={_bm.anchor_status}({_bm.id})")

        if _body_front_canonical:
            # Canonical mode: body_front is the sole visual truth.
            # No text essays needed — the ref image carries left/right placement.
            _sleeve_enforcement_str = ""
            _arm_side_binding_str = ""
        elif _tattoo_visibility_requested:
            # Simplified fallback (body_front absent): restore full binding text.
            # Short note alone is insufficient — providers need explicit L/R exclusivity
            # rules to prevent merging distinct tattoos onto one arm.
            # Phase 1 (#23): drive off the beta-safe visible regions so covered arms
            # never get a "sleeve must be present" instruction.
            _sleeve_enforcement_str = build_sleeve_enforcement_str(_bc_markings, _p1_visible_regions)
            _arm_side_binding_str = build_arm_side_binding_str(_bc_markings, _p1_visible_regions)
        else:
            _sleeve_enforcement_str = build_sleeve_enforcement_str(_bc_markings, _p1_visible_regions)
            _arm_side_binding_str = build_arm_side_binding_str(_bc_markings, _p1_visible_regions)

        if (_sleeve_left_required or _sleeve_right_required) and not _tattoo_layout_used and not _tattoo_visibility_requested:
            _tl_status = (_bi_slots.get("tattoo_layout") or {}).get("status", "missing")
            if _tl_status != "locked":
                _sleeve_missing_refs.append(f"tattoo_layout:status={_tl_status}")
                logger.warning(
                    "BODY-CANON-WARNING sleeve_visible_but_no_layout_anchor=true "
                    "character_id=%s left_sleeve_required=%s right_sleeve_required=%s",
                    character_id, _sleeve_left_required, _sleeve_right_required,
                )

        _left_anchor_used = any("left_arm" in a for a in _bc_anchors_used)
        _right_anchor_used = any("right_arm" in a for a in _bc_anchors_used)
        logger.info(
            "BODY-CANON-SLEEVE character_id=%s "
            "exposed_arms=%s "
            "left_sleeve_required=%s right_sleeve_required=%s "
            "tattoo_layout_used=%s "
            "left_anchor_used=%s right_anchor_used=%s "
            "missing_required_refs=%s",
            character_id,
            bool(_bc_visible_regions),
            _sleeve_left_required,
            _sleeve_right_required,
            _tattoo_layout_used,
            _left_anchor_used,
            _right_anchor_used,
            _sleeve_missing_refs,
        )

        # ── SCENE-IDENTITY-BALANCE diagnostic ────────────────────────────
        _identity_lock_str = (anchor_data or {}).get("identity_lock_string", "") or ""  # type: ignore[union-attr]
        logger.info(
            "SCENE-IDENTITY-BALANCE character_id=%s "
            "scene_complexity=%s full_body_anchor_used=%s suppressed_reason=%s "
            "scene_tokens_count=%d identity_tokens_count=%d",
            character_id,
            _scene_complexity,
            _full_body_anchor_used,
            "scene_override" if _full_body_gated else "none",
            len(provider_prompt.split()),
            len(_identity_lock_str.split()),
        )

        logger.info(
            "DIAG strict_identity_state character_id=%s provider=%s "
            "anchors_loaded=%d anchor_types=%s multi_image_supported=%s "
            "face_ref_bytes=%s",
            character_id,
            resolved_provider_name,
            len(anchor_images),
            anchor_types,
            provider_supports_multi,
            f"{len(face_ref_bytes)}b" if face_ref_bytes else "None",
        )
        logger.info(
            "strict_identity_enabled character_id=%s provider=%s "
            "anchors_loaded=%d anchor_types=%s multi_image_supported=%s",
            character_id,
            resolved_provider_name,
            len(anchor_images),
            anchor_types,
            provider_supports_multi,
        )

        # ── IDENTITY-REFS unified summary ─────────────────────────────────
        _pack_stages = compute_pack_stages(character)
        logger.info(
            "IDENTITY-REFS character_id=%s "
            "pack_face=%s pack_body=%s pack_marks=%s "
            "anchor_types=%s "
            "face_ref=%s body_front=%s tattoo_layout=%s "
            "scene_complexity=%s full_body_gated=%s",
            character_id,
            _pack_stages["face"],
            _pack_stages["body"],
            _pack_stages["marks"],
            anchor_types,
            face_ref_bytes is not None,
            any(t == "body_identity:body_front" for t in anchor_types),
            any(t == "body_identity:tattoo_layout" for t in anchor_types),
            _scene_complexity,
            _full_body_gated,
        )

        # ── Provider ref check ────────────────────────────────────────────
        _tl_ref_in_types = any(t == "body_identity:tattoo_layout" for t in anchor_types)
        _ba_ref_count = sum(1 for t in anchor_types if t.startswith("body_anchor:"))

        # Google-specific: when both arm anchors are sent, the model can merge the two
        # tattoo designs into one arm.  Inject a hard separation rule into the sleeve
        # enforcement block so the text and image signals both reinforce separation.
        if resolved_provider_name == "google" and _ba_ref_count >= 2:
            _anti_merge = (
                "Left and right tattoos must remain separate — "
                "do not combine designs onto one arm."
            )
            _sleeve_enforcement_str = (
                _sleeve_enforcement_str.rstrip(". ") + ". " + _anti_merge
                if _sleeve_enforcement_str else _anti_merge
            )
            logger.info(
                "PROVIDER-REF-CHECK character_id=%s google_anti_merge_injected=True "
                "body_anchor_count=%d",
                character_id, _ba_ref_count,
            )

        logger.info(
            "PROVIDER-REF-CHECK character_id=%s "
            "tattoo_primary=%s provider_supports_multi=%s "
            "tattoo_layout_ref_present=%s tattoo_layout_ref_sent=%s "
            "body_front_sent=%s body_anchor_count=%d "
            "body_canon_has_text=%s sleeve_has_text=%s "
            "first_ref=%s final_ordered_refs=%s",
            character_id,
            _tattoo_primary,
            provider_supports_multi,
            bool((_bi_slots.get("tattoo_layout") or {}).get("url")),
            _tl_ref_in_types,
            any(t == "body_identity:body_front" for t in anchor_types),
            _ba_ref_count,
            bool(_body_canon_str),
            bool(_sleeve_enforcement_str),
            anchor_types[0] if anchor_types else "none",
            anchor_types,
        )
        if not provider_supports_multi and (_body_canon_str or _sleeve_enforcement_str):
            logger.info(
                "PROVIDER-REF-CHECK character_id=%s note=single_image_path_text_only "
                "body_canon_chars=%d sleeve_chars=%d — tattoo identity carried by text only",
                character_id,
                len(_body_canon_str),
                len(_sleeve_enforcement_str),
            )

        # Provider is required — stub fallback is never acceptable for character images
        if provider is None:
            logger.info(
                "strict_identity_outcome character_id=%s outcome=controlled_failure "
                "reason=provider_unavailable retry_attempted=False",
                character_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Character image generation could not be completed: "
                    "image provider is unavailable. Please try again later."
                ),
            )

        # ── Attempt 1 ──────────────────────────────────────────
        strict_prompt = _build_strict_identity_prompt(
            base_prompt=provider_prompt,
            anchor_data=anchor_data,  # type: ignore[arg-type]
            character_name=character.name,
            retry=False,
            body_canon_str=_body_canon_str,
            arm_side_binding_str=_arm_side_binding_str,
            sleeve_enforcement_str=_sleeve_enforcement_str,
            scene_complex=_scene_complexity != "low",
            character_id=character_id,
            arm_visibility_mode=_arm_visibility_mode,
            provider_name=resolved_provider_name,
            tattoo_simplified=_tattoo_visibility_requested,
        )

        # DIAG: full identity payload snapshot — what is actually sent to the provider
        _diag_lock = (anchor_data or {}).get("identity_lock_string", "") or ""  # type: ignore[union-attr]
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
        _kw_hits = [p for p in _HAIR_PATTERNS if p in strict_prompt.lower()]
        logger.info(
            "DIAG identity_payload_debug character_id=%s provider=%s "
            "lock_string=%r spec_hair=%s anchor_slots=%s face_ref_available=%s "
            "final_prompt_len=%d hair_kw_hits=%s",
            character_id, resolved_provider_name,
            _diag_lock[:120],
            _diag_spec_hair,
            list(((anchor_data or {}).get("anchors") or {}).keys()),  # type: ignore[union-attr]
            face_ref_bytes is not None,
            len(strict_prompt),
            _kw_hits,
        )
        if _kw_hits:
            logger.warning(
                "DIAG hair_keyword_in_prompt character_id=%s hits=%s snippet=%r",
                character_id, _kw_hits, strict_prompt[:200],
            )

        # Tier 1: multi-image anchor conditioning (B19)
        if provider_supports_multi and anchor_images:
            logger.info("DIAG tier1_attempt character_id=%s anchor_count=%d", character_id, len(anchor_images))
            try:
                png_bytes = provider.generate_with_anchors(
                    prompt=strict_prompt,
                    anchor_images=anchor_images,
                )
                actual_provider_name = resolved_provider_name
                multi_image_used = True
                logger.info("DIAG tier1_success character_id=%s", character_id)
            except (ValueError, RuntimeError, NotImplementedError) as _t1e:
                logger.warning(
                    "DIAG tier1_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t1e),
                )
                logger.info(
                    "anchor_multi_image_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )
        else:
            logger.info(
                "DIAG tier1_skip character_id=%s reason=%s anchors=%d",
                character_id,
                "multi_image_not_supported" if not provider_supports_multi else "no_anchors",
                len(anchor_images),
            )
            logger.info(
                "anchor_conditioning_fallback character_id=%s "
                "reason=multi_image_not_supported anchors_available=%d using=face_ref",
                character_id,
                len(anchor_images),
            )

        # Tier 2: single-image grounded (face-ref crop)
        if png_bytes is None and face_ref_bytes is not None:
            logger.info("DIAG tier2_attempt character_id=%s face_ref_bytes=%d", character_id, len(face_ref_bytes))
            try:
                png_bytes = provider.generate_grounded_image(
                    prompt=strict_prompt,
                    reference_image_bytes=face_ref_bytes,
                )
                actual_provider_name = resolved_provider_name
                used_face_ref = True
                logger.info("DIAG tier2_success character_id=%s", character_id)
            except (ValueError, RuntimeError, NotImplementedError) as _t2e:
                logger.warning(
                    "DIAG tier2_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t2e),
                )
                logger.info(
                    "strict_identity_grounded_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )
        elif png_bytes is None:
            logger.info(
                "DIAG tier2_skip character_id=%s reason=face_ref_not_available",
                character_id,
            )

        # Tier 3: text-only strict (no image reference available)
        if png_bytes is None:
            logger.info("DIAG tier3_attempt character_id=%s text_only_fallback=TRUE", character_id)
            try:
                png_bytes = provider.generate_image(prompt=strict_prompt)
                actual_provider_name = resolved_provider_name
                logger.info("DIAG tier3_success character_id=%s WARNING=text_only_no_identity_grounding", character_id)
            except (ValueError, RuntimeError) as _t3e:
                logger.warning(
                    "DIAG tier3_failed character_id=%s provider=%s error=%r",
                    character_id, resolved_provider_name, str(_t3e),
                )
                logger.info(
                    "strict_identity_text_failed attempt=1 character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )

        # ── Attempt 2 (retry with escalated wording) ───────────
        if png_bytes is None:
            retry_attempted = True
            logger.info("strict_identity_retry character_id=%s", character_id)

            retry_prompt = _build_strict_identity_prompt(
                base_prompt=provider_prompt,
                anchor_data=anchor_data,  # type: ignore[arg-type]
                character_name=character.name,
                retry=True,
                body_canon_str=_body_canon_str,
                arm_side_binding_str=_arm_side_binding_str,
                sleeve_enforcement_str=_sleeve_enforcement_str,
                scene_complex=_scene_complexity != "low",
                character_id=character_id,
                arm_visibility_mode=_arm_visibility_mode,
                provider_name=resolved_provider_name,
                tattoo_simplified=_tattoo_visibility_requested,
            )

            if provider_supports_multi and anchor_images:
                logger.info("DIAG retry_tier1_attempt character_id=%s", character_id)
                try:
                    png_bytes = provider.generate_with_anchors(
                        prompt=retry_prompt,
                        anchor_images=anchor_images,
                    )
                    actual_provider_name = resolved_provider_name
                    multi_image_used = True
                    logger.info("DIAG retry_tier1_success character_id=%s", character_id)
                except (ValueError, RuntimeError, NotImplementedError) as _r1e:
                    logger.warning(
                        "DIAG retry_tier1_failed character_id=%s error=%r", character_id, str(_r1e),
                    )
                    logger.info(
                        "anchor_multi_image_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

            if png_bytes is None and face_ref_bytes is not None:
                logger.info("DIAG retry_tier2_attempt character_id=%s", character_id)
                try:
                    png_bytes = provider.generate_grounded_image(
                        prompt=retry_prompt,
                        reference_image_bytes=face_ref_bytes,
                    )
                    actual_provider_name = resolved_provider_name
                    used_face_ref = True
                    logger.info("DIAG retry_tier2_success character_id=%s", character_id)
                except (ValueError, RuntimeError, NotImplementedError) as _r2e:
                    logger.warning(
                        "DIAG retry_tier2_failed character_id=%s error=%r", character_id, str(_r2e),
                    )
                    logger.info(
                        "strict_identity_grounded_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

            if png_bytes is None:
                logger.info("DIAG retry_tier3_attempt character_id=%s text_only_fallback=TRUE", character_id)
                try:
                    png_bytes = provider.generate_image(prompt=retry_prompt)
                    actual_provider_name = resolved_provider_name
                    logger.info("DIAG retry_tier3_success character_id=%s WARNING=text_only_no_grounding", character_id)
                except (ValueError, RuntimeError) as _r3e:
                    logger.warning(
                        "DIAG retry_tier3_failed character_id=%s error=%r", character_id, str(_r3e),
                    )
                    logger.info(
                        "strict_identity_text_failed attempt=2 character_id=%s provider=%s",
                        character_id,
                        resolved_provider_name,
                    )

        # ── Controlled failure — do not save non-conditioned output ──
        if png_bytes is None:
            logger.info(
                "strict_identity_outcome character_id=%s outcome=controlled_failure "
                "retry_attempted=%s",
                character_id,
                retry_attempted,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Character image generation could not be completed with reliable "
                    "identity conditioning. Please try again. If the issue persists, "
                    "regenerate the character's identity pack."
                ),
            )

        logger.info(
            "strict_identity_outcome character_id=%s outcome=success "
            "retry_attempted=%s used_face_ref=%s multi_image_used=%s anchors_attached=%d",
            character_id,
            retry_attempted,
            used_face_ref,
            multi_image_used,
            len(anchor_images),
        )
        file_path = save_image(png_bytes)

    # ── NORMAL MODE (include_character=False) ─────────────────────
    else:
        anchor_images = []
        anchor_types = []

        if provider is not None:
            try:
                png_bytes = provider.generate_image(prompt=provider_prompt)
                actual_provider_name = resolved_provider_name
            except (ValueError, RuntimeError):
                logger.info(
                    "image_generator text_gen_failed character_id=%s provider=%s",
                    character_id,
                    resolved_provider_name,
                )

        if png_bytes is None:
            fallback = get_fallback_provider()
            if fallback is not None:
                try:
                    png_bytes = fallback.generate_image(prompt=provider_prompt)
                    actual_provider_name = "fal"
                except (ValueError, RuntimeError):
                    logger.info(
                        "image_generator fallback_failed character_id=%s", character_id
                    )

        if png_bytes is not None:
            file_path = save_image(png_bytes)
        else:
            file_path = generate_placeholder_png(
                label=character.name,
                sublabel=body.prompt[:80],
                role="generated",
            )
            actual_provider_name = "stub"

    # ── Cover composition retry (character-inclusive covers only) ─────────
    # No image-content heuristic can detect poor banner composition without
    # vision infrastructure. We apply one deterministic retry with an
    # escalated prompt whenever a character is included in a cover image.
    # The retry result supersedes the first-pass result; if it fails the
    # first-pass image is kept and committed as normal.
    cover_retry_attempted = False
    cover_retry_succeeded = False
    if body.is_cover and body.include_character and png_bytes is not None:
        cover_retry_attempted = True
        retry_base = _COVER_RETRY_PROMPT + body.prompt.strip()
        cover_retry_str_prompt = _build_strict_identity_prompt(
            base_prompt=retry_base[:_STRICT_IDENTITY_PROMPT_MAX_CHARS],
            anchor_data=anchor_data,  # type: ignore[arg-type]
            character_name=character.name,
            retry=False,
            body_canon_str=_body_canon_str,
            arm_side_binding_str=_arm_side_binding_str,
            sleeve_enforcement_str=_sleeve_enforcement_str,
            scene_complex=_scene_complexity != "low",
            character_id=character_id,
            arm_visibility_mode=_arm_visibility_mode,
            provider_name=resolved_provider_name,
            tattoo_simplified=_tattoo_visibility_requested,
        )
        cover_retry_png: bytes | None = None
        if provider_supports_multi and anchor_images:
            try:
                cover_retry_png = provider.generate_with_anchors(
                    prompt=cover_retry_str_prompt,
                    anchor_images=anchor_images,
                )
            except (ValueError, RuntimeError, NotImplementedError):
                pass
        if cover_retry_png is None and face_ref_bytes is not None:
            try:
                cover_retry_png = provider.generate_grounded_image(
                    prompt=cover_retry_str_prompt,
                    reference_image_bytes=face_ref_bytes,
                )
            except (ValueError, RuntimeError, NotImplementedError):
                pass
        if cover_retry_png is None:
            try:
                cover_retry_png = provider.generate_image(prompt=cover_retry_str_prompt)
            except (ValueError, RuntimeError):
                pass
        if cover_retry_png is not None:
            file_path = save_image(cover_retry_png)
            png_bytes = cover_retry_png
            cover_retry_succeeded = True
            logger.info("cover_retry_succeeded character_id=%s", character_id)
        else:
            logger.info(
                "cover_retry_failed_using_first_pass character_id=%s", character_id
            )

    # ── Persist image record ──────────────────────────────────────
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        "include_character": body.include_character,
        "character_id": character_id if body.include_character else None,
        "prompt": body.prompt,
        "strict_identity_mode": body.include_character,
        "is_cover": body.is_cover,
    }
    if body.include_character:
        metadata["used_face_ref"] = used_face_ref
        metadata["identity_hash"] = identity_hash
        metadata["strict_identity_retry"] = retry_attempted
        metadata["anchors_attached"] = len(anchor_images)
        metadata["anchor_types"] = anchor_types
        metadata["multi_image_used"] = multi_image_used
        metadata["face_anchor_boosted"] = _face_anchor_boosted  # B21
        metadata["cover_retry_attempted"] = cover_retry_attempted
        metadata["cover_retry_succeeded"] = cover_retry_succeeded
        # Body Truth System diagnostics — used during torture testing
        metadata["body_truth_mode"] = bool(_bc_markings)
        metadata["body_front_loaded"] = _bf_loaded
        metadata["body_markings_present"] = bool(_bc_markings)
        metadata["body_front_source"] = _body_front_source

    img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,  # B22: stamp for quota tracking
        kind=ImageKindEnum.COVER if body.is_cover else ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider=actual_provider_name,
        prompt_summary=body.prompt[:200],
        metadata_json=metadata,
        file_path=file_path,
    )
    db.add(img)
    db.commit()
    db.refresh(img)

    logger.info(
        "image_generator_result image_id=%s character_id=%s provider=%s "
        "provider_option=%s include_character=%s anchors_attached=%s",
        img.id,
        character_id,
        actual_provider_name,
        effective_option,
        body.include_character,
        len(anchor_images),
    )

    return CharacterImageRead.model_validate(img)
