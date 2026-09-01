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
There are two modes, and which one applies is decided by the SURFACE that
submitted the generation — never by the character, the prompt or the provider.

``augment`` (:data:`REFERENCE_MODE_AUGMENT`) — the default, and the only mode the
Image Generator on /images uses. Behaviour is exactly what it has always been:

* **Canon first, in router order.** Canon is identity truth; it is never trimmed
  to make room for a manual reference. "Augment, not replace" is enforced here.
* **Manual next, in the exact order the client listed them.** The founder's
  ordering is meaningful (they put the important reference first), so it is
  preserved rather than re-sorted.
* **Overflow is dropped from the TAIL of the manual block only.** Never from
  canon, never from an arbitrary position.

``deliberate`` (:data:`REFERENCE_MODE_DELIBERATE`) — Admin Creator only. There
the four reference cards ARE the creative brief: a workflow that offers four
slots and then supplements them with automatically chosen ones is not the
workflow that was asked for. The pipeline therefore bypasses canon entirely for
these generations (see ``image_generation_pipeline.run_image_generation``), so
``canon_urls`` arrives here EMPTY and the merge resolves to the cards alone.

The manual-first branch below is kept as a deliberate SAFETY NET rather than as
live policy:

* **Manual first, in card order**, never trimmed while budget remains.
* **Canon fills any remaining capacity**, in router priority order, trimmed from
  its TAIL.
* Manual references lead the payload, so the caller's byte-dedup pass — first
  occurrence wins — resolves a manual/canon duplicate in the MANUAL card's
  favour.

If the canon bypass ever regresses, that branch is what keeps the founder's
cards in front of the provider instead of letting canon crowd them out again.
It costs nothing while the bypass holds.

Both modes are pure selection and ordering of what is SENT. Neither writes to
canon.

* **Nothing is dropped silently, in either mode.** Every omission is reported —
  which id, which role, which position, and why — in the generation metadata and
  in the job result, so the founder can see that reference 4 did not reach the
  provider, or that deliberate cards displaced two canon references.
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

#: Canon-driven. Canon is compiled and routed, and manual references use only
#: the capacity canon leaves. The default everywhere, and the only mode the
#: /images Image Generator uses.
REFERENCE_MODE_AUGMENT = "augment"
#: Reference-driven. The hand-picked cards and the prompt are the entire brief;
#: the pipeline bypasses canon compilation and canon reference routing, and the
#: selected character is only the owner of the resulting row. Admin Creator
#: only; founder/seeder gated at the route.
REFERENCE_MODE_DELIBERATE = "deliberate"
#: Every accepted mode. An unknown value normalises to AUGMENT, never raises:
#: an old job row predates the field entirely (see ``GenerationParams``).
REFERENCE_MODES = (REFERENCE_MODE_AUGMENT, REFERENCE_MODE_DELIBERATE)


def normalise_reference_mode(raw: Optional[str]) -> str:
    """Coerce a stored or client-supplied mode to a known one.

    Deliberately forgiving, unlike :func:`parse_role`. A role typo changes what
    the model is TOLD and must be caught; an absent or unrecognised mode simply
    means "no deliberate intent was recorded", and the safe reading of that is
    the pre-existing canon-first policy. This is what makes a job row written
    before ``reference_mode`` existed replay as ``augment``.
    """
    return raw if raw in REFERENCE_MODES else REFERENCE_MODE_AUGMENT


