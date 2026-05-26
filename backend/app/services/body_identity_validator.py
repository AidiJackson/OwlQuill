"""Body Identity Pack validation scaffold.

validate_body_identity_pack(...) is the future entry point for visual consistency
checks on generated body identity images.

Phase 1: stub only — returns structural validation based on slot state.
Phase 2 (future): integrate vision AI to verify per-image constraints.

FUTURE CHECKS (not yet implemented — require vision AI pass):
  - tattoo_moved_arms:      tattoo detected on wrong limb vs. canon placement
  - tattoo_on_clothing:     tattoo rendered on fabric instead of skin
  - merged_tattoos:         left + right arm tattoos merged into a single design
  - missing_markings:       a documented marking is absent from the image
  - mirrored_limbs:         left/right flipped vs. canon (mirror-image error)
  - body_mismatch:          body proportions/type differ from face-pack body shape
  - placement_drift:        marking position shifted vs. body_front reference
  - style_drift:            marking design style changed vs. body_front reference
"""
import logging
from dataclasses import dataclass, field

from app.models.character import Character as CharacterModel
from app.services.body_canon import load_markings
from app.services.body_identity_refs import get_body_identity_references

logger = logging.getLogger(__name__)


@dataclass
class BodyIdentityValidationResult:
    """Result of validate_body_identity_pack().

    valid:    True when no failures; warnings are non-blocking.
    warnings: Non-blocking issues — generation will proceed but may drift.
    failures: Blocking issues — generation should be blocked or warned clearly.
    """
    valid: bool = True
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


def validate_body_identity_pack(
    character: CharacterModel,
    *,
    require_complete_pack: bool = False,
) -> BodyIdentityValidationResult:
    """Validate a character's body identity pack.

    Phase 1 (structural only):
    - Checks whether body_front is locked when markings exist.
    - Warns when detail slots are missing for a character with markings.
    - Flags final_character_card used without body_front (support-only misuse).

    Phase 2 (vision AI — future):
    - Per-image checks enumerated in module docstring.

    Args:
        character:              Character to validate.
        require_complete_pack:  If True, missing body_front with markings is a
                                failure rather than a warning.

    Returns:
        BodyIdentityValidationResult with valid, warnings, failures.
    """
    result = BodyIdentityValidationResult()
    markings = load_markings(character)
    body_refs = get_body_identity_references(character)

    # ── Structural checks ──────────────────────────────────────────────

    if markings and not body_refs.body_identity_complete:
        msg = (
            f"body_front not locked for character with {len(markings)} marking(s). "
            "Tattoo and body marking placement will rely on text description only — "
            "expect visual drift."
        )
        if require_complete_pack:
            result.failures.append(msg)
            result.valid = False
        else:
            result.warnings.append(msg)

    if markings and body_refs.body_identity_complete:
        # body_front present — check for useful detail slots
        ref_slots = {r.slot for r in body_refs.refs}
        if "body_left_detail" not in ref_slots and "body_right_detail" not in ref_slots:
            result.warnings.append(
                "Neither body_left_detail nor body_right_detail is locked. "
                "Left/right arm marking fidelity may be reduced."
            )
        if "body_map" not in ref_slots and "tattoo_layout" not in ref_slots:
            result.warnings.append(
                "body_map (or legacy tattoo_layout) not locked. "
                "Spatial placement relationships between markings rely on body_front only."
            )

    # final_character_card without body_front is a misuse warning
    has_final_card = any(r.slot == "final_character_card" for r in body_refs.refs)
    if has_final_card and not body_refs.body_identity_complete and markings:
        result.warnings.append(
            "final_character_card is locked but body_front is not. "
            "final_character_card is SUPPORT ONLY and cannot substitute for body_front."
        )

    # ── Future vision checks (stub) ────────────────────────────────────
    # The following checks are documented but not yet implemented.
    # Each requires a vision model pass against the generated images.
    #
    # TODO: tattoo_moved_arms   — verify each marking is on the correct limb
    # TODO: tattoo_on_clothing  — verify markings appear on skin, not fabric
    # TODO: merged_tattoos      — verify left/right arm markings are distinct
    # TODO: missing_markings    — verify all canon markings appear in body_front
    # TODO: mirrored_limbs      — verify image is not a mirror flip of canon
    # TODO: body_mismatch       — verify body proportions match face-pack body
    # TODO: placement_drift     — verify marking positions match body_front
    # TODO: style_drift         — verify marking designs match body_front

    logger.info(
        "BODY_IDENTITY_VALIDATION character_id=%s valid=%s "
        "warnings=%d failures=%d markings=%d body_complete=%s",
        getattr(character, "id", "?"),
        result.valid,
        len(result.warnings),
        len(result.failures),
        len(markings),
        body_refs.body_identity_complete,
    )

    return result
