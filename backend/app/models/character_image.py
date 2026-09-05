"""Character Image model — stores anchor and generated images."""
from datetime import datetime
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import relationship
import enum

from app.core.database import Base


class ImageKindEnum(str, enum.Enum):
    """Allowed image kinds."""
    ANCHOR_FRONT = "anchor_front"
    ANCHOR_THREE_QUARTER = "anchor_three_quarter"
    ANCHOR_TORSO = "anchor_torso"
    ANCHOR_FULL_BODY = "anchor_full_body"
    GENERATED = "generated"
    COVER = "cover"                           # character cover/banner image
    IDENTITY_FACE_REF = "identity_face_ref"  # tight face crop used as reference seed
    IDENTITY_SKETCH = "identity_sketch"       # pre-pack pencil/charcoal/dossier sketch anchor
    IDENTITY_BODY_FRONT = "identity_body_front"              # full-body front morphology reference
    IDENTITY_BODY_THREE_QUARTER = "identity_body_three_quarter"  # body 3/4 angle reference (legacy)
    IDENTITY_BODY_BACK = "identity_body_back"                # back view / back markings reference
    IDENTITY_TATTOO_LAYOUT = "identity_tattoo_layout"        # both arms/body markings reference (legacy)
    # Body Identity Pack v2 — canonical roles
    IDENTITY_BODY_LEFT_DETAIL = "identity_body_left_detail"      # left-side detail crop (high-fidelity marking ref)
    IDENTITY_BODY_RIGHT_DETAIL = "identity_body_right_detail"    # right-side detail crop
    IDENTITY_BODY_MAP = "identity_body_map"                      # canonical placement-sheet reference
    IDENTITY_FINAL_CHARACTER_CARD = "identity_final_character_card"  # cinematic presentation (support only)
    # Identity OS Beta — accessory canon refs
    ACCESSORY_DESIGN = "accessory_design"          # isolated accessory design sheet
    ACCESSORY_FIT = "accessory_fit"                # accessory on character (fit reference)
    # Identity OS Beta — scene images are NOT canon unless explicitly promoted
    SCENE_ONLY = "scene_only"                      # generated scene — not canon, not identity ref
    # Founder/seeder upload — an image the founder supplied from their own
    # device. It is ordinary creator media held against a character so it can be
    # picked as a generation reference. It is NOT canon, NOT an identity slot,
    # and NOT gallery or post material: deliberately absent from both
    # POST_ATTACHABLE_IMAGE_KINDS below and PUBLIC_GALLERY_KINDS in
    # app/schemas/character_image.py. Storing an image against a character has
    # never conferred authority, and this kind must not become the exception.
    UPLOADED = "uploaded"


#: Kinds a character may attach to a public post.
#:
#: An allowlist, not a denylist, so a newly added kind is private by default and
#: has to be opted in deliberately. Everything omitted here — identity sketches,
#: face and body references, anchors, accessory sheets, founder uploads — is
#: private production material that exists to drive generation, not to be
#: published.
#:
#: The client mirrors this list in ``frontend/src/components/attachImageKinds.ts``
#: for what it *offers*; this is what the server will *accept*, and it is the one
#: that matters.
POST_ATTACHABLE_IMAGE_KINDS = frozenset(
    {
        ImageKindEnum.GENERATED.value,
        ImageKindEnum.COVER.value,
        ImageKindEnum.SCENE_ONLY.value,
    }
)


#: Kinds that CANNOT be archived by their owner — the identity anchors.
#:
#: These are canon working references: the character's visual identity is
#: compiled from them, and removing one silently changes what every future
#: generation looks like. Resetting the character is the deliberate way to
#: discard them.
#:
#: Defined here rather than in a route module because Phase 4C gave archiving
#: two entrances — the character-scoped ``DELETE /characters/{id}/images/{id}``
#: and the account-scoped ``DELETE /users/me/character-images/{id}`` — and a
#: protection that exists on only one of them is not a protection.
PROTECTED_IMAGE_KINDS = frozenset(
    {
        ImageKindEnum.ANCHOR_FRONT,
        ImageKindEnum.ANCHOR_THREE_QUARTER,
        ImageKindEnum.ANCHOR_TORSO,
        ImageKindEnum.ANCHOR_FULL_BODY,
    }
)