class ReferenceRole(str, enum.Enum):
    """What a manual reference is FOR.

    Optional per reference. The role is advisory prompt context — it tells the
    model how to read that image. It confers no authority over CANON: a role
    does not make an image identity truth, and canon still governs identity when
    the generation is canon-grounded.

    Two vocabularies share this enum, because both submit through the same
    endpoint:

    * the ORIGINAL five, which the Image Generator on /images offers and which
      compile exactly as they always have (see :data:`_ROLE_PHRASES`);
    * the Admin Creator additions — the identity buckets, the scene-attribute
      roles and the eight facial/attribute-authority roles — which only carry
      meaning under ``deliberate`` mode, where canon is bypassed and the cards
      are the entire brief. Under ``augment`` they contribute no prompt line at
      all, exactly like UNSPECIFIED, so an /images request can never be changed
      by them. That fall-through is the whole compatibility mechanism: a role is
      opted IN to /images by appearing in :data:`_ROLE_PHRASES`, and none of
      these do.
    """

    #: Legacy. Supporting appearance evidence with no identity-grouping claim.
    #: Kept because /images offers it; Admin Creator offers CHARACTER_1 instead.
    CHARACTER_APPEARANCE = "character_appearance"
    #: Identity bucket A. Every card marked CHARACTER_1 is the SAME person.
    CHARACTER_1 = "character_1"
    #: Identity bucket B. Every card marked CHARACTER_2 is the SAME person, and
    #: a DIFFERENT person from CHARACTER_1.
    CHARACTER_2 = "character_2"
    CLOTHING = "clothing"
    ENVIRONMENT = "environment"
    #: Permanent-mark design and placement evidence. Says how a mark LOOKS and
    #: WHERE it sits — never that it must be visible.
    TATTOO_MARK = "tattoo_mark"
    #: Pose, framing and composition. A person visible in such an image is
    #: staging, not a character.
    POSE_COMPOSITION = "pose_composition"

    # ── Attribute-authority roles (Admin Creator, deliberate mode only) ──
    #
    # Each says "take THIS feature from this image and nothing else". They are
    # attribute evidence, never identity evidence: the person shown is a source
    # for one named trait and is not a character in the resulting image. That
    # disclaimer is carried in every phrase below, because the failure they
    # exist to prevent — a face supplied as eye evidence arriving whole — is the
    # default behaviour of every model we send them to.
    EYES = "eyes"
    NOSE = "nose"
    MOUTH_LIPS = "mouth_lips"
    FACE_SHAPE = "face_shape"
    EYEBROWS = "eyebrows"
    HAIR = "hair"
    FACIAL_HAIR = "facial_hair"
    SKIN_COMPLEXION = "skin_complexion"

    OTHER = "other"
    #: Explicitly no stated meaning — the model is given the image with no note.
    UNSPECIFIED = "unspecified"


#: The two manual identity buckets, and the names the provider is given for
#: them. Deliberately "Person A"/"Person B" rather than "Character 1/2": the
#: buckets are not Ficshon character records and must not be read as such, and a
#: model handles two plainly-named people better than two numbered slots.
_PERSON_LABELS: dict[ReferenceRole, str] = {
    ReferenceRole.CHARACTER_1: "Person A",
    ReferenceRole.CHARACTER_2: "Person B",
}

#: Stable provenance tag per identity bucket, recorded in the reference audit so
#: a past generation can be shown to have grouped its references correctly.
_IDENTITY_GROUPS: dict[ReferenceRole, str] = {
    ReferenceRole.CHARACTER_1: "person_a",
    ReferenceRole.CHARACTER_2: "person_b",
}

#: The attribute-authority roles, as a set.
#:
#: Membership — not card count, card position or any board size — is what the
#: construction/refinement derivation below reads. The board happens to offer
#: four cards today; nothing here knows or cares how many there are, so raising
#: the reference budget later is a change to budgeting alone.
_FEATURE_ROLES: frozenset[ReferenceRole] = frozenset(
    {
        ReferenceRole.EYES,
        ReferenceRole.NOSE,
        ReferenceRole.MOUTH_LIPS,
        ReferenceRole.FACE_SHAPE,
        ReferenceRole.EYEBROWS,
        ReferenceRole.HAIR,
        ReferenceRole.FACIAL_HAIR,
        ReferenceRole.SKIN_COMPLEXION,
    }
)


def board_is_self_describing(roles: Iterable[ReferenceRole]) -> bool:
    """True when the cards alone specify a complete operation.

    This is what makes the free-text prompt OPTIONAL rather than required. A
    board qualifies only when the compiled block already states an operation
    with a subject:

    * any feature role — the notes carry a ``Required sources``/``Required
      changes to Person A`` list, which names both the operation and every
      input to it (construction and refinement alike);
    * CHARACTER_1 with POSE_COMPOSITION — identity plus framing, the canon-card
      pass, complete without prose.

    Everything else stays prompt-required, and the exclusions matter more than
    the inclusions:

    * two identity buckets and nothing else name two people and no event — "who
      is here" is not "what is happening";
    * clothing / environment / tattoo boards describe attributes with no
      subject and no action;
    * an all-UNSPECIFIED board compiles to NO notes at all, so an empty prompt
      there would send the provider an empty prompt.

    Roles only, deliberately: no count, no ordering, no board size. The caller
    additionally checks that the compiled notes are non-empty, so a shape that
    qualifies here can still never produce an empty provider prompt.
    """
    present = set(roles)
    if present & _FEATURE_ROLES:
        return True
    return {ReferenceRole.CHARACTER_1, ReferenceRole.POSE_COMPOSITION} <= present


