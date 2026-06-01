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
from app.services.image_provider import (
    get_provider_for_option,
    get_fallback_provider,
    resolve_canon_provider_option,
)
from app.services.stub_image_generator import generate_placeholder_png
from app.models.character_identity_canon import CharacterIdentityCanon
from app.services.canon_compiler import (
    compile_canon_prompt,
    has_any_canon_content,
)
from app.services.scene_router import route_canon_refs
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
    # Beta: Google (option2) is the default Canon provider. OpenAI (option1) is
    # admin-only and falls back to Google for non-admins (enforced server-side).
    provider_option: Literal["option1", "option2"] = "option2"
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


def _build_arm_side_lock_str(exposed_markings: list) -> str:
    """Side-lock + negative-side text to prevent mirroring.

    Emitted only when at least one arm carries an exposed marking AND the opposite
    arm has no exposed marking — declares the marked arm and explicitly states the
    other arm is bare so the model does not mirror a tattoo onto bare skin.
    """
    exposed_sides = {
        s for m in exposed_markings if (s := get_arm_side(m.placement)) is not None
    }
    if not exposed_sides:
        return ""
    bare_sides = {"left", "right"} - exposed_sides
    if not bare_sides:
        return ""
    vis_txt = " and ".join(sorted(exposed_sides))
    bare_txt = " and ".join(sorted(bare_sides))
    return (
        f"ARM SIDE LOCK: Only the {vis_txt} arm has visible tattoos. "
        f"The {bare_txt} arm is bare skin. "
        f"No tattoos, writing, symbols, or marks on the {bare_txt} arm."
    )


def _classify_marking_coverage(marking, prompt_lower: str) -> str:
    """Return 'exposed' or 'covered' for this marking in the current scene.

    Clothing-coverage classifier for Task #26 — replaces Phase 1 "reliably visible".
    The body identity ref images are ALWAYS loaded regardless of this result; this
    function only determines the prompt text (permanent feature vs coverage note).

    Rules:
    - Always-visible placements (neck/face/hands) → exposed.
    - Full-sleeve markings on a broad-arm placement (left_full_arm / right_full_arm):
        * Whole arm bare → exposed.
        * Forearm exposed (rolled sleeves / t-shirt) → exposed (sleeve exception —
          the forearm portion of a full sleeve is part of the sleeve design).
        * Otherwise → covered.
    - Non-sleeve arm markings: use the precise anatomical region exposure so that
      a forearm marking correctly reports "exposed" when sleeves are rolled, while
      an upper-arm marking correctly reports "covered".
    - Unknown/no-signal exposure → covered (conservative; refs still loaded).
    """
    if marking.placement in _ALWAYS_VISIBLE_PLACEMENTS:
        return "exposed"
    side = get_arm_side(marking.placement)
    if side is not None:
        if is_sleeve_marking(marking):
            # Full-sleeve marking: forearm portion is part of the sleeve design.
            # Exposed whenever the whole arm is bare OR the forearm is exposed.
            if _classify_region_exposure(f"broad_{side}_arm", prompt_lower) == "exposed":
                return "exposed"
            forearm_region = f"{side}_forearm"
            if _classify_region_exposure(forearm_region, prompt_lower) == "exposed":
                return "exposed"
            return "covered"
        else:
            # Non-sleeve: use the precise region so forearm vs upper-arm exposure
            # is correctly distinguished (e.g. rolled sleeves expose forearm only).
            region = _classify_marking_region(marking.placement)
            return "exposed" if _classify_region_exposure(region, prompt_lower) == "exposed" else "covered"
    region = _classify_marking_region(marking.placement)
    return "exposed" if _classify_region_exposure(region, prompt_lower) == "exposed" else "covered"


