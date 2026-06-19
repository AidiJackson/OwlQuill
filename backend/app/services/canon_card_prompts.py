"""V2 canon card prompt templates (S24AL).

Data-only module: prompt strings + the card generation pipeline definition.
NO provider, DB, or storage imports — this is pure text/metadata so it can be
imported anywhere (including dry-run planning) with zero side effects.

Design (S24AL §1 / §3): one identity seed (face_front) is generated first; every
other card is grounded on already-approved cards so the face/body stay
consistent. Truth is carried by the grounding reference images, so each prompt
adds only the identity preamble + a camera/pose clause + a short anti-drift
clause (mirrors the minimal-prose philosophy of canon_compiler).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ── Standing clauses ──────────────────────────────────────────────────
# Content-policy only; carries no identity engineering (matches
# canon_compiler._SAFETY_PREFIX).
SAFETY_PREFIX = "adult, fully clothed, non-explicit, tasteful"

# Neutral studio framing shared by every CANON card (not validation scenes).
STUDIO_FRAMING = "neutral studio backdrop, even soft lighting, sharp focus"

# Anti-drift clause — keeps anatomy/marks from being reinterpreted across the
# pack (mirrors CharacterCanonState.LOCKED_CANON_CLAUSE intent).
ANTI_DRIFT = (
    "Keep the same person across every image: identical face, body, "
    "proportions, and permanent markings. Do not redesign, relocate, mirror, "
    "resize, or remove any feature."
)


# ── Identity input (description-agnostic container) ───────────────────

@dataclass
class MarkSpec:
    """One permanent marking to add to the founder's body canon.

    Mirrors the fields of schemas.canon.AddPermanentMarkRequest so the harness
    can construct the request 1:1 without guessing.
    """
    label: str
    type: str          # tattoo | scar | birthmark | mole | body_marking | other
    body_region: str   # e.g. "left_full_arm"
    side: str          # left | right | centre | bilateral
    description: str   # full visual description (also the mark-detail prompt body)


@dataclass
class FounderIdentity:
    """All identity inputs for one founder character.

    Every field is supplied by the user (S24AL: "use the provided identity
    descriptions exactly"). This module never invents values — empty fields
    simply produce a thinner preamble.
    """
    name: str
    # Face
    gender: str = ""
    age_band: str = ""
    skin_tone: str = ""
    hair: str = ""            # free text: colour / length / texture
    eye_color: str = ""
    face_features: str = ""   # distinctive features, free text
    face_description: str = ""  # optional full override for the face line
    # Body
    height: str = ""
    build: str = ""
    proportions: str = ""
    body_description: str = ""  # optional full override for the body line
    # Marks
    marks: list[MarkSpec] = field(default_factory=list)
    # Validation scenes (S24AL task 5)
    casual_scene: str = ""
    cinematic_scene: str = ""
    environment_scene: str = ""

    def is_complete(self) -> bool:
        """True when enough identity text exists to build a usable seed prompt.

        The harness refuses to generate without this so we never ship a founder
        built from a blank/fabricated description.
        """
        has_face = bool(self.face_description or self.hair or self.face_features)
        has_body = bool(self.body_description or self.build or self.height)
        return bool(self.name) and has_face and has_body


# ── Card pipeline definition (S24AL §1) ───────────────────────────────

@dataclass(frozen=True)
class CardSpec:
    """One card in the generation pipeline."""
    slot: str            # must be a key in schemas.canon.SLOT_FIELD_MAP
    phase: str           # seed | face | body_seed | body | pose
    clause: str          # camera/pose clause appended to the preamble
    grounds_on: tuple[str, ...]  # slots whose images anchor this generation
    is_gate: bool = False        # gate cards must pass before dependents run


# Generation order matters: gate cards (face_front, body_front) come before
# anything that grounds on them.
CARD_PIPELINE: tuple[CardSpec, ...] = (
    CardSpec("face_front", "seed",
             "tight head-and-shoulders portrait, facing camera directly, neutral expression",
             (), is_gate=True),
    CardSpec("face_left_3q", "face",
             "head-and-shoulders, three-quarter view turned to their left",
             ("face_front",)),
    CardSpec("face_right_3q", "face",
             "head-and-shoulders, three-quarter view turned to their right",
             ("face_front",)),
    CardSpec("face_profile", "face",
             "head-and-shoulders, full side profile, ninety degrees to camera",
             ("face_front",)),
    CardSpec("face_expression", "face",
             "head-and-shoulders, natural relaxed smile",
             ("face_front",)),
    CardSpec("body_front", "body_seed",
             "full-body, standing straight, facing camera, arms at sides, full outfit visible",
             ("face_front",), is_gate=True),
    CardSpec("body_left", "body",
             "full-body, left-side view",
             ("face_front", "body_front")),
    CardSpec("body_right", "body",
             "full-body, right-side view",
             ("face_front", "body_front")),
    CardSpec("body_back", "body",
             "full-body, back to camera, full back visible",
             ("face_front", "body_front")),
    CardSpec("torso_front", "pose",
             "waist-up framing, front, chest and shoulders clearly visible",
             ("face_front", "body_front")),
    CardSpec("torso_side", "pose",
             "waist-up framing, side view",
             ("face_front", "body_front")),
    CardSpec("standing_relaxed", "pose",
             "full-body, relaxed natural standing posture, weight on one leg",
             ("face_front", "body_front")),
    CardSpec("seated_relaxed", "pose",
             "full-body, seated relaxed on a plain stool",
             ("face_front", "body_front")),
)

# Cards whose approval unlocks dependents (S24AL §5).
GATE_SLOTS: frozenset[str] = frozenset(c.slot for c in CARD_PIPELINE if c.is_gate)

# Quick lookup.
CARD_BY_SLOT: dict[str, CardSpec] = {c.slot: c for c in CARD_PIPELINE}


# ── Prompt builders ───────────────────────────────────────────────────

def build_preamble(identity: FounderIdentity) -> str:
    """Compose the shared identity preamble used by every card prompt."""
    # Face line — prefer an explicit override, else assemble from fields.
    if identity.face_description:
        face_line = identity.face_description.strip().rstrip(".")
    else:
        face_bits = [
            b for b in (
                identity.skin_tone,
                f"{identity.hair} hair" if identity.hair else "",
                f"{identity.eye_color} eyes" if identity.eye_color else "",
                identity.face_features,
            ) if b
        ]
        face_line = ", ".join(face_bits)

    # Body line.
    if identity.body_description:
        body_line = identity.body_description.strip().rstrip(".")
    else:
        body_bits = [
            b for b in (
                identity.height,
                f"{identity.build} build" if identity.build else "",
                identity.proportions,
            ) if b
        ]
        body_line = ", ".join(body_bits)

    descriptor = " ".join(b for b in (identity.age_band, identity.gender) if b).strip()
    lead = f"{identity.name}, {descriptor}" if descriptor else identity.name

    parts = [lead]
    if face_line:
        parts.append(face_line)
    if body_line:
        parts.append(body_line)
    return ". ".join(parts) + "."


def build_card_prompt(identity: FounderIdentity, slot: str) -> str:
    """Full prompt for a single canon card slot."""
    spec = CARD_BY_SLOT.get(slot)
    if spec is None:
        raise KeyError(f"Unknown card slot: {slot!r}")
    preamble = build_preamble(identity)
    return (
        f"{SAFETY_PREFIX}. {preamble} {spec.clause}. "
        f"{STUDIO_FRAMING}. {ANTI_DRIFT}"
    )


def build_mark_prompt(identity: FounderIdentity, mark: MarkSpec) -> str:
    """Prompt for a single mark-detail crop card."""
    region = mark.body_region.replace("_", " ")
    return (
        f"{SAFETY_PREFIX}. Extreme close-up of {identity.name}'s {region} "
        f"({mark.side} side): {mark.description}. The marking is skin-bound and "
        f"permanent, reproduced exactly. {STUDIO_FRAMING}. {ANTI_DRIFT}"
    )


def validation_scene_prompts(identity: FounderIdentity) -> dict[str, Optional[str]]:
    """Return the 3 validation scene prompts (S24AL §5). None when unspecified.

    These run through the EXISTING canon scene generator
    (/identity-canon/scenes/generate) — not the card generator.
    """
    return {
        "casual": identity.casual_scene or None,
        "cinematic": identity.cinematic_scene or None,
        "environment": identity.environment_scene or None,
    }
