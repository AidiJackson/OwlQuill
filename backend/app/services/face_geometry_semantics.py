"""Authoritative anatomical semantics for the six Interview geometry fields.

Polish Phase 3 (prompt-semantics pass). Three responsibilities are kept apart:

  * the REFERENCE CARD (``frontend/public/creator-refs``) shows a human what
    an option looks like — explanatory UI, never a generation reference;
  * the STORED VALUE (``face_shape="angular"``) is the stable Ficshon
    vocabulary — validated in ``schemas/character_visual.py``, persisted in
    ``identity_spec_json`` / DNA, and never rewritten;
  * the PROMPT PHRASE — this module — tells the image model what anatomy the
    stored value means.

Before this module the four prompt builders (sketch, identity prompt, lock
string, V2 pack description) each interpolated the raw value almost
literally ("balanced lips", "angular face"), with three different label
conventions. Now every path calls :func:`geometry_phrases`, so one stored
value means one thing everywhere.

Semantic boundaries, deliberately (the Interview asks these separately):

  face_shape     overall outline, width/height proportion, silhouette — never
                 jaw width, jaw angle or chin shape;
  jaw_type       lower jawline, mandibular taper/angle, chin region;
  cheekbone_type ridge prominence or lateral placement — never the width of
                 the whole face.

A value has the same meaning whether or not another field is populated: no
field wins, nothing is reinterpreted conditionally. If a creator picks
"square face" and "narrow jaw" both phrases are emitted as written.

Two tiers of the same meaning. ``full`` is used by the sketch, the identity
prompt and the V2 pack description. ``lock`` is the compact form of every
value — same anatomy, fewer words — and it has two consumers:

  * ``compile_identity_lock_string`` always: lock strings are persisted into
    ``identity_anchor_json`` at pack-accept and then truncated from the tail
    by scene prompts (800 / 500 chars), so brevity there is load-bearing. The
    lock string carries only :data:`LOCK_FIELDS` (existing behaviour kept —
    eye_shape and cheekbone_type are not lock-string fields);
  * ``compile_identity_prompt`` only under budget pressure: the legacy
    identity prompt has a 1500-char cap and drops sections when it is over
    it. The full tier fits the cap for every human spec, but a non-human
    species descriptor can push a worst-case spec over, so the compiler
    re-renders the six geometry fields at this tier before it drops
    anything. That is why the tier is complete for all six fields, and why
    no compact phrase is longer than the literal wording it replaced (see
    the note above ``_LOCK``): compaction can only ever recover budget.

Unknown values. Pydantic rejects them on write, but the pack builder reads
raw dicts from DNA / legacy JSON. An unexpected historical value therefore
falls back to the pre-existing literal wording ("<value> <noun>") with a
warning, and the stored data is never touched.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Literal, Mapping, Optional

from app.schemas.character_visual import _FACIAL_GEOMETRY_FIELD_MAP

logger = logging.getLogger(__name__)

Tier = Literal["full", "lock"]

#: The six fields, in the order every prompt path emits them.
GEOMETRY_FIELDS: tuple[str, ...] = (
    "face_shape",
    "jaw_type",
    "cheekbone_type",
    "eye_shape",
    "nose_type",
    "lip_type",
)

#: The subset the lock STRING carries (existing behaviour, kept): the
#: highest-signal structural traits, so scene/body prompts stay short. The
#: lock TIER itself covers all six fields (see the module docstring).
LOCK_FIELDS: tuple[str, ...] = ("face_shape", "jaw_type", "nose_type", "lip_type")

#: The noun used by the literal fallback for an unknown value — the wording
#: every path used before this module, so a legacy value degrades to what it
#: produced yesterday rather than to nothing.
_FALLBACK_NOUN: dict[str, str] = {
    "face_shape": "face",
    "jaw_type": "jaw",
    "cheekbone_type": "cheekbones",
    "eye_shape": "eyes",
    "nose_type": "nose",
    "lip_type": "lips",
}

# Full tier. Approved anatomy, phrased at the density the identity prompt's
# 1500-char cap demands: a fully specified spec with the longest phrase in
# every field must still fit with the outfit lock and the shot instruction
# intact (test_face_geometry_semantics pins this), so each phrase is
# "<label>, <the one clause that separates it from its neighbours>".
_FULL: dict[str, dict[str, str]] = {
    "face_shape": {
        "oval": "oval face, softly curved, slightly longer than wide",
        "round": "round face, short wide proportions, rounded sides",
        "square": "square face, broad proportions, straight outer sides",
        "angular": "angular face, defined planes, tapered lower outline",
        "long": "long face, vertically elongated, narrow proportions",
    },
    "jaw_type": {
        "soft": "soft jawline, rounded transitions",
        "narrow": "narrow jaw tapering toward the chin",
        "square": "square jaw, broad flat lower line",
        "sharp": "sharp jawline, defined mandibular angle",
    },
    "cheekbone_type": {
        "subtle": "subtle cheekbones, low ridge prominence",
        "high": "high cheekbones, ridge set high under the eyes",
        "wide": "wide-set cheekbones, broad lateral spacing",
    },
    "eye_shape": {
        "almond": "almond eyes, tapered inner and outer corners",
        "round": "round eyes, open curved aperture",
        "narrow": "narrow eyes, slim horizontal aperture",
        "deep_set": "deep-set eyes recessed beneath the brow ridge",
    },
    "nose_type": {
        "straight": "straight nose, even bridge",
        "narrow": "narrow nose, slim bridge and narrow base",
        "broad": "broad nose, wide bridge and wide base",
        "hooked": "hooked nose, bridge curving to a downward tip",
        "roman": "Roman nose, prominent convex bridge",
        "upturned": "upturned nose, tip angled upward",
    },
    "lip_type": {
        "thin": "thin lips, little vertical fullness",
        "balanced": "medium lips, even upper and lower fullness",
        "full": "full lips, pronounced vertical fullness",
        "cupid_bow": "cupid's-bow lips, clearly peaked upper lip",
    },
}

# Lock tier. The same anatomy as _FULL, reduced to its label — the one or two
# words that separate the value from its neighbours in the same field. It is
# the emergency compaction tier of the two capped prompts as well as the
# persisted lock string, so it must be genuinely compact: for every value it
# is no longer than the literal wording those prompts used before this module
# ("<value> face" / "<value> jaw" / "<value> eyes" ...). That keeps the
# compact-tier prompt no longer than the pre-semantics prompt for the same
# spec, so budget pressure from free text (extra_notes, face_features) can
# never newly drop a section that the literal wording retained
# (test_face_geometry_semantics pins this, value by value). The richer
# anatomical clause lives in _FULL only.
_LOCK: dict[str, dict[str, str]] = {
    "face_shape": {
        "oval": "oval face",
        "round": "round face",
        "square": "square face",
        "angular": "angular face",
        "long": "long face",
    },
    "jaw_type": {
        "soft": "soft jaw",
        "narrow": "narrow jaw",
        "square": "square jaw",
        "sharp": "sharp jaw",
    },
    "cheekbone_type": {
        "subtle": "subtle cheekbones",
        "high": "high cheekbones",
        "wide": "wide cheekbones",
    },
    "eye_shape": {
        "almond": "almond eyes",
        "round": "round eyes",
        "narrow": "narrow eyes",
        "deep_set": "deep-set eyes",
    },
    "nose_type": {
        "straight": "straight nose",
        "narrow": "narrow nose",
        "broad": "broad nose",
        "hooked": "hooked nose",
        "roman": "Roman nose",
        "upturned": "upturned nose",
    },
    "lip_type": {
        "thin": "thin lips",
        "balanced": "medium lips",
        "full": "full lips",
        "cupid_bow": "cupid-bow lips",
    },
}

_TIERS: dict[str, dict[str, dict[str, str]]] = {"full": _FULL, "lock": _LOCK}


def _check_complete() -> None:
    """Every validated value has a phrase in both tiers, for all six fields.

    Runs at import so a vocabulary change in the schema without a phrase here
    fails the process, not a user's generation.
    """
    for field in GEOMETRY_FIELDS:
        valid = _FACIAL_GEOMETRY_FIELD_MAP[field]
        for tier_name, tier in _TIERS.items():
            missing = valid - set(tier.get(field, {}))
            if missing:
                raise RuntimeError(
                    f"face_geometry_semantics: {field} lacks {tier_name} phrases for {sorted(missing)}"
                )


_check_complete()


def geometry_phrase(field: str, value: Any, *, tier: Tier = "full") -> Optional[str]:
    """The prompt phrase for one stored value, or None when nothing is set.

    ``None`` / ``""`` / whitespace / ``"none"`` → None (the field is simply
    omitted; ``"none"`` is how the V2 pack builder's legacy dicts said unset).
    A value the tier does not know → the pre-existing literal
    ``"<value> <noun>"`` (underscores as spaces), logged at WARNING. The
    caller's data is not modified.
    """
    if field not in _FALLBACK_NOUN:
        raise KeyError(f"{field!r} is not a geometry field")
    if value is None:
        return None
    raw = str(getattr(value, "value", value)).strip()
    if not raw or raw.lower() == "none":
        return None
    # The validator stores lower-case; legacy DNA dicts predate it, so match
    # case-insensitively before treating a value as unknown.
    key = raw.lower()
    phrase = _TIERS[tier][field].get(key) if field in _TIERS[tier] else None
    if phrase is not None:
        return phrase
    fallback = f"{key.replace('_', ' ')} {_FALLBACK_NOUN[field]}"
    logger.warning(
        "face_geometry_semantics: no %s-tier phrase for %s=%r; using literal %r",
        tier, field, raw, fallback,
    )
    return fallback


def _get(spec: Any, field: str) -> Any:
    if isinstance(spec, Mapping):
        return spec.get(field)
    return getattr(spec, field, None)


def geometry_phrases(
    spec: Any,
    *,
    tier: Tier = "full",
    fields: Iterable[str] = GEOMETRY_FIELDS,
) -> list[str]:
    """Phrases for every populated geometry field on ``spec``, in field order.

    ``spec`` may be a ``CharacterIdentitySpec`` or a plain dict (the V2 pack
    builder works on the raw ``identity_spec`` dict). Fields that are unset
    contribute nothing; each populated field contributes exactly one phrase
    that depends on its own value only.
    """
    out: list[str] = []
    for field in fields:
        phrase = geometry_phrase(field, _get(spec, field), tier=tier)
        if phrase:
            out.append(phrase)
    return out