def _build_permanent_marking_block(markings: list, prompt_lower: str) -> str:
    """Build a permanent-features block for the image prompt (Task #26).

    Body identity ref images are always loaded as the visual ground truth.
    This block tells the model which markings are currently visible (permanent
    features to reproduce from the refs) and which are covered by clothing.

    Exposed markings: described as permanent features with a ref-match instruction.
    Covered markings: one-line clothing-coverage note — no 'DO NOT RENDER' language
    (the refs are still loaded; the coverage note is sufficient for the model).
    Returns '' when there are no markings.
    """
    if not markings:
        return ""
    exposed: list = []
    covered: list = []
    for m in markings:
        if _classify_marking_coverage(m, prompt_lower) == "exposed":
            exposed.append(m)
        else:
            covered.append(m)
    parts: list[str] = []
    if exposed:
        v = "; ".join(build_compact_token(m) for m in exposed)
        parts.append(
            "PERMANENT BODY MARKINGS — always present on exposed skin, reproduced "
            f"exactly as shown in the reference images: {v}"
        )
    if covered:
        c = "; ".join(build_compact_token(m) for m in covered)
        parts.append(f"COVERED BY CLOTHING — not visible in this scene: {c}")
    return ". ".join(parts)


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
    """Generate a single image using CharacterIdentityCanon as the only identity truth.

    Architecture (Identity OS — canon single source):
        Generate Images → CharacterIdentityCanon → canon_compiler → provider

    When include_character=True:
      - CharacterIdentityCanon is required. If missing or incomplete, returns a
        graceful 409 "Character canon incomplete".
      - The prompt is compiled by canon_compiler.compile_canon_prompt in strict
        order: face → body → permanent marks → requested accessories → scene →
        locked-canon clause. Removable accessories inject ONLY when their trigger
        keywords appear in the scene prompt.
      - Reference images are the locked face/body canon slots selected by the
        scene-aware reference router (route_canon_refs), which deterministically
        picks scene-relevant slots from the prompt and falls back to the static
        canonical ordering when the prompt is ambiguous. No identity_anchor_json,
        body_identity_json, or CharacterStyleElements are consulted as identity truth.

    When include_character=False, the user's prompt is used as-is (plain scene, no
    identity conditioning).

    Scene images always save as SCENE_ONLY (or COVER for is_cover); canon is never
    mutated here.

    provider_option: option1 → OpenAI | option2 → Google
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

    # ── B22: Weekly allowance check (admins bypass; deducted on success) ──
    quota_error = check_weekly_quota(current_user, db)
    if quota_error is not None:
        return quota_error

    # ── Provider resolution + beta gating ──────────────────────────
    requested_option = body.provider_option if settings.IMAGE_GENERATOR_PROVIDER_TOGGLE else "option1"
    # OpenAI (option1) is admin-only for beta; non-admins fall back to Google.
    effective_option, provider_gate_meta = resolve_canon_provider_option(
        requested_option, is_admin=bool(current_user.is_admin)
    )
    resolved_provider_name = _OPTION_PROVIDER_NAMES[effective_option]
    if provider_gate_meta:
        logger.info(
            "IMAGE_GEN_PROVIDER_GATED character_id=%s user_id=%s requested=%s effective=%s reason=%s",
            character_id, current_user.id, requested_option, effective_option,
            provider_gate_meta.get("provider_fallback_reason"),
        )

    base_prompt = body.prompt.strip()

    # Cover mode: prepend banner-composition directives before the user's prompt.
    if body.is_cover:
        cover_block = _COVER_BANNER_PREFIX
        if body.include_character:
            cover_block += _COVER_CHARACTER_FRAMING
        base_prompt = cover_block + base_prompt

    # ── Identity truth: CharacterIdentityCanon ONLY ───────────────
    canon: CharacterIdentityCanon | None = None
    reference_urls: list[str] = []
    using_canon = False

    if body.include_character:
        canon = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == character_id)
            .first()
        )
        if canon is None or not has_any_canon_content(canon):
            # Graceful fallback — no legacy identity sources are consulted.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Character canon incomplete",
            )
        compiled_prompt = compile_canon_prompt(
            canon,
            base_prompt,
            include_accessories=True,
        )
        # P10: scene-aware reference routing replaces static ordering.
        # Route on the raw user scene text (not the cover-prefixed prompt).
        reference_urls, scene_meta = route_canon_refs(body.prompt, canon)
        using_canon = True
    else:
        compiled_prompt = base_prompt

    logger.info(
        "IMAGE_GEN_START character_id=%s include_character=%s using_canon=%s "
        "camera=%s routed=%s exposure=%s refs=%d prompt_len=%d prompt_preview=%r",
        character_id, body.include_character, using_canon,
        scene_meta.camera if using_canon else "n/a",
        scene_meta.routed if using_canon else False,
        scene_meta.exposure if using_canon else [],
        len(reference_urls), len(compiled_prompt), compiled_prompt[:120],
    )

    # ── Load reference image bytes (cap at 6) ─────────────────────
    ref_bytes: list[bytes] = []
    for url in reference_urls[:6]:
        try:
            b = load_image_bytes(url)
            ref_bytes.append(b)
            logger.info("IMAGE_GEN_REF_LOADED character_id=%s url=%s bytes=%d", character_id, url, len(b))
        except Exception as exc:
            logger.warning("IMAGE_GEN_REF_LOAD_FAILED character_id=%s url=%s error=%r", character_id, url, str(exc))

    # ── Resolve provider ──────────────────────────────────────────
    try:
        provider = get_provider_for_option(effective_option)
    except (RuntimeError, ValueError):
        logger.warning(
            "image_generator provider_unavailable option=%s provider=%s character_id=%s",
            effective_option, resolved_provider_name, character_id,
        )
        provider = None

    png_bytes: bytes | None = None
    actual_provider_name = "stub"
    multi_image_used = False
    used_ref = False

    # ── Generate: multi-image → grounded → text-only → fal → stub ──
    provider_supports_multi = bool(getattr(provider, "supports_multi_image_input", False))
    if provider is not None and ref_bytes and provider_supports_multi:
        try:
            png_bytes = provider.generate_with_anchors(
                prompt=compiled_prompt,
                anchor_images=ref_bytes,
            )
            actual_provider_name = resolved_provider_name
            multi_image_used = True
            logger.info("IMAGE_GEN_MULTI_IMAGE_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("IMAGE_GEN_MULTI_IMAGE_FAILED character_id=%s fallback=grounded", character_id)

    if png_bytes is None and provider is not None and ref_bytes:
        try:
            png_bytes = provider.generate_grounded_image(
                prompt=compiled_prompt,
                reference_image_bytes=ref_bytes[0],
            )
            actual_provider_name = resolved_provider_name
            used_ref = True
            logger.info("IMAGE_GEN_GROUNDED_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError, NotImplementedError, AttributeError):
            logger.info("IMAGE_GEN_GROUNDED_FAILED character_id=%s fallback=text", character_id)

    if png_bytes is None and provider is not None:
        try:
            png_bytes = provider.generate_image(prompt=compiled_prompt)
            actual_provider_name = resolved_provider_name
            logger.info("IMAGE_GEN_TEXT_ONLY_SUCCESS character_id=%s", character_id)
        except (ValueError, RuntimeError):
            logger.info("IMAGE_GEN_TEXT_FAILED character_id=%s fallback=fal", character_id)

    if png_bytes is None:
        fallback = get_fallback_provider()
        if fallback is not None:
            try:
                png_bytes = fallback.generate_image(prompt=compiled_prompt)
                actual_provider_name = "fal"
                logger.info("IMAGE_GEN_FAL_SUCCESS character_id=%s", character_id)
            except (ValueError, RuntimeError):
                pass

    if png_bytes is not None:
        file_path = save_image(png_bytes)
    else:
        file_path = generate_placeholder_png(
            label=character.name,
            sublabel=body.prompt[:80],
            role="generated",
        )
        actual_provider_name = "stub"
        logger.info("IMAGE_GEN_STUB character_id=%s", character_id)

    # ── Cover composition retry (character-inclusive covers only) ──
    # One deterministic retry with an escalated cover prompt, still sourced
    # entirely from canon. Supersedes the first pass on success.
    cover_retry_attempted = False
    cover_retry_succeeded = False
    if body.is_cover and body.include_character and canon is not None and provider is not None and png_bytes is not None:
        cover_retry_attempted = True
        retry_prompt = compile_canon_prompt(
            canon,
            _COVER_RETRY_PROMPT + body.prompt.strip(),
            include_accessories=True,
        )
        cover_retry_png: bytes | None = None
        if ref_bytes and provider_supports_multi:
            try:
                cover_retry_png = provider.generate_with_anchors(prompt=retry_prompt, anchor_images=ref_bytes)
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        if cover_retry_png is None and ref_bytes:
            try:
                cover_retry_png = provider.generate_grounded_image(prompt=retry_prompt, reference_image_bytes=ref_bytes[0])
            except (ValueError, RuntimeError, NotImplementedError, AttributeError):
                pass
        if cover_retry_png is None:
            try:
                cover_retry_png = provider.generate_image(prompt=retry_prompt)
            except (ValueError, RuntimeError):
                pass
        if cover_retry_png is not None:
            file_path = save_image(cover_retry_png)
            png_bytes = cover_retry_png
            cover_retry_succeeded = True
            logger.info("cover_retry_succeeded character_id=%s", character_id)
        else:
            logger.info("cover_retry_failed_using_first_pass character_id=%s", character_id)

    # ── Persist image record — SCENE_ONLY / COVER, never canon ────
    metadata: dict = {
        "image_generator": True,
        "provider_option": effective_option,
        "provider": actual_provider_name,
        "include_character": body.include_character,
        "character_id": character_id if body.include_character else None,
        "prompt": body.prompt,
        "is_cover": body.is_cover,
        # Identity OS: generated scenes are not canon.
        "scene_only": not body.is_cover,
        # Canon-contract diagnostics (replace legacy strict-identity metadata).
        "canon_used": using_canon,
        "refs_count": len(ref_bytes),
        "compiled_prompt": compiled_prompt[:400],
    }
    if body.include_character:
        metadata["multi_image_used"] = multi_image_used
        metadata["used_ref"] = used_ref
        metadata["cover_retry_attempted"] = cover_retry_attempted
        metadata["cover_retry_succeeded"] = cover_retry_succeeded

    # Beta provider-gating audit trail (empty unless a fallback occurred).
    metadata.update(provider_gate_meta)

    img = CharacterImage(
        character_id=character_id,
        user_id=current_user.id,  # B22: stamp for quota tracking
        # Identity OS: generated scenes default to SCENE_ONLY — promotion to
        # face/body canon must be explicit via the canon flow.
        kind=ImageKindEnum.COVER if body.is_cover else ImageKindEnum.SCENE_ONLY,
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
        "provider_option=%s include_character=%s canon_used=%s refs=%d",
        img.id, character_id, actual_provider_name, effective_option,
        body.include_character, using_canon, len(ref_bytes),
    )

    return CharacterImageRead.model_validate(img)