def has_ambiguous_refinement_subject(roles: Iterable[ReferenceRole]) -> bool:
    """True when a board asks to change a feature but supplies several Person A images.

    A feature change is an edit, and an edit needs ONE starting image. The
    identity buckets deliberately group: several CHARACTER_1 cards compile to
    "Reference images 1, 3 and 4 are all the same person … reproduce that
    person's face and likeness exactly", which is correct for two photographs of
    one person and incoherent as the subject of "replace Person A's hair" — the
    referent is a set, and the model has to guess which member's hair is the
    hair being replaced.

    Observed 2026-08-22: three Character 1 cards accumulated across a repeated
    Hair refinement (each generated result was ADDED rather than replacing the
    previous one) and the original hairstyle returned, because the first card
    still asserted it and nothing arbitrated. The precedence clause cannot help
    here — it is scoped to attributes that are NOT required changes, precisely
    so that identity cannot veto an explicit feature replacement.

    Refused rather than silently resolved: any tie-break we invented would be a
    guess about which image the founder meant, and getting it wrong costs a paid
    generation that looks plausible.
    """
    present = list(roles)
    if not (set(present) & _FEATURE_ROLES):
        return False
    return sum(1 for r in present if r is ReferenceRole.CHARACTER_1) > 1


def describe_board_operation(roles: Iterable[ReferenceRole]) -> str:
    """Short human summary of a self-describing board, for ``prompt_summary``.

    A promptless generation would otherwise save a blank summary, leaving a row
    in the founder's library with nothing to identify it by.
    """
    present = list(roles)
    features = [r for r in present if r in _FEATURE_ROLES]
    # Deduped, first-appearance order — mirrors the required-change list.
    seen: list[str] = []
    for r in features:
        noun = _FEATURE_EDIT_NOUNS[r]
        if noun not in seen:
            seen.append(noun)
    if features and ReferenceRole.CHARACTER_1 in present:
        return f"Refine Person A — {', '.join(seen)}"
    if features:
        return f"Construct a face — {', '.join(seen)}"
    if ReferenceRole.CHARACTER_1 in present:
        return "Pose Person A"
    return "Reference-driven generation"


def is_feature_role(role: ReferenceRole) -> bool:
    """True for an attribute-authority role (eyes, nose, hair, …).

    Public because the frontend's vocabulary mirrors this split and the tests
    pin the two lists against each other.
    """
    return role in _FEATURE_ROLES


#: AUGMENT-mode phrasing per role. Deliberately short: these ride at the tail of
#: an already-long compiled prompt, where image models weight instructions well
#: but where length competes with the canon clauses that must survive.
#:
#: FROZEN. These four strings and this mapping are what /images has always sent;
#: changing any of them changes every canon-grounded generation. The Admin
#: Creator roles are deliberately ABSENT, so under augment they fall through to
#: "no line" rather than acquiring meaning on a surface that never offered them.
_ROLE_PHRASES: dict[ReferenceRole, str] = {
    ReferenceRole.CHARACTER_APPEARANCE: "supporting appearance reference for this character",
    ReferenceRole.CLOTHING: "the clothing and outfit to reproduce",
    ReferenceRole.ENVIRONMENT: "the environment, setting and lighting to reproduce",
    ReferenceRole.OTHER: "an additional visual reference for this scene",
}