#: Kinds a founder may hand-pick as a MANUAL generation reference.
#:
#: An allowlist for the same reason as the one above: a kind added later is
#: unselectable until someone opts it in deliberately.
#:
#: The identity/anchor/accessory kinds are excluded ON PURPOSE. Those are canon
#: production material, and which of them reaches a provider is decided by the
#: scene-aware reference router (``services/scene_router.route_canon_refs``)
#: from locked canon. Letting a founder hand-pick them here would create a
#: second, unaudited path for canon slots to reach the provider and would blur
#: exactly the canon-vs-manual boundary this feature has to keep sharp. Manual
#: references are ordinary media — uploads and previously generated output.
REFERENCE_SELECTABLE_IMAGE_KINDS = frozenset(
    {
        ImageKindEnum.UPLOADED.value,
        ImageKindEnum.GENERATED.value,
        ImageKindEnum.SCENE_ONLY.value,
        ImageKindEnum.COVER.value,
    }
)


class ImageStatusEnum(str, enum.Enum):
    """Image lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"


class ImageVisibilityEnum(str, enum.Enum):
    """Image visibility."""
    PRIVATE = "private"
    PUBLIC = "public"


# ── Safety state (Phase 4A) ───────────────────────────────────────────────────
#
# Plain strings, not a PostgreSQL enum, and not a Python enum bound to a column
# type. Adding a state later — ``review_required`` is the expected one — must be
# a CHECK edit, because this project has already been forced through
# ``ALTER TYPE ... ADD VALUE`` three times for ``imagekindenum`` and that
# operation cannot be rolled back.

#: No Ficshon decision exists for this asset. The default, and the state every
#: row created before Phase 4A carries. It says "nobody looked", which is a
#: different and more honest claim than "an old denylist did not object".
SAFETY_STATE_UNREVIEWED = "unreviewed"

#: An explicit moderation decision was made under a stated policy version, and
#: the asset may be shown beyond its owner once enforcement is switched on.
#:
#: NEVER written by inference. Not by a migration, not by a provenance
#: evaluation, not by "the denylist did not fire". Anything that writes this
#: must also record ``safety_policy_version``, ``safety_decided_at`` and
#: ``safety_decision_source`` — the CHECK constraint below enforces exactly that,
#: so the invariant survives code nobody remembers writing.
SAFETY_STATE_APPROVED = "approved"

#: An explicit decision that this asset must not be shown beyond its owner.
SAFETY_STATE_REJECTED = "rejected"

SAFETY_STATES = frozenset({
    SAFETY_STATE_UNREVIEWED,
    SAFETY_STATE_APPROVED,
    SAFETY_STATE_REJECTED,
})

#: A person made the call, through a moderation surface.
SAFETY_DECISION_SOURCE_HUMAN = "human"

#: A policy run made the call, with no human in the loop.
SAFETY_DECISION_SOURCE_AUTOMATED = "automated"

SAFETY_DECISION_SOURCES = frozenset({
    SAFETY_DECISION_SOURCE_HUMAN,
    SAFETY_DECISION_SOURCE_AUTOMATED,
})

#: Policy version meaning "never evaluated". A decided row must exceed it.
SAFETY_POLICY_VERSION_NONE = 0


class CharacterImage(Base):
    """Ficshon's canonical persisted-image asset (Phase 4A/4B1).

    Historically "an image associated with a character". It is becoming the one
    row that must exist for every persisted image, which is why the safety and
    storage columns below live here rather than in a parallel asset table: two
    tables describing the same bytes would drift, and one of them would end up
    being the one nobody checks.

    Phase 4B1 established the first half of that: ``user_id`` is now the
    authoritative owning account (see the column), and every ownership question
    reads it instead of joining ``Character``. ``character_id`` keeps its own,
    separate job — association — and stays NOT NULL until Phase 4C.

    Three things this row deliberately does NOT yet mean
    ----------------------------------------------------
    * **``storage_key`` is not populated.** Every row has NULL. ``file_path``
      remains the only storage identity in use, and every resolver still reads
      it. The backfill is a separate, reviewable script because deriving the key
      requires stripping an environment-specific URL prefix, which does not
      belong in a migration.
    * **``safety_state`` is not presentation authority.** No predicate reads it
      — not ``is_public_surface_safe``, ``is_public_post_image``,
      ``is_public_gallery_image``, nor any resolver. What may be shown is still
      decided exactly as it was before this column existed. Enforcement is a
      later, deliberate flip, and when it comes the existing denylist stays as
      the floor: an approval must never publish something the denylist rejects.
    * **``approved`` is never inferred.** It represents an explicit moderation
      decision under a stated policy version. Nothing derives it from provider,
      provenance or the absence of a denylist hit — that inference is the exact
      confusion these columns exist to end. The CHECK constraints make a
      decision without its policy version, timestamp and source unrepresentable,
      so the rule holds against code that has not been written yet.

    Lifecycle (``status``) and safety (``safety_state``) stay orthogonal.
    ``status`` answers "does the owner still have this?" — and ARCHIVED already
    IS the owner's delete, since ``DELETE /characters/{id}/images/{image_id}``
    sets it and no hard-delete route exists. ``safety_state`` answers "may
    anyone else see it?". The two genuinely disagree in practice: an ARCHIVED
    row is ineligible as a post attachment and perfectly eligible as an avatar.
    """

    __tablename__ = "character_images"

    id = Column(Integer, primary_key=True, index=True)
    #: The character this asset is ASSOCIATED with — optional (Phase 4C).
    #:
    #: Nullable with ``ON DELETE SET NULL``. Deleting a character is a statement
    #: about a character, not a demolition order for the person's images: the
    #: association disappears and the asset survives, keeping its owner, its
    #: safety decision, its provenance, its lineage and its storage pointer.
    #:
    #: Read this together with ``user_id`` below. They are the two halves of one
    #: rule and neither can stand in for the other::
    #:
    #:     user_id      = ownership   — mandatory, RESTRICT
    #:     character_id = association — optional,  SET NULL
    #:
    #: An asset with no character still belongs to somebody and still appears in
    #: their library. It is NOT reachable through any character-scoped route:
    #: every one of those filters ``character_id == <path id>``, and NULL never
    #: equals an integer, so a characterless asset cannot be claimed by another
    #: character merely because the same account owns both. There is
    #: deliberately no re-association route.
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The OWNING ACCOUNT for this asset (Phase 4B1).
    #:
    #: This is what "does this user own this image?" is answered with, and it is
    #: answered here rather than by joining ``Character`` — ownership of an
    #: asset is a fact about the asset, not about whichever character it is
    #: currently associated with. ``character_id`` continues to answer the
    #: separate question "which character is this associated with?", and the two
    #: must not be used interchangeably: a post authored by one character may
    #: still only attach that character's media, however many characters the
    #: account owns.
    #:
    #: It originally meant "which account generated this, for the weekly quota",
    #: and ``services/image_quota`` still counts it — that is LEGACY ACCOUNTING
    #: riding on the column, not the definition of it. Quota wants the
    #: generation requester; ownership is what this column now states. The two
    #: agree everywhere except admin generation on another account's character
    #: (``routes/adult_studio_admin`` deliberately stamps ``character.owner_id``),
    #: which is recorded technical debt: the requester already has a proper home
    #: in ``image_generation_jobs.user_id``, and quota should eventually read it
    #: there. Not changed here — 4B1 changes what the field MEANS, not what
    #: quota counts.
    #:
    #: NOT NULL with ``ON DELETE RESTRICT`` (Phase 4B2). Every asset has an
    #: owner, and an account cannot be deleted while it still owns assets — the
    #: database refuses, loudly, rather than picking a disposal policy nobody
    #: has decided. ``CASCADE`` would have destroyed rows and their safety
    #: decisions while leaving the objects in the bucket; ``SET NULL`` would
    #: have produced exactly the ownerless rows this column exists to prevent.
    #:
    #: THE WRITER RULE (Phase 4C). A writer that HAS a character writes
    #: ``character.owner_id``. A writer with NO character — account-level media,
    #: which ``character_id`` being optional now permits — writes the owning
    #: account directly. What a writer must never write is "whoever made the
    #: request": that is the requester, it is not always the owner (an admin may
    #: act on someone else's character), and it has its own home in
    #: ``image_generation_jobs.user_id`` / ``editor_jobs.user_id``.
    #:
    #: There is deliberately NO ``User.images`` relationship for this table. An
    #: ORM cascade would delete these rows itself and the FK would never be
    #: consulted, quietly reinstating the destruction ``RESTRICT`` was chosen to
    #: refuse. Ownership is read through this column; it is not navigated from
    #: the account.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # values_callable ensures SQLAlchemy stores the enum VALUE (e.g. "identity_sketch")
    # not the member NAME (e.g. "IDENTITY_SKETCH").  The PostgreSQL enum type is
    # recreated by migration b14_2 to use the same lowercase value strings.
    kind = Column(
        SQLEnum(ImageKindEnum, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    status = Column(
        SQLEnum(ImageStatusEnum, values_callable=lambda obj: [e.value for e in obj]),
        default=ImageStatusEnum.ACTIVE,
        nullable=False,
    )
    visibility = Column(
        SQLEnum(ImageVisibilityEnum, values_callable=lambda obj: [e.value for e in obj]),
        default=ImageVisibilityEnum.PRIVATE,
        nullable=False,
    )

    # Creator selection for the Character Home gallery (Character Home Step 6.5).
    #
    # Means ONE thing: "the creator has picked this image to be displayed in the
    # Character Home gallery." It is not a visibility level, not a permission,
    # and not a statement about the image's provenance or lifecycle.
    #
    # Deliberately a column of its own rather than a new state on ``visibility``.
    # ``visibility`` keeps whatever general meaning it was always intended to
    # have; overloading it with gallery curation would give one field two jobs
    # and make every future read of it ambiguous.
    #
    # Selection is one of THREE independent layers an image must clear to reach
    # an anonymous viewer's Character Home gallery, and it is the weakest of
    # them:
    #
    #   1. the Character Home is published    (character_home_is_publishable)
    #   2. the creator selected this image    (this column)
    #   3. Ficshon will expose this image     (is_public_gallery_image)
    #
    # Selecting an image can therefore never publish something the safety rule
    # withholds. Defaults false everywhere — existing rows by migration server
    # default, new rows by this Python-side default — so no image has ever been
    # selected without a creator saying so.
    public_gallery_enabled = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )

    provider = Column(String, nullable=True)       # e.g. "stub", "dall-e-3"
    prompt_summary = Column(String, nullable=True)  # short human-readable description
    seed = Column(String, nullable=True)            # reproducibility seed
    metadata_json = Column(JSON, nullable=True)     # arbitrary provider metadata
    file_path = Column(String, nullable=False)      # local path for MVP

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # ── Safety audit (Phase 4A) ──────────────────────────────────────────
    #
    # Read together, these five answer one question honestly six months from
    # now: did Ficshon actually review this, or did some historical code merely
    # fail to reject its provider?
    #
    # ``server_default`` is kept permanently on the two non-nullable columns,
    # rather than dropped after migration. An INSERT from a writing path nobody
    # remembered to update must land on "not reviewed" at the DDL level. That is
    # not hypothetical: thirteen modules currently call ``save_image()`` and
    # write no row at all, and when they are fixed their rows must default safe
    # without anyone having to remember.
    safety_state = Column(
        String(32),
        nullable=False,
        default=SAFETY_STATE_UNREVIEWED,
        server_default=SAFETY_STATE_UNREVIEWED,
        index=True,
    )

    #: Which version of the safety policy produced the decision; 0 = never
    #: evaluated. Exists so that when the policy changes in November, the rows
    #: approved under the old one can be found and re-reviewed — exactly those,
    #: and not everything. It is also what makes a future ``review_required``
    #: derivable (``approved AND version < CURRENT``) rather than stored.
    safety_policy_version = Column(
        Integer, nullable=False, default=SAFETY_POLICY_VERSION_NONE, server_default="0"
    )

    #: When the decision was made. Not derivable from anything else — this table
    #: has no ``updated_at`` — and it is what answers "which rows went through
    #: the auto-approver during the window it was broken?".
    safety_decided_at = Column(DateTime, nullable=True)

    #: The human account that decided, where one exists and still exists.
    #:
    #: ON DELETE SET NULL, so this going NULL does NOT mean "automated" — it may
    #: equally mean the moderator later deleted their account. Never infer the
    #: mechanism from this column; that is what ``safety_decision_source`` is
    #: for, and it is why the CHECK constraint requires the source rather than
    #: this FK on a decided row.
    safety_decided_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    #: How the decision was made — ``human`` or ``automated``. Survives the
    #: deletion of the deciding account, which is the whole reason it is a
    #: separate column from ``safety_decided_by``.
    safety_decision_source = Column(String(32), nullable=True)

    #: Short human-readable justification, chiefly for rejections. Deliberately
    #: NOT required by any constraint: forcing a reason onto automated decisions
    #: would produce placeholder text, which is worse than an honest NULL, and
    #: an automated decision's structured reasoning belongs with its policy
    #: version rather than in free text.
    safety_reason = Column(String(500), nullable=True)

    # ── Lineage and storage identity (Phase 4A) ──────────────────────────

    #: The image row this one was produced from — an avatar or cover crop, an
    #: Editor Studio transform, a future redraw.
    #:
    #: Answers the question the current schema cannot: "this crop was never
    #: vetted; what was it cropped FROM, and was that approved?" Nothing
    #: represents this today — a scan of all 1,425 rows carrying metadata found
    #: zero occurrences of ``source_image_id``, ``derived_from``,
    #: ``parent_image_id``, ``origin`` or ``crop``.
    #:
    #: Sufficient for one-to-one derivation, which is what actually causes
    #: today's unresolvable-avatar bug. A many-to-one redraw will need a link
    #: table later; this column then means "the primary source". SET NULL rather
    #: than CASCADE: deleting a source must not delete everything derived from
    #: it.
    #:
    #: Inert until the crop paths start writing rows at all. The column is the
    #: schema half of that fix, not the fix.
    derived_from_image_id = Column(
        Integer, ForeignKey("character_images.id", ondelete="SET NULL"), nullable=True
    )

    #: Bucket-relative object key — no scheme, no host, no bucket name.
    #:
    #: The eventual replacement for ``file_path`` as the row's storage identity,
    #: so that identity no longer depends on a permanent anonymous delivery URL
    #: (today 1,409 of 1,429 rows store a public R2 URL verbatim). NULL on every
    #: row until a deterministic backfill has run; ``file_path`` stays the sole
    #: working identity, unchanged, and every resolver still reads it.
    #:
    #: No unique index yet. All 1,429 current ``file_path`` values are already
    #: distinct and none is shared with ``user_images``, so uniqueness is
    #: achievable with no dedup work — but the index is created after the
    #: backfill has run and been checked for collisions, not before.
    storage_key = Column(String(512), nullable=True)

    # ── Relationships ────────────────────────────────────────────────────
    character = relationship("Character", back_populates="images")

    #: The asset this one was derived from, and the assets derived from it.
    #: ``remote_side`` names the "parent" end of the self-join.
    derived_from = relationship(
        "CharacterImage", remote_side=[id], backref="derivatives"
    )

    __table_args__ = (
        CheckConstraint(
            "safety_state IN ('unreviewed', 'approved', 'rejected')",
            name="ck_character_images_safety_state",
        ),
        CheckConstraint(
            "safety_decision_source IS NULL "
            "OR safety_decision_source IN ('human', 'automated')",
            name="ck_character_images_safety_decision_source",
        ),
        # An unreviewed row carries NO decision residue; a decided row carries a
        # COMPLETE decision. Nothing in between is representable, so a partial
        # write fails loudly at the database rather than producing a row that
        # claims a review nobody performed.
        #
        # ``safety_decided_by`` is constrained on the unreviewed side only. On
        # the decided side it must stay free: an automated decision has no human
        # to name, and the FK is ON DELETE SET NULL, so requiring it would make
        # that FK action illegal — deleting a moderator would leave their
        # decisions unsatisfiable. ``safety_decision_source`` is what survives
        # both cases, which is why it is the required field.
        CheckConstraint(
            "("
            " safety_state = 'unreviewed'"
            " AND safety_policy_version = 0"
            " AND safety_decided_at IS NULL"
            " AND safety_decision_source IS NULL"
            " AND safety_decided_by IS NULL"
            ") OR ("
            " safety_state IN ('approved', 'rejected')"
            " AND safety_policy_version > 0"
            " AND safety_decided_at IS NOT NULL"
            " AND safety_decision_source IS NOT NULL"
            ")",
            name="ck_character_images_safety_audit_coherent",
        ),
    )
