"""Canon prompt compiler — Identity OS minimal prompt.

P12 architecture:

    USER PROMPT → Scene Router → Canon Card Selection → Provider

Identity truth (facial identity, anatomy, proportions, visible body truth,
and tattoo placement) is carried by the canon **reference cards** selected by
the scene router — NOT by prose. The provider infers identity from those
cards. This compiler therefore keeps the user's scene prompt essentially
unchanged, adding only:

  * a minimal safety directive, and
  * any removable accessory the user explicitly requested via trigger keyword.

There are intentionally NO canon paragraphs, tattoo-visibility essays,
relocation / side-lock invariants, or covered/hidden marking blocks. Those
prose systems were removed in P12 (rollback tag: pre-p12-canon-routing-simplification)
because they conflicted with, and provided no leverage over, the card truth.

The old identity_compiler.py remains for legacy characters without a canon record.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.canon_service import (
    load_accessories,
    load_body_canon,
    load_face_canon,
)

if TYPE_CHECKING:
    from app.models.character_identity_canon import CharacterIdentityCanon
    from app.schemas.canon import RemovableAccessory

logger = logging.getLogger(__name__)

# ── Minimal safety directive ──────────────────────────────────────────
# The only standing prose the compiler prepends. Kept short and content-policy
# only — it carries no identity engineering.
_SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

# Provider prompt cap. Prompts are now small (safety + accessories + scene), so
# this almost never triggers; retained purely as a defensive truncation guard.
_PROMPT_CAP = 2400

# ── Identity-priority directive (name-neutralisation) ─────────────────
# Added only when the canon has image references. Tells the provider that
# identity comes from the reference cards, not from any personal name the
# user typed in the scene (which otherwise drifts toward a real-person/celebrity
# likeness — e.g. "Leonardo" resembling a famous actor).
_IDENTITY_PRIORITY = (
    "Depict the exact character shown in the reference images. "
    "Treat any personal name in the scene as a label only — do not infer the "
    "face from the name and do not resemble any real person or celebrity."
)

# ── Permanence + skin-binding directive (C + P13b) ────────────────────
# One compact directive appended to the marking clause. Not the pre-P12 essay.
# Targets the "floating symbol" failure mode: an isolated tattoo crop being
# rendered as a free-standing graphic/accessory beside the body instead of a
# skin-bound marking applied to the correct anatomy.
_MARKING_HEADER = "Permanent markings are immutable skin-bound anatomy:"

_PERMANENCE_DIRECTIVE = (
    "Do not redesign, relocate, mirror, enlarge, detach, float, duplicate, or "
    "reinterpret markings as symbols, graphics, accessories, or background elements. "
    "Permanent tattoos/scars must remain attached to the correct body region and side. "
    "Reproduce each marking's exact shape, line work, and scale from the reference "
    "images — this specific design, not a stylistic or tribal reinterpretation."
)

# Clothing truth outranks tattoo visibility. The model must never restyle a
# garment to expose a covered marking; a tattoo is only visible when the
# requested clothing naturally leaves that skin region uncovered.
_CLOTHING_TRUTH_DIRECTIVE = (
    "Permanent markings obey scene clothing. Do not alter, cut, remove, roll "
    "higher, tear, or reinterpret garments to reveal covered tattoos/scars. "
    "Hidden markings remain hidden."
)


def _skin_phrase(mark: object) -> str:
    """Type-aware skin-binding suffix that frames the mark as inked-in anatomy."""
    t = (getattr(mark, "type", "") or "").lower()
    if t == "scar":
        return "permanently set into the skin"
    if t in ("tattoo", "body_marking", ""):
        return "permanently inked into skin"
    return "permanently part of the skin"


# ── Reference image collector ─────────────────────────────────────────
# Unchanged from P8: the canonical static priority ordering. The scene router
# (scene_router.py) selects/weights cards for routed scenes and falls back to
# this ordering when the prompt is ambiguous.

def collect_canon_reference_urls(
    canon: "CharacterIdentityCanon",
) -> list[str]:
    """Collect reference image URLs in provider-priority order.

    S24AK note: this is the ambiguous-prompt FALLBACK ordering (the scene
    router weights cards per-camera when an orientation is detectable). The v2
    cards are woven in by priority — NOT blindly appended — so the strongest
    six still win under the 6-image provider cap. A fully-populated v2 canon
    sends face_front, face_left_3q, face_right_3q, face_profile, body_front,
    body_map (4 face angles + body truth + marking placement).

    Priority (positions 0–5 are the ones most likely sent under the 6-cap):
      0. face_front            — primary face identity seed
      1. face_left_3q          — face geometry supplement
      2. face_right_3q         — face geometry supplement
      3. face_profile          — v2: side-profile face geometry
      4. body_front            — body morphology + tattoo placement truth
      5. body_map              — canonical marking placement sheet

    May drop under provider cap (positions 6+):
      6.  final_character_card — holistic identity grounding
      7.  body_left            — side detail (optional)
      8.  body_right           — side detail (optional)
      9.  body_back            — back detail (optional)
      10. face_expression      — lowest-value face variant
      11. torso_front          — v2: upper-body truth (optional)
      12. torso_side           — v2: upper-body side truth (optional)
      13. standing_relaxed     — v2: relaxed full-body pose (optional)
      14. seated_relaxed       — v2: relaxed seated pose (optional)

    Rationale: face angles + body truth + marking placement carry the most
    identity signal and lead. The v2 relaxed/torso cards are supporting body
    truth and sit behind the legacy core so they only surface when room remains
    or higher-priority slots are absent (sparse canons stay compact).
    """
    face = load_face_canon(canon)
    body = load_body_canon(canon)

    def _f(obj: object, attr: str) -> str | None:
        return getattr(obj, attr, None) if obj else None

    # Build in strict priority order — each entry is (url_or_None,).
    # Skip None entries so sparse canons produce a compact list.
    ordered = [
        _f(face, "face_front_image_url"),            # 0 — always first
        _f(face, "face_left_3q_image_url"),          # 1
        _f(face, "face_right_3q_image_url"),         # 2
        _f(face, "face_profile_image_url"),          # 3 — v2 profile face
        _f(body, "body_front_image_url"),            # 4 — body truth
        _f(body, "body_map_image_url"),              # 5 — marking placement
        _f(body, "final_character_card_image_url"),  # 6 — holistic grounding
        _f(body, "body_left_image_url"),             # 7 — may drop
        _f(body, "body_right_image_url"),            # 8 — may drop
        _f(body, "body_back_image_url"),             # 9 — may drop
        _f(face, "face_expression_image_url"),       # 10 — low-value face variant
        _f(body, "torso_front_image_url"),           # 11 — v2 torso truth
        _f(body, "torso_side_image_url"),            # 12 — v2 torso side
        _f(body, "standing_relaxed_image_url"),      # 13 — v2 relaxed pose
        _f(body, "seated_relaxed_image_url"),        # 14 — v2 seated pose
    ]
    return [url for url in ordered if url]


# ── Requested removable accessories ───────────────────────────────────

def _requested_accessories(
    canon: "CharacterIdentityCanon",
    scene_lower: str,
) -> list["RemovableAccessory"]:
    """Return removable accessories whose trigger keyword appears in the scene.

    Deterministic substring match only. Accessories are never inferred — they
    appear solely when the user's prompt explicitly asks for them.
    """
    requested: list["RemovableAccessory"] = []
    for acc in load_accessories(canon):
        for kw in (acc.trigger_keywords or []):
            if kw.lower() in scene_lower:
                requested.append(acc)
                break
    return requested


# ── Permanent marking clause (A) ──────────────────────────────────────

def _region_phrase(region: str) -> str:
    """Turn a body_region key into a short human phrase.

    'left_full_arm' → 'left arm'; 'right_upper_arm' → 'right upper arm';
    'neck' → 'neck'; 'right_cheek' → 'right cheek'.
    """
    r = (region or "").lower().strip()
    if r.endswith("_full_arm"):
        return r[: -len("_full_arm")].replace("_", " ") + " arm"
    return r.replace("_", " ")


def _has_image_refs(canon: "CharacterIdentityCanon") -> bool:
    """True if the canon carries any face or body image reference."""
    face = load_face_canon(canon)
    body = load_body_canon(canon)
    if face and any([
        face.face_front_image_url,
        face.face_left_3q_image_url,
        face.face_right_3q_image_url,
    ]):
        return True
    if body and any([
        body.body_front_image_url,
        body.body_map_image_url,
        body.final_character_card_image_url,
    ]):
        return True
    return False


def _permanent_marks_clause(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
) -> str:
    """Compile a scene-aware permanent-marking clause (A + C).

    Clothing truth > tattoo visibility. The text is aligned with the routing
    layer's already-correct visibility decisions so the prompt never instructs
    the provider to reproduce a tattoo the scene covers (which previously made
    garments split/cut open to expose hidden marks).

    Visibility is decided by the SAME logic the scene router uses for crop
    routing — `_detect_camera`, `_is_sleeve_mark`, `_mark_region_exposed` — so
    text and references can never drift apart (single source of truth).

    Emission rules:
      * portrait / close-up        → no marking block at all (face-only frame).
      * exposed marks (this scene) → skin-bound header + per-mark geometry lines
                                      + permanence/exact-geometry directive.
      * covered marks present      → ONLY the compact clothing-truth directive;
                                      covered marks are never named, never given
                                      a permanence/geometry reproduction clause.
      * no exposed marks           → permanence/geometry section suppressed
                                      entirely (just the clothing-truth line).

    Returns '' when there are no permanent marks, or for portraits.
    """
    body = load_body_canon(canon)
    marks = getattr(body, "permanent_body_marks", None) if body else None
    if not marks:
        return ""

    # Single source of truth: reuse the router's deterministic scene logic.
    from app.services.scene_router import (
        _detect_camera,
        _is_sleeve_mark,
        _mark_region_exposed,
    )

    prompt_lower = (scene_prompt or "").lower()

    # Portrait / close-up frames carry no body region — emit no marking block
    # (matches the router skipping all body-crop routing for portraits).
    if _detect_camera(prompt_lower) == "portrait_closeup":
        return ""

    # Partition marks by THIS scene's exposure, using the identical per-mark gate
    # the router applies to crop routing. Covered/uncertain regions → not exposed.
    exposed: list = []
    for m in marks:
        if _mark_region_exposed(
            getattr(m, "body_region", ""), _is_sleeve_mark(m), prompt_lower
        ):
            exposed.append(m)

    parts: list[str] = []

    # Exposed marks only: skin-bound wording + permanence + exact-geometry clause.
    if exposed:
        lines: list[str] = []
        for m in exposed:
            region = _region_phrase(getattr(m, "body_region", ""))
            design = (getattr(m, "description", None) or getattr(m, "label", None)
                      or "permanent marking").strip()
            lines.append(f"- {region}: {design} {_skin_phrase(m)}")
        parts.append(
            _MARKING_HEADER + "\n"
            + "\n".join(lines)
            + "\n" + _PERMANENCE_DIRECTIVE
        )

    # Clothing truth always asserted when the character has marks in a body
    # scene — this is what keeps covered marks hidden instead of forcing them.
    parts.append(_CLOTHING_TRUTH_DIRECTIVE)

    return "\n".join(parts)


# ── Main compiler ─────────────────────────────────────────────────────

def compile_canon_prompt(
    canon: "CharacterIdentityCanon",
    scene_prompt: str,
    *,
    include_accessories: bool = True,
) -> str:
    """Compile a minimal generation prompt from the user's scene.

    Output order:
      1. minimal safety directive
      2. requested removable accessories (keyword-triggered only)
      3. the user's scene prompt, essentially unchanged

    Identity is supplied by the routed canon reference cards, not by this
    prompt. No canon prose, marking essays, or relocation/side-lock invariants
    are emitted.
    """
    scene = scene_prompt.strip()
    parts: list[str] = [_SAFETY_PREFIX]

    # Identity-priority directive — only when image refs back it (name fix).
    if _has_image_refs(canon):
        parts.append(_IDENTITY_PRIORITY)

    requested: list["RemovableAccessory"] = []
    if include_accessories:
        requested = _requested_accessories(canon, scene.lower())
        if requested:
            parts.append("wearing " + "; ".join(a.description for a in requested))

    # Scene-aware permanent-marking clause (A + C) — exposed marks get the
    # skin-bound/geometry block; covered marks get only the clothing-truth line.
    marks_clause = _permanent_marks_clause(canon, scene)
    if marks_clause:
        parts.append(marks_clause)

    parts.append(scene)

    prompt = ", ".join(p for p in parts if p)

    if len(prompt) > _PROMPT_CAP:
        prompt = prompt[:_PROMPT_CAP]
        logger.warning(
            "canon_prompt_truncated character_id=%s len=%d",
            canon.character_id, _PROMPT_CAP,
        )

    logger.info(
        "CANON_PROMPT character_id=%s accessories=%d marks_clause=%s prompt_len=%d",
        canon.character_id, len(requested), bool(marks_clause), len(prompt),
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