#: DELIBERATE-mode phrasing per non-identity role.
#:
#: Richer than the augment set because the situation is different: canon is
#: bypassed, so these sentences are the ONLY thing telling the model how to read
#: four images that may disagree with each other. Each one states what the image
#: IS authority for and, where it matters, what it is NOT — the Davies run of
#: 2026-08-22 produced a cut sleeve and an exposed forearm tattoo precisely
#: because an appearance photo with rolled sleeves was the only evidence about
#: his arms and nothing said it was not the outfit.
_DELIBERATE_ROLE_PHRASES: dict[ReferenceRole, str] = {
    ReferenceRole.CHARACTER_APPEARANCE: (
        "a supporting appearance reference; use it for likeness only, not for "
        "clothing, pose or setting"
    ),
    ReferenceRole.CLOTHING: (
        "the clothing and outfit to reproduce, including how the garments are "
        "worn and how far the sleeves and hems extend; it is not identity evidence"
    ),
    ReferenceRole.ENVIRONMENT: (
        "the environment, setting, atmosphere and lighting to reproduce; it is "
        "not identity evidence, and any person visible in it is not a character "
        "in this scene"
    ),
    ReferenceRole.TATTOO_MARK: (
        "permanent-mark evidence: it defines how the marks look and where on the "
        "body they sit. It does NOT mean any mark must be visible — a mark the "
        "clothing in this scene covers stays covered"
    ),
    ReferenceRole.POSE_COMPOSITION: (
        "the pose, framing and composition to follow; it is not identity "
        "evidence, and any person visible in it is not a character in this scene"
    ),
    ReferenceRole.OTHER: "an additional visual reference for this scene",
    # ── Attribute-authority phrases ──
    #
    # One shape, applied eight times: name the feature, enumerate what about it
    # is authoritative, then disclaim the rest of the person. The enumeration is
    # not decoration — "the eyes" alone leaves the model to decide whether that
    # includes the brow, the socket and the surrounding face, and it decides
    # generously.
    #
    # The three non-facial roles say "their facial features" where the five
    # facial ones say "their OTHER facial features": hair is not a facial
    # feature, and telling a model to ignore the "other" facial features of a
    # hair reference implies the hair was one.
    ReferenceRole.EYES: (
        "the eyes only: use the eye shape, colour, spacing and eyelid form as "
        "visual evidence. The person shown is not this character — do not copy "
        "their other facial features or likeness"
    ),
    ReferenceRole.NOSE: (
        "the nose only: use the bridge, width, tip and nostril shape as visual "
        "evidence. The person shown is not this character — do not copy their "
        "other facial features or likeness"
    ),
    ReferenceRole.MOUTH_LIPS: (
        "the mouth and lips only: use the lip shape, fullness, width and resting "
        "mouth line as visual evidence. The person shown is not this character — "
        "do not copy their other facial features or likeness"
    ),
    ReferenceRole.FACE_SHAPE: (
        "the face shape only: use the overall facial proportions, cheekbones, "
        "jawline and chin structure as visual evidence. The person shown is not "
        "this character — do not copy their other facial features or likeness"
    ),
    ReferenceRole.EYEBROWS: (
        "the eyebrows only: use the brow shape, thickness, density and arch as "
        "visual evidence. The person shown is not this character — do not copy "
        "their other facial features or likeness"
    ),
    ReferenceRole.HAIR: (
        "the hair only: use the hairstyle, length, colour, texture and hairline "
        "as visual evidence. The person shown is not this character — do not "
        "copy their facial features or likeness"
    ),
    ReferenceRole.FACIAL_HAIR: (
        "the facial hair only: use the beard, moustache or stubble style, length "
        "and coverage as visual evidence. The person shown is not this character "
        "— do not copy their facial features or likeness"
    ),
    ReferenceRole.SKIN_COMPLEXION: (
        "the skin only: use the skin tone, texture, freckles and complexion as "
        "visual evidence. The person shown is not this character — do not copy "
        "their facial features or likeness"
    ),
}

#: Stated whenever both identity buckets are in play. The failure it exists to
#: prevent is the model averaging two supplied faces into one person, or giving
#: the second person the first one's features.
_IDENTITY_SEPARATION_CLAUSE = (
    "{a} and {b} are two DIFFERENT people and both appear in this scene. Keep "
    "their identities completely separate: do not blend, average, morph, merge "
    "or swap faces, features or likenesses between them."
)

#: Appended when the generation is canon-grounded AND at least one manual
#: reference carries a role. Manual evidence must never be read as an identity
#: override — the compiled canon block above it stays authoritative.
_CANON_PRECEDENCE_CLAUSE = (
    "The character's identity is defined by the locked description and character "
    "reference images above; the supplied references below inform this scene only "
    "and never override that identity."
)

