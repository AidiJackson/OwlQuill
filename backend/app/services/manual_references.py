"""Manual generation references — validation, roles, and the canon merge policy.

A founder may hand-pick up to :data:`MAX_MANUAL_REFERENCES` of their own
character images as extra visual evidence for one generation. This module owns
three things and nothing else:

1. **Validation** (:func:`resolve_manual_references`) — turning client-supplied
   ids into real rows, refusing anything the caller may not use.
2. **Roles** (:data:`ReferenceRole`, :func:`build_reference_notes`) — the
   optional per-reference meaning, and the prompt text that carries it.
3. **The merge policy** (:func:`merge_reference_sets`) — how canon references
   and manual references share one bounded provider payload.

Why manual references are NOT canon
-----------------------------------
Canon (``character_identity_canon``) remains the authoritative answer to who the
character is. A manual reference is *supporting evidence for one image*: it is
an input to a single generation and is never written back to a canon slot, never
promoted, and never consulted by ``canon_compiler`` or ``scene_router``. Nothing
in this module writes to the canon tables — it only reads ``character_images``.

The merge policy, stated once
-----------------------------
Providers take a bounded number of references (``scene_router.MAX_PROVIDER_REFS``
= 6, further narrowed by a model's documented ``max_reference_images``). Canon
routing can already fill that budget on its own, so canon + manual can overflow.
The policy is deliberate and deterministic:

* **Canon first, in router order.** Canon is identity truth; it is never trimmed
  to make room for a manual reference. "Augment, not replace" is enforced here.
* **Manual next, in the exact order the client listed them.** The founder's
  ordering is meaningful (they put the important reference first), so it is
  preserved rather than re-sorted.
* **Overflow is dropped from the TAIL of the manual block only.** Never from
  canon, never from an arbitrary position.
* **Nothing is dropped silently.** Every omission is reported — which id, which
  role, which position, and why — in the generation metadata and in the job
  result, so the founder can see that reference 4 did not reach the provider.

Byte-identical duplicates are then removed by the caller's existing dedup pass
(first occurrence wins), which is why a manual reference that repeats a canon
card costs nothing and changes no ordering.
"""
from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any, Iterable, Optional

