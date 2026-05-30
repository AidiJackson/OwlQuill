"""Canon prompt compiler — clean strict hierarchy.

Compiles a generation prompt from CharacterIdentityCanon in exact order:
  1. FACE CANON
  2. BODY CANON
  3. PERMANENT BODY MARKS (visibility-gated)
  4. REQUESTED REMOVABLE ACCESSORIES (trigger-keyword matched)
  5. USER SCENE PROMPT
  6. LOCKED CANON CLAUSE

No other source of identity truth is consulted here.
The old identity_compiler.py remains for legacy characters without a canon record.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.schemas.canon import (
    BodyCanonData,
    FaceCanonData,
    PermanentBodyMark,
    RemovableAccessory,
)
from app.services.canon_service import (
    load_accessories,
    load_body_canon,
    load_face_canon,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon

logger = logging.getLogger(__name__)

# ── Hard invariants ───────────────────────────────────────────────────

LOCKED_CANON_CLAUSE = (
    "The character's locked face, body, proportions, scars, tattoos, birthmarks, "
    "and permanent body markings are canon. "
    "Do not redesign, relocate, resize, mirror, reinterpret, remove, or replace them. "
    "Scene, pose, wardrobe, lighting, and environment may change only if they do not "
    "conflict with locked canon."
)

ACCESSORY_RULE = (
    "Only include removable accessories if the user prompt explicitly requests them "
    "or includes one of their trigger keywords. "
    "Do not add accessories that are not requested."
)

SCENE_RULE = "Scene prompt is lower priority than locked character canon."

# Injected into every COVERED block — hard relocation prohibition.
# Explicitly targets reference-image reproduction: even if visual refs show the
# marking, the clothing scene must override them.
MARKING_COVERED_CLAUSE = (
    "These markings are canonical but covered by clothing in this scene. "
    "Do not render them. "
    "Do not move them to visible skin. "
    "Do not relocate them to preserve visibility. "
    "Do not mirror, resize, reinterpret, or replace them. "
    "Even if reference images show these markings, they must remain hidden — "
    "the clothing in this scene covers them entirely."
)

# Always appended when permanent marks are present — anatomical lock.
# Covers both prompt-driven and reference-image-driven relocation.
MARKING_NO_RELOCATION_INVARIANT = (
    "Permanent body markings are locked to exact anatomical regions. "
    "If clothing covers a marking, it must remain hidden — "
    "do not render it on the forearm, wrist, hand, chest, neck, face, back, "
    "or any other visible area, even if reference images show it there."
)

# Appended after MARKING_NO_RELOCATION_INVARIANT — prevents symmetry hallucination
# and bilateral tattoo inference (the model mirroring a left-arm sleeve to the right).
MARKING_SIDE_LOCK_INVARIANT = (
    "Permanent body markings are anatomically side-locked and exclusive to their canonical regions. "
    "A marking on the left arm must not appear on the right arm unless canon explicitly defines a matching marking. "
    "A marking on the right arm must not appear on the left arm unless canon explicitly defines it. "
    "Do not mirror, duplicate, symmetrize, infer matching tattoos, or redistribute markings "
    "for visual balance or composition."
)

_SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

# Raised from 1800 to accommodate relocation + side-lock invariants without truncation.
_PROMPT_CAP = 2400

# ── Marking visibility signals (Fix B) ───────────────────────────────
# Mirror of the equivalent sets in image_generator.py — kept here so
# canon_compiler.py has no dependency on a route file.

_FULL_ARM_EXPOSURE_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso", "sleeveless", "tank top", "vest", "crop top",
    "swimwear", "swimming", "pool", "beach", "paddling",
    "both arms visible", "bare arms", "arms out", "arms visible",
    "paddling pool", "swimming pool", "poolside",
    "ice bath", "cold bath", "sitting in water", "submerged", "upper body visible",
})

_PARTIAL_ARM_EXPOSURE_SIGNALS = frozenset({
    "t-shirt", "tshirt", "tee shirt", "tee-shirt",
    "short sleeve", "short-sleeve", "short sleeved", "short-sleeved",
})

_ROLLED_SLEEVE_SIGNALS = frozenset({
    "rolled sleeve", "rolled sleeves", "rolled-up sleeve", "rolled-up sleeves",
    "rolled up sleeve", "rolled up sleeves", "sleeves rolled", "sleeve rolled",
    "sleeves rolled up", "sleeves pushed up", "pushed-up sleeves",
})

_BUTTON_SHIRT_SIGNALS = frozenset({
    "button shirt", "button-up shirt", "button up shirt", "button-down shirt",
    "button down shirt", "button-up", "button up", "button-down", "button down",
    "dress shirt", "plain shirt", "collared shirt", "oxford shirt",
})

_CLOTHING_COVER_SIGNALS = frozenset({
    "costume", "superhero", "armor", "armour", "uniform",
    "jacket", "coat", "suit", "robe", "hoodie",
    "long sleeve", "long-sleeve", "sweater", "cardigan", "blazer",
})

_SHIRTLESS_SIGNALS = frozenset({
    "shirtless", "bare-chested", "bare chested", "bare chest", "no shirt",
    "topless", "bare torso",
})

# Regions always visible regardless of clothing (face / neck / hands).
_ALWAYS_VISIBLE_REGIONS = frozenset({
    "face", "neck", "throat", "hand", "knuckles",
    "right_cheek", "left_cheek", "forehead", "chin", "jaw",
    "left_hand", "right_hand",
})

# Fix D: body_region value → internal exposure-region key.
# Covers all explicit region semantics required by the spec.
_BODY_REGION_TO_EXPOSURE_REGION: dict[str, str] = {
    # Right arm
    "right_upper_arm": "right_upper_arm",
    "right_lower_arm": "right_forearm",
    "right_forearm": "right_forearm",
    "right_full_arm": "broad_right_arm",
    "right_arm": "broad_right_arm",
    # Left arm
    "left_upper_arm": "left_upper_arm",
    "left_lower_arm": "left_forearm",
    "left_forearm": "left_forearm",
    "left_full_arm": "broad_left_arm",
    "left_arm": "broad_left_arm",
    # Torso
    "chest": "chest",
    "abdomen": "chest",
    "ribs": "chest",
    "side": "chest",
    # Back
    "upper_back": "back",
    "lower_back": "back",
    "full_back": "back",
    "back": "back",
    # Neck / face
    "neck": "neck",
    "throat": "neck",
    "right_cheek": "face",
    "left_cheek": "face",
    "forehead": "face",
    "chin": "face",
    "jaw": "face",
    "face": "face",
    # Hands
    "left_hand": "hand",
    "right_hand": "hand",
    "hand": "hand",
    "knuckles": "hand",
    # Legs
    "left_thigh": "left_leg",
    "right_thigh": "right_leg",
    "left_calf": "left_leg",
    "right_calf": "right_leg",
}

# ── Side-lock lookup tables ───────────────────────────────────────────
# For each arm body_region, the opposite-side areas to negate in the
# side-lock clause ("There is no X on the right forearm, right wrist…").
_OPPOSITE_ARM_REGIONS: dict[str, str] = {
    "left_full_arm":   "the right forearm, right wrist, right lower arm, or right upper arm",
    "left_arm":        "the right arm, right forearm, right wrist, or right upper arm",
    "left_upper_arm":  "the right upper arm, right shoulder, or right bicep",
    "left_lower_arm":  "the right lower arm, right wrist, or right forearm",
    "left_forearm":    "the right forearm, right wrist, or right lower arm",
    "right_full_arm":  "the left forearm, left wrist, left lower arm, or left upper arm",
    "right_arm":       "the left arm, left forearm, left wrist, or left upper arm",
    "right_upper_arm": "the left upper arm, left shoulder, or left bicep",
    "right_lower_arm": "the left lower arm, left wrist, or left forearm",
    "right_forearm":   "the left forearm, left wrist, or left lower arm",
}

# Human-readable canonical region for existence clauses
# ("X exists only on the right upper bicep/deltoid region and nowhere else").
_REGION_EXCLUSIVE_DESC: dict[str, str] = {
    "right_upper_arm":  "right upper bicep/deltoid region",
    "left_upper_arm":   "left upper bicep/deltoid region",
    "right_forearm":    "right forearm",
    "left_forearm":     "left forearm",
    "right_lower_arm":  "right lower arm",
    "left_lower_arm":   "left lower arm",
    "right_full_arm":   "right arm, shoulder to wrist",
    "left_full_arm":    "left arm, shoulder to wrist",
    "right_arm":        "right arm",
    "left_arm":         "left arm",
}

_ARM_LOCK_REGIONS = frozenset(_OPPOSITE_ARM_REGIONS.keys())


# ── Marking visibility classification (Fix B) ─────────────────────────

def _classify_canon_region_exposure(region: str, prompt_lower: str) -> str:
    """Return 'exposed', 'covered', or 'unknown' for a body region in this scene.

    Garment rules (same semantics as image_generator.py):
      full arm bare (sleeveless/shirtless) → upper arm + forearm exposed
      t-shirt / short sleeve               → forearm exposed, upper arm covered
      rolled sleeves                       → forearm exposed, upper arm covered
      button / dress / plain shirt         → upper arm + forearm covered
      long sleeve / jacket / hoodie        → all arm skin covered
      no garment signal                    → unknown (caller treats as covered)
    """
    full_arm = any(s in prompt_lower for s in _FULL_ARM_EXPOSURE_SIGNALS)
    short_sleeve = any(s in prompt_lower for s in _PARTIAL_ARM_EXPOSURE_SIGNALS)
    rolled = any(s in prompt_lower for s in _ROLLED_SLEEVE_SIGNALS)
    button_shirt = any(s in prompt_lower for s in _BUTTON_SHIRT_SIGNALS)
    covering = any(s in prompt_lower for s in _CLOTHING_COVER_SIGNALS)
    shirtless = any(s in prompt_lower for s in _SHIRTLESS_SIGNALS)
    covered_garment = button_shirt or covering

    if region in ("face", "neck", "hand"):
        return "exposed"

    if region in ("right_upper_arm", "left_upper_arm"):
        if full_arm:
            return "exposed"
        if short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    if region in ("right_forearm", "left_forearm"):
        if full_arm or short_sleeve or rolled:
            return "exposed"
        if covered_garment:
            return "covered"
        return "unknown"

    if region in ("broad_right_arm", "broad_left_arm"):
        if full_arm:
            return "exposed"
        if short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    if region == "chest":
        if shirtless:
            return "exposed"
        if full_arm or short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    if region == "back":
        if shirtless or "backless" in prompt_lower or "bare back" in prompt_lower:
            return "exposed"
        if full_arm or short_sleeve or rolled or covered_garment:
            return "covered"
        return "unknown"

    return "unknown"


def _classify_canon_mark_exposure(mark: PermanentBodyMark, prompt_lower: str) -> str:
    """Return 'exposed' or 'covered' for a PermanentBodyMark in this scene.

    Safe fallback: unknown → covered. Marks are hidden unless the scene
    unambiguously exposes their skin. This prevents the model from inventing
    tattoo placement on nearby visible skin.
    """
    region_key = mark.body_region.lower().replace(" ", "_")

    if region_key in _ALWAYS_VISIBLE_REGIONS:
        return "exposed"

    exposure_region = _BODY_REGION_TO_EXPOSURE_REGION.get(region_key, "other")
    exposure = _classify_canon_region_exposure(exposure_region, prompt_lower)

    # Sleeve exception: a full-arm sleeve spans shoulder to wrist. If the broad
    # arm is not fully bare but the forearm is exposed (rolled sleeves, t-shirt),
    # the forearm portion of the sleeve is visible.
    if exposure != "exposed" and exposure_region in ("broad_left_arm", "broad_right_arm"):
        if "sleeve" in (mark.description or "").lower():
            side = "left" if "left" in region_key else "right"
            if _classify_canon_region_exposure(f"{side}_forearm", prompt_lower) == "exposed":
                exposure = "exposed"

    return "exposed" if exposure == "exposed" else "covered"


def _make_mark_token(mark: PermanentBodyMark) -> str:
    """Format a PermanentBodyMark as a compact prompt token."""
    side_str = mark.side if mark.side in ("centre", "bilateral") else f"{mark.side} side"
    readable_region = mark.body_region.replace("_", " ")
    return f"{mark.type} on {readable_region} ({side_str}): {mark.description}"


def _side_lock_label(mark: PermanentBodyMark) -> str:
    """Return a concise display name for side-lock clause text.

    Strips leading side/location qualifiers from the label so the clause
    reads naturally: "Left Arm Gothic Script Sleeve" → "gothic script sleeve".
    """
    label = mark.label or ""
    for prefix in (
        "Left Full Arm ", "Right Full Arm ",
        "Left Arm ", "Right Arm ",
        "Left Upper Arm ", "Right Upper Arm ",
        "Left ", "Right ",
    ):
        if label.lower().startswith(prefix.lower()):
            label = label[len(prefix):]
            break
    return label.lower() or "marking"


def _build_side_lock_clauses(
    visible_marks: list[PermanentBodyMark],
    hidden_marks: list[PermanentBodyMark],
) -> str:
    """Build per-mark negative side-lock clauses for arm markings.

    For visible arm marks: "There is no [mark] on [opposite side areas]."
    For covered arm marks: "[Mark] exists only on [canonical region] and nowhere else."

    Non-arm marks (chest, neck, face, etc.) are skipped — they have no
    mirroring failure mode.
    """
    clauses: list[str] = []

    for m in visible_marks:
        region = m.body_region.lower().replace(" ", "_")
        if region in _ARM_LOCK_REGIONS:
            opposite = _OPPOSITE_ARM_REGIONS[region]
            name = _side_lock_label(m)
            clauses.append(f"There is no {name} on {opposite}.")

    for m in hidden_marks:
        region = m.body_region.lower().replace(" ", "_")
        if region in _ARM_LOCK_REGIONS:
            exclusive = _REGION_EXCLUSIVE_DESC.get(region, region.replace("_", " "))
            name = _side_lock_label(m)
            clauses.append(
                f"The {name} exists only on the {exclusive} and nowhere else."
            )

    return " ".join(clauses)


# ── Reference image collector ─────────────────────────────────────────

def collect_canon_reference_urls(
    canon: "CharacterIdentityCanon",
) -> list[str]:
    """Collect reference image URLs in provider-priority order.

    Priority (positions 0–5 are always sent under the 6-image provider cap):
      0. face_front            — primary face identity seed
      1. face_left_3q          — face geometry supplement
      2. face_right_3q         — face geometry supplement
      3. body_front            — body morphology + tattoo placement truth
      4. body_map              — canonical marking placement sheet
      5. final_character_card  — holistic identity grounding

    May drop under provider cap (positions 6–9):
      6. body_left             — side detail (optional)
      7. body_right            — side detail (optional)
      8. body_back             — back detail (optional)
      9. face_expression       — lowest-value face variant; always last

    Rationale: face_expression is a 4th face angle with marginal identity
    value. body_map and final_character_card carry canonical marking truth
    and must always reach the provider. Optional side/back refs may drop.
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)

    def _f(obj: object, attr: str) -> str | None:
        return getattr(obj, attr, None) if obj else None

    # Build in strict priority order — each entry is (url_or_None,).
    # Skip None entries so sparse canons produce a compact list.
    ordered = [
        _f(face, "face_front_image_url"),           # 0 — always first
        _f(face, "face_left_3q_image_url"),          # 1
        _f(face, "face_right_3q_image_url"),         # 2
        _f(body, "body_front_image_url"),            # 3 — body truth
        _f(body, "body_map_image_url"),              # 4 — marking placement
        _f(body, "final_character_card_image_url"),  # 5 — holistic grounding
        _f(body, "body_left_image_url"),             # 6 — may drop
        _f(body, "body_right_image_url"),            # 7 — may drop
        _f(body, "body_back_image_url"),             # 8 — may drop
        _f(face, "face_expression_image_url"),       # 9 — always last
    ]
    return [url for url in ordered if url]


