"""Character Image schemas."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, computed_field

from app.models.character_image import (
    POST_ATTACHABLE_IMAGE_KINDS,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)


class CharacterImageCreate(BaseModel):
    """Schema for recording a new character image."""
    kind: ImageKindEnum
    file_path: str
    status: ImageStatusEnum = ImageStatusEnum.ACTIVE
    visibility: ImageVisibilityEnum = ImageVisibilityEnum.PRIVATE
    provider: Optional[str] = None
    prompt_summary: Optional[str] = None
    seed: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None


#: Kinds that belong in a character's PUBLIC gallery.
#:
#: The ``visibility`` column is NOT usable as the gallery signal: it defaults to
#: PRIVATE and nothing in the codebase has ever written PUBLIC, so every stored
#: image is 'private'. Filtering on it would empty every gallery in production.
#: Kind is therefore the safest existing definition — it distinguishes finished,
#: shareable output from the identity/anchor working references used to build a
#: character. Documented limitation, not invented behaviour.
#:
#: ``UPLOADED`` (founder/seeder device uploads) is deliberately NOT here. An
#: uploaded image is a private working reference: the founder supplied it to
#: steer generation, not to publish it, and Ficshon has no provenance for it. It
#: is likewise absent from ``POST_ATTACHABLE_IMAGE_KINDS``. Adding it to either
#: list is a product decision that must be taken explicitly, never as a
#: side effect of adding the upload feature.
PUBLIC_GALLERY_KINDS = frozenset({
    ImageKindEnum.GENERATED,
    ImageKindEnum.COVER,
    ImageKindEnum.SCENE_ONLY,
})


class CharacterImagePublic(BaseModel):
    """A character image as seen by the PUBLIC — Wanderers, other owners,
    anonymous visitors.

    Deliberately narrow. Everything a viewer has no business seeing is absent
    from the schema rather than merely unset, so it cannot leak by accident:
    ``prompt_summary``, ``provider``, ``seed``, ``metadata_json`` (raw provider
    payloads, costs, storage internals), ``user_id`` (account identity),
    ``status`` and ``visibility``.
    """
    id: int
    character_id: int
    kind: ImageKindEnum
    created_at: datetime
    url: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_image(cls, image) -> "CharacterImagePublic":
        """Build from a CharacterImage ORM row, deriving the servable URL."""
        return cls(
            id=image.id,
            character_id=image.character_id,
            kind=image.kind,
            created_at=image.created_at,
            url=_file_path_to_url(image.file_path),
        )


def _file_path_to_url(file_path: str) -> str:
    """Derive a servable URL from a stored file_path.

    Shared by CharacterImageRead.url and CharacterImagePublic so the two can
    never disagree about how an image is addressed.
    """
    if file_path.startswith(("http://", "https://")):
        return file_path
    path = file_path.lstrip("/")
    if not path.startswith("static/"):
        return f"/static/{path}"
    return f"/{path}"


#: Providers whose output is never public, whatever kind it carries.
#:
#: ``replicate_nsfw`` is the Adult Studio image-to-image backend. ``self_hosted``
#: is the Editor Studio RunPod transform pod, which applies no content filter.
#: This is a STRUCTURAL signal — a column the writing path sets alongside the
#: metadata — so it still holds if a metadata payload is rewritten or partial.
#: It is defence in depth, not the primary Editor Studio identifier: the dev
#: audit found the one editor row that actually reached the public gallery came
#: from ``gpt-image``, not ``self_hosted``. ``editor_generated`` below is what
#: catches that one.
NON_PUBLIC_IMAGE_PROVIDERS = frozenset({"replicate_nsfw", "self_hosted"})

#: Metadata flags marking output that is ineligible for public surfaces.
#:
#: ``adult_studio`` — Adult Studio output. Permanently ineligible: Ficshon's
#: initial public product carries no explicit sexual imagery.
#: ``editor_generated`` — Editor Studio output, across all three writing paths
#: (the sync route, the async RunPod driver, and the E1 validation script) and
#: every provider it uses. A launch-safety exclusion, fail-closed pending an
#: explicit review of Editor Studio output — not a permanent judgement on it.
NON_PUBLIC_METADATA_FLAGS = ("adult_studio", "editor_generated")

#: User-facing explanation when a write is refused by the safety rule. Defined
#: beside the predicate so the three avatar/cover routes cannot drift apart on
#: how they describe the same refusal.
PUBLIC_SURFACE_UNSAFE_MESSAGE = (
    "This image was produced in a studio whose output cannot be shown on a "
    "public surface. It remains in your library."
)


def is_public_surface_safe(image) -> bool:
    """True when *image* may be presented on an ANONYMOUS/PUBLIC surface.

    The cross-surface launch-safety rule, and only that. It deliberately knows
    nothing about galleries — no kind allowlist, no status, no ``is_temp`` —
    because those are gallery semantics, and a character's avatar, cover and
    post attachments answer to different rules about kind and lifecycle while
    answering to the SAME rule about studio provenance.

    Three presentation paths reach an anonymous viewer — the public gallery,
    the character's avatar/cover, and a post's attached image. Before this
    existed each was free to invent its own denylist, and two of them had
    simply never been given one. This is the one definition they share.

    Duck-typed on ``provider`` and ``metadata_json``, so it holds for both
    ``CharacterImage`` and ``UserImage`` rows; the avatar and cover routes
    accept either.

    Excludes, in three redundant layers so a writing path that sets only one
    signal is still caught:

    * ``provider`` column in :data:`NON_PUBLIC_IMAGE_PROVIDERS`;
    * ``provider`` recorded inside the metadata payload, same set;
    * any of :data:`NON_PUBLIC_METADATA_FLAGS` present and truthy.

    Fail-closed throughout: any truthy marker excludes, so a row whose marker
    is present but malformed is withheld rather than published on the strength
    of a value nobody can parse.

    Says nothing about ownership. A founder keeps full access to their own
    material through the owner and admin paths, which never consult this.
    """
    metadata = getattr(image, "metadata_json", None) or {}

    if (getattr(image, "provider", None) or "") in NON_PUBLIC_IMAGE_PROVIDERS:
        return False
    if (metadata.get("provider") or "") in NON_PUBLIC_IMAGE_PROVIDERS:
        return False
    if any(metadata.get(flag) for flag in NON_PUBLIC_METADATA_FLAGS):
        return False

    return True


def is_public_gallery_image(image) -> bool:
    """True when *image* belongs in the character's public gallery.

    Requires an allowlisted kind, ACTIVE status, that the image is not a
    temporary pack preview that was never accepted, and that it carries no
    launch-ineligible provider or studio marker.

    The studio exclusions are a DENYLIST layered under the kind allowlist, and
    they are deliberately redundant: provider column, provider recorded inside
    the metadata payload, and per-studio metadata flags are three independent
    signals, any one of which is enough to exclude. A path that sets only one
    of them is still caught.

    They read as fail-closed: any truthy value excludes, matching how ``is_temp``
    has always been read here. A row whose marker is present but malformed is
    withheld from the public rather than published on the strength of a value
    nobody can parse.

    This is the single chokepoint for public gallery eligibility — route code
    must call it rather than filtering in parallel, or the two rules drift.
    Owner and admin views do NOT pass through here: a founder keeps full access
    to their own material, which this function has no opinion about.
    """
    if image.kind not in PUBLIC_GALLERY_KINDS:
        return False
    if image.status != ImageStatusEnum.ACTIVE:
        return False
    if (image.metadata_json or {}).get("is_temp", False):
        return False

    return is_public_surface_safe(image)


def is_selected_for_public_gallery(image) -> bool:
    """True when the CREATOR has selected *image* for the Character Home gallery.

    The curation layer, and only that. It asks one question — did a creator
    pick this image to be shown on the Character Home? — and knows nothing
    about provenance, kind, status or whether the Home is published at all.

    Read through ``getattr`` with a false default so a row predating the column,
    or any duck-typed stand-in that never had it, reads as UNSELECTED. Selection
    fails closed: an image is shown publicly because someone chose it, never
    because a value was missing.
    """
    return bool(getattr(image, "public_gallery_enabled", False))


def is_public_gallery_visible(image) -> bool:
    """True when *image* may be shown in the ANONYMOUS Character Home gallery.

    The conjunction of the two per-image layers, kept separate on purpose:

    * :func:`is_selected_for_public_gallery` — the creator chose to show it;
    * :func:`is_public_gallery_image` — Ficshon is willing to expose it.

    The third layer, whether the Character Home is published at all, is
    ``character_home_is_publishable`` and belongs to the character, not the
    image, so the route applies it before reaching here.

    The ordering is the point. Creator selection is checked FIRST and the safety
    rule still runs afterwards, so selecting an image can never publish
    something the safety rule withholds — a creator curates *within* what
    Ficshon allows, never around it. That is also why the selection check lives
    here rather than inside :func:`is_public_gallery_image`: that predicate is
    Ficshon's own eligibility rule, it governs surfaces that have no notion of
    gallery curation, and folding a creator-controlled flag into it would make
    a safety chokepoint answerable to creator input.

    Owner and admin views do NOT pass through here. A creator sees their whole
    library whatever they have selected, exactly as before.
    """
    return is_selected_for_public_gallery(image) and is_public_gallery_image(image)


def is_public_post_image(image) -> bool:
    """True when *image* may be shown as a post attachment to an ANONYMOUS viewer.

    The third composition of :func:`is_public_surface_safe`, alongside
    :func:`is_public_gallery_image`. Same shared provenance rule, different
    lifecycle rules, because a post attachment is not a gallery piece:

    * the shared studio-provenance exclusions;
    * the row is still ACTIVE. Archiving IS the owner's delete — ``DELETE
      /characters/{id}/images/{image_id}`` flips the status rather than
      removing the row — and a post's ``image_url`` is a denormalised string
      that keeps pointing at it afterwards. Without this check, deleting an
      image would leave it published on every post that ever carried it. Read
      duck-typed so it holds for ``UserImage`` too, whose ``status`` is the
      plain string ``"active"`` that ``ImageStatusEnum.ACTIVE`` compares equal
      to;
    * for a ``CharacterImage``, the kind is still in
      :data:`POST_ATTACHABLE_IMAGE_KINDS`. This is not a new policy: it is the
      exact allowlist ``POST /realms/{id}/posts`` enforced when the image was
      attached, re-asserted at read time because ``kind`` is mutable — the
      identity-pack accept path rewrites it — so a row that was attachable when
      the post was written may since have become private production material.

    The kind allowlist is deliberately NOT applied to ``UserImage``: the
    attachment path never imposed one there (account images are checked for
    ownership alone), so requiring one on read would suppress attachments that
    were legitimately made.

    Nothing here belongs in ``is_public_surface_safe`` itself. That predicate is
    about where an image CAME FROM, and stays free of lifecycle and kind so the
    avatar, cover, gallery and post surfaces can each answer those differently
    while sharing one provenance rule.
    """
    if getattr(image, "status", None) != ImageStatusEnum.ACTIVE:
        return False
    if isinstance(image, CharacterImage) and image.kind not in POST_ATTACHABLE_IMAGE_KINDS:
        return False

    return is_public_surface_safe(image)


class PublicGallerySelectionRequest(BaseModel):
    """Creator selection of one image for the Character Home gallery.

    A single field on purpose. This endpoint changes the creator's gallery
    choice and nothing else — never kind, status, visibility or provenance —
    so there is nothing else to send.
    """
    enabled: bool


class CharacterImageRead(BaseModel):
    """Schema returned when reading a character image."""
    id: int
    character_id: int
    kind: ImageKindEnum
    status: ImageStatusEnum
    visibility: ImageVisibilityEnum
    #: Creator selection for the Character Home gallery. Present in the OWNER's
    #: view (this schema) because it is the creator's own choice and the Media
    #: UI has to render its state; deliberately absent from
    #: ``CharacterImagePublic``, which describes an image already shown to a
    #: visitor and to whom the curation state is not information.
    public_gallery_enabled: bool = False
    provider: Optional[str] = None
    prompt_summary: Optional[str] = None
    seed: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None
    file_path: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        """Derive a servable URL from the stored file_path."""
        return _file_path_to_url(self.file_path)

    model_config = {"from_attributes": True}