# ── Character-construction clauses (deliberate mode, feature roles present) ──
#
# The per-image phrases say what each reference IS. These four say what to DO
# with a set of them, and they are where the two Character Build passes actually
# differ. All are conditional on at least one feature role being present, which
# is what keeps every feature-free board byte-identical to what it produced
# before these existed.

#: Stated whenever any feature role is in play. Without it, four faces supplied
#: as four features read as four people, and the model stages a group shot.
_FEATURE_SOURCE_CLAUSE = (
    "The feature references above show different people used only as evidence "
    "for the feature each one is named for. They are not characters in this "
    "image, they are not additional people in the scene, and their identities "
    "must not be merged, averaged or carried across."
)

#: How each feature is NAMED in a required-change list.
#:
#: Separate from the per-image phrases above, which describe evidence in detail.
#: These are the short operative nouns an instruction reads naturally with:
#: "replace Person A's mouth and lips with …". Two roles widen slightly here
#: (face shape gains "and jawline", skin gains "and complexion") because the
#: bare noun is ambiguous in an imperative where it was not in a description.
_FEATURE_EDIT_NOUNS: dict[ReferenceRole, str] = {
    ReferenceRole.EYES: "eyes",
    ReferenceRole.NOSE: "nose",
    ReferenceRole.MOUTH_LIPS: "mouth and lips",
    ReferenceRole.FACE_SHAPE: "face shape and jawline",
    ReferenceRole.EYEBROWS: "eyebrows",
    ReferenceRole.HAIR: "hair",
    ReferenceRole.FACIAL_HAIR: "facial hair",
    ReferenceRole.SKIN_COMPLEXION: "skin tone and complexion",
}

#: Said in both passes, and the reason this machinery exists.
#:
#: Observed 2026-08-22 on Gemini: a board carrying Hair and Eyebrows references
#: changed the eyebrows and kept the original hair, because every sentence in
#: the block described what the images WERE and none demanded an outcome. "Use
#: as visual evidence" is satisfied by a model that looks and then does nothing.
#: The free-text prompt was the only place a change was ever actually required,
#: which made the structured selection decorative — the founder had to restate
#: every card in prose for it to take effect.
_PROMPT_INDEPENDENCE = "whether or not the scene description mentions it"


def _ref_phrase(numbers: list[int]) -> str:
    """"reference image 2" / "reference images 2 and 3"."""
    if len(numbers) == 1:
        return f"reference image {numbers[0]}"
    return f"reference images {_join_numbers(numbers)}"


def _construction_clause(items: list[str]) -> str:
    """Pass 1 — features with no identity bucket.

    There is no person yet, so the instruction is to SYNTHESISE one. The
    enumerated sources are what stop the model anchoring on whichever reference
    happens to show a whole face and taking everything else from it too: on
    2026-08-22 a board of face-shape + hair + eyebrows kept the face-shape
    source's hair, because nothing said the hair had to come from image 2.
    """
    return (
        "Combine the named features into ONE single coherent photorealistic "
        "person who appears in none of the references. "
        f"Required sources: {'; '.join(items)}. "
        f"Use every source in that list, {_PROMPT_INDEPENDENCE}, and resolve "
        "them into one natural, consistent face."
    )


def _refinement_clause(items: list[str]) -> str:
    """Pass 2 — features WITH Person A.

    Leads with preserving the identity, because that is what is most at risk,
    then states the edits as required operations. The previous wording bounded
    the SCOPE of a change ("changes nothing except the attribute it is named
    for") without ever requiring one, which a model satisfies by changing
    nothing at all.
    """
    return (
        "Person A is the identity of this image and must be preserved exactly: "
        "the face, bone structure and likeness of Person A stay the same. "
        f"Required changes to Person A: {'; '.join(items)}. "
        f"Make every change in that list, {_PROMPT_INDEPENDENCE}. Every "
        "attribute not in that list stays exactly as it is in Person A."
    )