# ── Main compiler ─────────────────────────────────────────────────────

def compile_canon_prompt(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    *,
    include_accessories: bool = True,
) -> str:
    """Compile a scene prompt from the character's locked canon.

    Section order:
      1. Safety prefix
      2. FACE CANON
      3. BODY CANON (anatomy)
      4. PERMANENT BODY MARKS VISIBLE — exposed marks only
         COVERED PERMANENT BODY MARKS — hidden marks + relocation prohibition
         MARKING_NO_RELOCATION_INVARIANT — always present when marks exist
      5. REMOVABLE ACCESSORIES (trigger-keyword matched)
      6. USER SCENE PROMPT
      7. LOCKED CANON CLAUSE

    Marks are classified as visible or covered using the scene prompt.
    Safe fallback: ambiguous exposure → covered. This prevents the model
    from relocating a covered marking to nearby visible skin.
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    accessories = load_accessories(canon) if include_accessories else []
    has_locked = (face and face.locked) or (body and body.locked)

    parts: list[str] = [_SAFETY_PREFIX]

    # ── 1. FACE CANON ─────────────────────────────────────────────
    if face and face.face_description:
        parts.append(f"FACE CANON: {face.face_description}")

    # ── 2. BODY CANON (anatomy) ───────────────────────────────────
    if body:
        body_parts: list[str] = []
        if body.body_description:
            body_parts.append(body.body_description)
        morphology: list[str] = []
        if body.height:
            morphology.append(body.height)
        if body.build:
            morphology.append(f"{body.build} build")
        if body.proportions:
            morphology.append(body.proportions)
        if body.skin_tone:
            morphology.append(f"{body.skin_tone} skin")
        if morphology:
            body_parts.append(", ".join(morphology))
        if body_parts:
            parts.append("BODY CANON: " + ". ".join(body_parts))

    # ── 3. PERMANENT BODY MARKS (visibility-gated) ────────────────
    if body and body.permanent_body_marks:
        prompt_lower = scene_prompt.lower()
        visible_marks: list[PermanentBodyMark] = []
        hidden_marks: list[PermanentBodyMark] = []
        for m in body.permanent_body_marks:
            if _classify_canon_mark_exposure(m, prompt_lower) == "exposed":
                visible_marks.append(m)
            else:
                hidden_marks.append(m)

        if visible_marks:
            tokens = "; ".join(_make_mark_token(m) for m in visible_marks)
            parts.append(f"PERMANENT BODY MARKS VISIBLE: {tokens}")

        if hidden_marks:
            tokens = "; ".join(_make_mark_token(m) for m in hidden_marks)
            parts.append(
                f"COVERED PERMANENT BODY MARKS: {tokens}. {MARKING_COVERED_CLAUSE}"
            )

        # Fix C: always append the anatomical no-relocation invariant.
        parts.append(MARKING_NO_RELOCATION_INVARIANT)

        # Fix P9: side-lock invariant prevents bilateral / symmetry hallucination.
        parts.append(MARKING_SIDE_LOCK_INVARIANT)
        side_lock_clauses = _build_side_lock_clauses(visible_marks, hidden_marks)
        if side_lock_clauses:
            parts.append(side_lock_clauses)

    # ── 4. REMOVABLE ACCESSORIES ──────────────────────────────────
    if accessories and include_accessories:
        scene_lower = scene_prompt.lower()
        requested: list[RemovableAccessory] = []
        for acc in accessories:
            for kw in (acc.trigger_keywords or []):
                if kw.lower() in scene_lower:
                    requested.append(acc)
                    break
        if requested:
            acc_tokens = [acc.description for acc in requested]
            parts.append("ACCESSORIES (requested): " + "; ".join(acc_tokens))
        else:
            parts.append(ACCESSORY_RULE)

    # ── 5. USER SCENE PROMPT ──────────────────────────────────────
    parts.append(scene_prompt.strip())

    # ── 6. LOCKED CANON CLAUSE ────────────────────────────────────
    if has_locked:
        parts.append(LOCKED_CANON_CLAUSE)

    prompt = ", ".join(p for p in parts if p)

    if len(prompt) > _PROMPT_CAP:
        prompt = prompt[:_PROMPT_CAP]
        logger.warning(
            "canon_prompt_truncated character_id=%s len=%d",
            canon.character_id, _PROMPT_CAP,
        )

    logger.info(
        "CANON_PROMPT character_id=%s face_locked=%s body_locked=%s "
        "marks=%d accs=%d prompt_len=%d",
        canon.character_id,
        face.locked if face else False,
        body.locked if body else False,
        len(body.permanent_body_marks) if body else 0,
        len(accessories),
        len(prompt),
    )

    return prompt


def has_any_canon_content(canon: "CharacterIdentityCanon") -> bool:
    """Return True if the canon record has any face or body content."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    if face and any([
        face.face_front_image_url, face.face_description,
    ]):
        return True
    if body and any([
        body.body_front_image_url, body.body_description,
        body.permanent_body_marks,
    ]):
        return True
    return False