from app.models.character_image import (
    REFERENCE_SELECTABLE_IMAGE_KINDS,
    CharacterImage,
    ImageStatusEnum,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.orm import Session

#: Hard cap on hand-picked references per generation (product decision).
MAX_MANUAL_REFERENCES = 4


class ReferenceRole(str, enum.Enum):
    """What a manual reference is FOR.

    Optional per reference. The role is advisory prompt context — it tells the
    model how to read that image. It confers no authority: a
    ``CHARACTER_APPEARANCE`` role does not make the image identity truth, and
    canon still governs identity when the generation is canon-grounded.
    """

    CHARACTER_APPEARANCE = "character_appearance"
    CLOTHING = "clothing"
    ENVIRONMENT = "environment"
    OTHER = "other"
    #: Explicitly no stated meaning — the model is given the image with no note.
    UNSPECIFIED = "unspecified"


#: Prompt phrasing per role. Deliberately short: these ride at the tail of an
#: already-long compiled prompt, where image models weight instructions well but
#: where length competes with the canon clauses that must survive.
_ROLE_PHRASES: dict[ReferenceRole, str] = {
    ReferenceRole.CHARACTER_APPEARANCE: "supporting appearance reference for this character",
    ReferenceRole.CLOTHING: "the clothing and outfit to reproduce",
    ReferenceRole.ENVIRONMENT: "the environment, setting and lighting to reproduce",
    ReferenceRole.OTHER: "an additional visual reference for this scene",
}

#: Appended when the generation is canon-grounded AND at least one manual
#: reference carries a role. Manual evidence must never be read as an identity
#: override — the compiled canon block above it stays authoritative.
_CANON_PRECEDENCE_CLAUSE = (
    "The character's identity is defined by the locked description and character "
    "reference images above; the supplied references below inform this scene only "
    "and never override that identity."
)


class ManualReferenceError(Exception):
    """A manual reference selection the caller may not use.

    Carries an HTTP status hint so both the sync route and the job submission
    path report the same thing.
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ResolvedReference:
    """One validated manual reference: the row, its role, and its position."""

    __slots__ = ("image", "role", "position")

    def __init__(self, image: CharacterImage, role: ReferenceRole, position: int) -> None:
        self.image = image
        self.role = role
        self.position = position

    @property
    def image_id(self) -> int:
        return int(self.image.id)

    @property
    def file_path(self) -> str:
        return str(self.image.file_path)

    def describe(self, *, sent: bool, reason: Optional[str] = None) -> dict[str, Any]:
        """Audit record for generation metadata / the job result."""
        entry: dict[str, Any] = {
            "image_id": self.image_id,
            "role": self.role.value,
            "position": self.position,
            "kind": getattr(self.image.kind, "value", self.image.kind),
            "sent": sent,
        }
        if reason:
            entry["reason"] = reason
        return entry


def parse_role(raw: Optional[str]) -> ReferenceRole:
    """Coerce a client-supplied role string to a :class:`ReferenceRole`.

    An absent role is UNSPECIFIED (the documented default). An unrecognised role
    is an ERROR rather than a silent downgrade to UNSPECIFIED: a typo'd role
    would otherwise change what the model is told without anyone noticing.
    """
    if raw is None or raw == "":
        return ReferenceRole.UNSPECIFIED
    try:
        return ReferenceRole(raw)
    except ValueError:
        valid = ", ".join(sorted(r.value for r in ReferenceRole))
        raise ManualReferenceError(
            422, f"Unknown reference role {raw!r}. Valid roles: {valid}."
        ) from None


def resolve_manual_references(
    db: "Session",
    *,
    character_id: int,
    image_ids: Iterable[int],
    roles: Optional[Iterable[Optional[str]]] = None,
) -> list[ResolvedReference]:
    """Validate hand-picked reference ids against the database.

    Every id must independently satisfy ALL of:

    * it exists;
    * it belongs to THIS character (an id from another character the founder
      also owns is refused — a generation is character-scoped, exactly as post
      image attachment is);
    * its status is ACTIVE (an archived/soft-deleted image is refused);
    * its kind is in ``REFERENCE_SELECTABLE_IMAGE_KINDS`` (canon/identity slots
      are not hand-pickable — see that constant for why);
    * it is not a temporary pack preview.

    Ids are never trusted: the rows are re-read here and the caller's ownership
    check on the CHARACTER is what authorises the whole set. Order is preserved
    as given. Duplicate ids are refused rather than deduped, because a repeated
    id is a client bug and silently collapsing it would misreport the count the
    founder chose.

    Raises :class:`ManualReferenceError`; returns ``[]`` for an empty selection.
    """
    ids = [int(i) for i in image_ids]
    if not ids:
        return []
    if len(ids) > MAX_MANUAL_REFERENCES:
        raise ManualReferenceError(
            422,
            f"At most {MAX_MANUAL_REFERENCES} reference images may be selected "
            f"(received {len(ids)}).",
        )
    if len(set(ids)) != len(ids):
        raise ManualReferenceError(422, "The same reference image was selected more than once.")

    role_list = list(roles or [])
    if role_list and len(role_list) != len(ids):
        raise ManualReferenceError(
            422,
            "reference_roles must be the same length as reference_image_ids "
            f"({len(role_list)} roles for {len(ids)} references).",
        )
    parsed_roles = [parse_role(role_list[i] if role_list else None) for i in range(len(ids))]

    rows = (
        db.query(CharacterImage)
        .filter(CharacterImage.id.in_(ids))
        .all()
    )
    by_id = {int(r.id): r for r in rows}

    resolved: list[ResolvedReference] = []
    for position, image_id in enumerate(ids):
        row = by_id.get(image_id)
        # One message for "missing" and "not this character's": distinguishing
        # them would confirm which ids exist on characters the caller cannot see.
        if row is None or int(row.character_id) != int(character_id):
            raise ManualReferenceError(
                422,
                f"Reference image {image_id} is not available for this character.",
            )
        if row.status != ImageStatusEnum.ACTIVE:
            raise ManualReferenceError(
                422, f"Reference image {image_id} has been deleted and can't be used."
            )
        kind_value = getattr(row.kind, "value", row.kind)
        if kind_value not in REFERENCE_SELECTABLE_IMAGE_KINDS:
            raise ManualReferenceError(
                422,
                f"Reference image {image_id} is character canon material and can't be "
                "hand-picked as a reference.",
            )
        if (row.metadata_json or {}).get("is_temp", False):
            raise ManualReferenceError(
                422, f"Reference image {image_id} is a temporary preview and can't be used."
            )
        resolved.append(ResolvedReference(row, parsed_roles[position], position))

    return resolved


def merge_reference_sets(
    *,
    canon_urls: list[str],
    manual: list[ResolvedReference],
    budget: int,
) -> tuple[list[str], list[ResolvedReference], list[ResolvedReference]]:
    """Apply the documented merge policy to one generation's reference sets.

    Returns ``(ordered_urls, manual_sent, manual_dropped)``:

    * ``ordered_urls`` — canon references first in router order, then the manual
      references that fit, in client order. This is the list the caller loads
      bytes for.
    * ``manual_sent`` / ``manual_dropped`` — the split, so both can be reported.

    Canon is never trimmed. When canon alone already fills ``budget``, every
    manual reference is dropped and reported; that is a real outcome the founder
    is told about, not a silent no-op.
    """
    kept_canon = list(canon_urls[:budget])
    room = max(0, budget - len(kept_canon))
    manual_sent = list(manual[:room])
    manual_dropped = list(manual[room:])
    ordered = kept_canon + [r.file_path for r in manual_sent]
    return ordered, manual_sent, manual_dropped


def refs_source(*, canon_count: int, manual_count: int) -> str:
    """Classify what the provider's reference set was actually made of.

    Distinct from ``canon_used``, whose meaning is unchanged: ``canon_used``
    says whether this generation was compiled from locked canon at all, and
    stays True for a canon generation even when canon routing selected no cards.
    ``refs_source`` describes the reference payload only.
    """
    if canon_count and manual_count:
        return "mixed"
    if manual_count:
        return "manual"
    if canon_count:
        return "canon"
    return "none"


def build_reference_notes(
    manual_sent: list[ResolvedReference],
    *,
    canon_ref_count: int,
    canon_grounded: bool,
) -> str:
    """Prompt text describing the manual references, or ``""`` when there is none.

    The notes are APPENDED to the already-compiled prompt so canon compilation is
    untouched — ``canon_compiler.compile_canon_prompt`` produces exactly what it
    produced before, and this text rides behind it where image models weight
    trailing instructions well (the same placement the cover directives use).

    References are numbered by their position in the payload actually sent, so
    "Reference 4" names the fourth image the provider received. Roles left
    UNSPECIFIED contribute no line at all: the image is still sent, but the model
    is told nothing about it rather than being told something invented.
    """
    lines: list[str] = []
    for offset, ref in enumerate(manual_sent):
        phrase = _ROLE_PHRASES.get(ref.role)
        if phrase is None:  # UNSPECIFIED — deliberately silent
            continue
        lines.append(f"Reference image {canon_ref_count + offset + 1} is {phrase}.")
    if not lines:
        return ""
    parts = ["SUPPLIED REFERENCES — " + " ".join(lines)]
    if canon_grounded:
        parts.append(_CANON_PRECEDENCE_CLAUSE)
    return " " + " ".join(parts)