#: The tie-breaker, emitted last where trailing instructions carry weight.
#:
#: This is a STATED contract, not an enforced one — the pipeline sends bytes and
#: text and has no weighting mechanism. Its value is that the ordering is
#: deterministic and pinned by tests, so a drifting result can be compared
#: against what the model was actually told.
#:
#: SCOPED to unlisted conflicts on purpose. Placed after a required-change list,
#: an unqualified "the identity of the person comes first" is readable as a veto
#: — the model can honour it by refusing the hair change in order to protect
#: Person A, which is precisely the failure the list above exists to fix. The
#: hierarchy is unchanged for everything that is not an explicit required change.
_ROLE_PRECEDENCE_CLAUSE = (
    "Where these references disagree on anything not listed as a required "
    "change above, resolve in this order: the identity of the person comes "
    "first, then the feature references for the attribute each is named for, "
    "then pose and framing, then clothing, then environment."
)

#: Roles that can contend with a feature reference and therefore make the
#: precedence clause worth spending prompt length on. TATTOO_MARK sits with the
#: features (it is attribute evidence about the body); OTHER and UNSPECIFIED
#: claim nothing and are deliberately absent.
_PRECEDENCE_CONTENDERS: frozenset[ReferenceRole] = frozenset(
    {
        ReferenceRole.CHARACTER_1,
        ReferenceRole.CHARACTER_2,
        ReferenceRole.POSE_COMPOSITION,
        ReferenceRole.CLOTHING,
        ReferenceRole.ENVIRONMENT,
    }
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

    @property
    def identity_group(self) -> Optional[str]:
        """``"person_a"``/``"person_b"`` for an identity bucket, else None.

        Provenance, not behaviour: it is what lets a past generation be shown to
        have grouped two cards as one person rather than as two.
        """
        return _IDENTITY_GROUPS.get(self.role)

    def describe(
        self,
        *,
        sent: bool,
        reason: Optional[str] = None,
        isolation: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Audit record for generation metadata / the job result.

        ``isolation`` carries the provenance of a derived provider-only
        representation (see ``reference_isolation``): whether a transform was
        applied, which version produced it, and its status. It is merged in
        rather than nested so a reference reads as one flat record, and it is
        OMITTED entirely for references that were never eligible — the absence
        of the key means "no isolation was ever in play here", which is exactly
        true of every Character 1/2, clothing, environment, pose, tattoo and
        canon reference.

        ``image_id`` is unchanged and still names the ORIGINAL row: a derived
        representation is never persisted, so the original plus the role plus
        the version is what identifies what the provider received.
        """
        entry: dict[str, Any] = {
            "image_id": self.image_id,
            "role": self.role.value,
            "position": self.position,
            "kind": getattr(self.image.kind, "value", self.image.kind),
            "sent": sent,
        }
        if isolation:
            entry.update(isolation)
        # Present only for the identity roles, so an older record's absence of
        # the key is not mistaken for "grouped as nobody".
        if self.identity_group:
            entry["identity_group"] = self.identity_group
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
    mode: str = REFERENCE_MODE_AUGMENT,
) -> tuple[list[str], list[ResolvedReference], list[ResolvedReference]]:
    """Apply the documented merge policy to one generation's reference sets.

    Returns ``(ordered_urls, manual_sent, manual_dropped)``:

    * ``ordered_urls`` — the payload order the caller loads bytes for. Under
      ``augment`` that is canon (router order) then manual (card order); under
      ``deliberate`` it is manual (card order) then canon (router order).
    * ``manual_sent`` / ``manual_dropped`` — the split, so both can be reported.

    How many canon references survived is deliberately NOT a fourth return
    value: it is exactly ``len(ordered_urls) - len(manual_sent)`` in both modes,
    and the caller already needs that arithmetic for its audit record.

    ``augment`` — canon is never trimmed. When canon alone already fills
    ``budget``, every manual reference is dropped and reported; that is a real
    outcome the founder is told about, not a silent no-op.

    ``deliberate`` — manual is never trimmed while budget remains, and canon is
    trimmed from its tail instead. A manual reference is dropped here ONLY when
    the founder selected more cards than the provider budget itself allows
    (``MAX_MANUAL_REFERENCES`` is 4 against a budget of 6, so this needs a model
    whose documented limit is narrower than the card count) — and it is reported
    identically when it happens.

    An unknown ``mode`` is treated as ``augment`` by
    :func:`normalise_reference_mode`; callers should normalise before calling,
    and this function re-checks rather than trusting the string.
    """
    if normalise_reference_mode(mode) == REFERENCE_MODE_DELIBERATE:
        # Card order IS priority order, and the cards lead the payload so the
        # caller's first-occurrence dedup resolves a manual/canon duplicate in
        # the card's favour.
        manual_sent = list(manual[:budget])
        manual_dropped = list(manual[len(manual_sent):])
        room = max(0, budget - len(manual_sent))
        kept_canon = list(canon_urls[:room])
        ordered = [r.file_path for r in manual_sent] + kept_canon
        return ordered, manual_sent, manual_dropped

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


def _join_numbers(numbers: list[int]) -> str:
    """"1", "1 and 3", "1, 3 and 4" — read aloud rather than as a list."""
    if len(numbers) == 1:
        return str(numbers[0])
    return f"{', '.join(str(n) for n in numbers[:-1])} and {numbers[-1]}"


def _identity_lines(
    manual_sent: list[ResolvedReference], offset_base: int
) -> list[str]:
    """The identity-bucket sentences, plus the separation clause when needed.

    Grouping is what makes the buckets worth having: two cards marked
    CHARACTER_1 must read as two views of ONE person, not as two people. Stating
    that explicitly is the difference between a model reconciling two faces into
    one identity and it inventing a second character.
    """
    groups: dict[ReferenceRole, list[int]] = {}
    for offset, ref in enumerate(manual_sent):
        if ref.role in _PERSON_LABELS:
            groups.setdefault(ref.role, []).append(offset_base + offset + 1)

    lines: list[str] = []
    for role in (ReferenceRole.CHARACTER_1, ReferenceRole.CHARACTER_2):
        numbers = groups.get(role)
        if not numbers:
            continue
        label = _PERSON_LABELS[role]
        if len(numbers) == 1:
            lines.append(
                f"Reference image {numbers[0]} is {label}: reproduce that "
                "person's face and likeness exactly."
            )
        else:
            lines.append(
                f"Reference images {_join_numbers(numbers)} are all the same "
                f"person, {label}: treat them as one identity seen more than "
                "once and reproduce that person's face and likeness exactly."
            )

    # Only meaningful when BOTH buckets are present — there is nothing to keep
    # separate otherwise, and asserting a second person who was never supplied
    # would invite the model to invent one.
    if ReferenceRole.CHARACTER_1 in groups and ReferenceRole.CHARACTER_2 in groups:
        lines.append(
            _IDENTITY_SEPARATION_CLAUSE.format(
                a=_PERSON_LABELS[ReferenceRole.CHARACTER_1],
                b=_PERSON_LABELS[ReferenceRole.CHARACTER_2],
            )
        )
    return lines


def _feature_edit_items(
    manual_sent: list[ResolvedReference], offset_base: int, *, refining: bool
) -> list[str]:
    """One operative instruction per selected feature, in payload order.

    Repeated roles are GROUPED rather than listed twice: two Hair cards are two
    views of one hairstyle, and "replace the hair with the hair from image 2;
    replace the hair with the hair from image 3" is a contradiction rather than
    an instruction.

    Numbering follows the payload exactly as the per-image lines above do, so an
    item always names the image the provider actually received.
    """
    grouped: dict[ReferenceRole, list[int]] = {}
    for offset, ref in enumerate(manual_sent):
        if ref.role in _FEATURE_ROLES:
            grouped.setdefault(ref.role, []).append(offset_base + offset + 1)

    items: list[str] = []
    for role, numbers in grouped.items():
        noun = _FEATURE_EDIT_NOUNS[role]
        source = _ref_phrase(numbers)
        if refining:
            items.append(f"replace Person A's {noun} with the {noun} from {source}")
        else:
            items.append(f"take the {noun} from {source}")
    return items


def _construction_lines(
    manual_sent: list[ResolvedReference], offset_base: int
) -> list[str]:
    """The character-construction clauses for this reference set, or ``[]``.

    Derived entirely from which ROLES are present — never from how many cards
    there are, which card is which, or what order they arrive in. The board is
    four cards today and this function would behave identically at eight; the
    reference budget is an external constraint on how many references reach the
    provider, not part of the construction model.

    Returns nothing at all when no feature role is present. That is the
    load-bearing condition: it is what makes every board that predates the
    attribute roles compile to exactly the string it compiled to before, so a
    Character 1 + Pose canon card or a two-person scene is untouched by Phase 2.

    The two passes are distinguished by one question — is there already a person
    here? CHARACTER_1 present means the identity exists and the features are
    edits to it; CHARACTER_1 absent means there is no one yet and the features
    are the raw material for a new face. CHARACTER_2 deliberately does not
    trigger refinement: Person B is a second person in a scene, not the subject
    being built, and treating features as edits to them would silently retarget
    the whole pass.
    """
    roles = {ref.role for ref in manual_sent}
    if not roles & _FEATURE_ROLES:
        return []

    refining = ReferenceRole.CHARACTER_1 in roles
    items = _feature_edit_items(manual_sent, offset_base, refining=refining)

    lines = [_FEATURE_SOURCE_CLAUSE]
    lines.append(_refinement_clause(items) if refining else _construction_clause(items))

    # Only worth its length when something can actually contend with a feature.
    # A board of nothing but feature cards has no disagreement to resolve.
    if roles & _PRECEDENCE_CONTENDERS:
        lines.append(_ROLE_PRECEDENCE_CLAUSE)
    return lines


def build_reference_notes(
    manual_sent: list[ResolvedReference],
    *,
    canon_ref_count: int,
    canon_grounded: bool,
    refs_before_manual: Optional[int] = None,
    mode: str = REFERENCE_MODE_AUGMENT,
) -> str:
    """Prompt text describing the manual references, or ``""`` when there is none.

    The notes are APPENDED to the already-compiled prompt so canon compilation is
    untouched — ``canon_compiler.compile_canon_prompt`` produces exactly what it
    produced before, and this text rides behind it where image models weight
    trailing instructions well (the same placement the cover directives use).

    References are numbered by their position in the payload actually sent, so
    "Reference 4" names the fourth image the provider received. ``canon_ref_count``
    is that offset under the ``augment`` payload order (canon leads). Under
    ``deliberate`` the manual block leads, so the caller passes
    ``refs_before_manual=0``; the numbering must follow the payload, or the notes
    would describe the wrong images. When omitted it defaults to
    ``canon_ref_count``, which is the pre-existing behaviour.

    Roles left UNSPECIFIED contribute no line at all: the image is still sent,
    but the model is told nothing about it rather than being told something
    invented.

    ``mode`` selects the vocabulary, and the split is deliberate:

    * ``augment`` — the frozen four phrases, in payload order, exactly as
      /images has always sent them. An Admin Creator role reaching this path
      contributes no line, like UNSPECIFIED.
    * ``deliberate`` — identity buckets first (grouped, with the separation
      clause when both are present), then the per-image authority sentences,
      then the character-construction clauses when any attribute role is
      present. Identity leads because it is the strongest claim in the set and
      the one the rest are qualified against; the construction clauses trail
      because they instruct on the set as a whole and because image models
      weight trailing instructions well.
    """
    offset_base = canon_ref_count if refs_before_manual is None else refs_before_manual

    if normalise_reference_mode(mode) == REFERENCE_MODE_DELIBERATE:
        lines = _identity_lines(manual_sent, offset_base)
        for offset, ref in enumerate(manual_sent):
            if ref.role in _PERSON_LABELS:
                continue  # already covered by its identity group
            phrase = _DELIBERATE_ROLE_PHRASES.get(ref.role)
            if phrase is None:  # UNSPECIFIED — deliberately silent
                continue
            lines.append(f"Reference image {offset_base + offset + 1} is {phrase}.")
        lines.extend(_construction_lines(manual_sent, offset_base))
        if not lines:
            return ""
        # No canon-precedence clause: deliberate mode bypasses canon, so there
        # is no locked description for these references to defer to.
        return " " + "SUPPLIED REFERENCES — " + " ".join(lines)

    lines = []
    for offset, ref in enumerate(manual_sent):
        phrase = _ROLE_PHRASES.get(ref.role)
        if phrase is None:  # UNSPECIFIED — deliberately silent
            continue
        lines.append(f"Reference image {offset_base + offset + 1} is {phrase}.")
    if not lines:
        return ""
    parts = ["SUPPLIED REFERENCES — " + " ".join(lines)]
    if canon_grounded:
        parts.append(_CANON_PRECEDENCE_CLAUSE)
    return " " + " ".join(parts)
