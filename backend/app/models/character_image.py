"""Character Image model — stores anchor and generated images."""
from datetime import datetime
from sqlalchemy import (
    Boolean,
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


class CharacterImage(Base):
    """An image associated with a character (anchor or generated)."""

    __tablename__ = "character_images"

    id = Column(Integer, primary_key=True, index=True)
    character_id = Column(
        Integer,
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # user_id tracks which user generated this image (used for weekly quota).
    # Nullable for legacy images created before quota enforcement.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # Relationships
    character = relationship("Character", back_populates="images")
