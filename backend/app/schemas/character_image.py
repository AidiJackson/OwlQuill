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
    #: Optional since Phase 4C — an asset may outlive its character. A
    #: characterless asset cannot actually reach this schema (the public gallery
    #: route is character-scoped and 404s once the character is gone), but the
    #: type states the column's shape rather than an assumption about which rows
    #: happen to arrive here.
    character_id: Optional[int] = None
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


def is_lifecycle_active(image) -> bool:
    """True when *image* has not been WITHDRAWN by its owner.

    The lifecycle half of public eligibility, and only that half. It asks one
    question — is this row still ACTIVE? — and knows nothing about where the
    bytes came from, which is :func:`is_public_surface_safe`'s question and
    stays there.

    Archiving IS the owner's delete: ``DELETE /characters/{id}/images/{image_id}``
    and ``DELETE /users/me/character-images/{image_id}`` flip ``status`` rather than
    removing the row, because provenance, ownership and lineage have to survive
    the deletion of the picture.

    Read duck-typed, exactly as :func:`is_public_post_image` reads it, so it
    holds for ``UserImage`` too — that model's ``status`` is the plain string
    ``"active"``, which ``ImageStatusEnum.ACTIVE`` compares equal to because the
    enum is a ``str`` subclass.

    Fail-closed on a row that has no ``status`` at all: ``getattr`` defaults to
    ``None``, which is not ACTIVE, so a duck-typed stand-in without the column
    is treated as withdrawn rather than published on a missing value.
    """
    return getattr(image, "status", None) == ImageStatusEnum.ACTIVE


def is_public_media(image) -> bool:
    """True when *image* may back a governed avatar/cover on a SHARED surface.

    The composition ``resolve_public_media_url`` applies, and the reason the two
    halves below are separate functions rather than one widened predicate:

    * :func:`is_public_surface_safe` — WHERE THE BYTES CAME FROM. Studio
      provenance, shared with the gallery and the post-attachment rules. It is
      deliberately free of lifecycle and kind, and must stay that way: three
      surfaces share it while answering lifecycle differently.
    * :func:`is_lifecycle_active` — WHETHER THE OWNER STILL PUBLISHES IT.

    A DELIBERATE PRODUCT REVERSAL, taken for beta. Until now ARCHIVED was read
    as a POST-ATTACHMENT rule only: an archived row was withheld from a post's
    ``image_url`` and still eligible as a character's avatar, and
    ``test_character_avatar_safety_on_shared_surfaces`` pinned exactly that
    divergence on purpose. The rule it pinned has changed. ARCHIVED now means
    WITHDRAWN FROM FICSHON — the owner pressed delete, and an owner who deletes
    an image does not expect to keep finding it on the Character Home, the OG
    card, the directory, the search results, a feed avatar, a comment or a
    messaging summary. One lifecycle answer for every shared surface is what
    that promise requires, so the avatar surface is brought into line with the
    attachment surface rather than the other way round.

    WHAT THIS DOES NOT CLAIM. It is APPLICATION-LAYER withdrawal. Ficshon stops
    projecting the url; it does not revoke bytes. An anonymous party already
    holding the direct public R2/static url can still fetch the object, and
    nothing here changes that. Accepted beta storage debt, stated rather than
    papered over.

    Says nothing about ownership. The owner's own library, and every owner and
    admin path, never consult this.

    Not a widening of :func:`is_public_surface_safe`. That predicate represents
    provenance, several surfaces share it, and folding lifecycle into it would
    give the gallery and post rules a second, invisible status check while
    destroying the one distinction that lets each surface answer differently.
    """
    return is_lifecycle_active(image) and is_public_surface_safe(image)


#: Kinds a ``CharacterImage`` may become a character's AVATAR.
#:
#: Phase 4D3-2. Until 4D3-3 the canon writers created no rows, so "which images
#: can be an avatar?" was answered by accident: an image was selectable if it
#: existed, and canon images did not. Giving canon assets rows removes that
#: accident, and rowlessness must not be what a policy rests on — so the rule is
#: stated here before the rows exist.
#:
#: An allowlist, like every other kind list in this codebase, so a kind added
#: later is ineligible until somebody opts it in deliberately.
#:
#: ``UPLOADED`` is here and deliberately NOT in :data:`PUBLIC_GALLERY_KINDS`.
#: The asymmetry is real and intended: a founder's own upload is not gallery
#: material Ficshon vouches for, but choosing it as the character's face is an
#: explicit act, and it is how upload-your-own-avatar has always worked.
#: Removing it would break that flow, which is a product decision and not this
#: phase's to take.
#:
#: Everything canon EXCEPT the four portrait-framed kinds is absent: body views,
#: poses, torsos, the body map, mark references and detail crops, accessory
#: sheets and the 90-degree face profile are working references, not faces.
AVATAR_ELIGIBLE_KINDS = frozenset({
    ImageKindEnum.GENERATED,
    ImageKindEnum.SCENE_ONLY,
    ImageKindEnum.UPLOADED,
    ImageKindEnum.IDENTITY_FACE_REF,
    # Legacy identity-pack anchors. Retained for compatibility: characters
    # locked before the v2 pack existed have these and nothing else.
    ImageKindEnum.ANCHOR_FRONT,
    ImageKindEnum.ANCHOR_THREE_QUARTER,
    # v2 canon face cards (Phase 4D3-3) — the portrait-framed ones. The 90°
    # profile is deliberately absent: it is a reference, not a face card.
    ImageKindEnum.IDENTITY_FACE_FRONT,
    ImageKindEnum.IDENTITY_FACE_LEFT_3Q,
    ImageKindEnum.IDENTITY_FACE_RIGHT_3Q,
    ImageKindEnum.IDENTITY_FACE_EXPRESSION,
    ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
})

#: Kinds a ``CharacterImage`` may become a character's COVER.
#:
#: A SEPARATE list from :data:`AVATAR_ELIGIBLE_KINDS`, not a reference to it.
#: The two surfaces ask different questions — an avatar is a face at thumbnail
#: size, a cover is a banner — and the moment one list serves both, widening it
#: for one surface silently widens the other. That is the whole reason there are
#: two of them, so they must not be merged, aliased or derived from each other.
#:
#: Face anchors are absent ON PURPOSE even though they are avatar-eligible: a
#: head crop makes a poor hero image, and nothing in the product asks for one.
#: ``IDENTITY_FINAL_CHARACTER_CARD`` is the one canon kind here — a cinematic
#: full-character image is exactly what a banner wants.
COVER_ELIGIBLE_KINDS = frozenset({
    ImageKindEnum.GENERATED,
    ImageKindEnum.COVER,
    ImageKindEnum.SCENE_ONLY,
    ImageKindEnum.UPLOADED,
    ImageKindEnum.IDENTITY_FINAL_CHARACTER_CARD,
})

#: Refusal text when an image's KIND (not its provenance) bars the surface.
#: Distinct from :data:`PUBLIC_SURFACE_UNSAFE_MESSAGE` because the two refusals
#: mean different things to a founder: one says "this image cannot be published
#: at all", the other says "this image is fine, but it is not a face".
AVATAR_KIND_INELIGIBLE_MESSAGE = (
    "This kind of image cannot be used as a character avatar. It remains in "
    "your library."
)
COVER_KIND_INELIGIBLE_MESSAGE = (
    "This kind of image cannot be used as a character cover. It remains in "
    "your library."
)


def is_avatar_eligible(image) -> bool:
    """True when *image* may become a character's avatar.

    Two independent questions, both of which must pass:

    * WHERE DID IT COME FROM — :func:`is_public_surface_safe`, which every
      anonymous-facing surface shares. Unchanged by this phase.
    * WHAT IS IT — :data:`AVATAR_ELIGIBLE_KINDS`, new in Phase 4D3-2.

    THE KIND TEST APPLIES TO ``CharacterImage`` ONLY, and the branch is written
    out rather than folded into a boolean expression because a reader has to see
    which model is exempt and why. ``UserImage.kind`` is a free-form ``String``
    (``"profile_cover"``), not an :class:`ImageKindEnum`, so putting it through
    this allowlist would refuse every account image — a workflow that predates
    this policy and has nothing to do with canon. The same carve-out, for the
    same reason, is made by :func:`is_public_post_image` for its kind allowlist.

    Says nothing about ownership, status or ``is_temp``: the routes check those
    already and they are not this predicate's question.
    """
    if not is_public_surface_safe(image):
        return False
    if isinstance(image, CharacterImage):
        return image.kind in AVATAR_ELIGIBLE_KINDS
    return True


def is_cover_eligible(image) -> bool:
    """True when *image* may become a character's cover.

    The same two questions as :func:`is_avatar_eligible`, against
    :data:`COVER_ELIGIBLE_KINDS`. Deliberately a separate function rather than a
    parameterised one: a shared implementation taking an allowlist argument
    invites a caller to pass the wrong list, and these two surfaces are exactly
    the pair that must not be confused. The cover is the character's most public
    image of all.
    """
    if not is_public_surface_safe(image):
        return False
    if isinstance(image, CharacterImage):
        return image.kind in COVER_ELIGIBLE_KINDS
    return True


def derived_provenance(source) -> tuple[Optional[str], dict[str, Any]]:
    """Provenance a LOCALLY DERIVED asset must carry from *source*.

    Returns ``(provider, metadata_fragment)`` to merge into the derived asset's
    own provider and metadata.

    WHY THIS EXISTS. Cropping is a byte transformation, not an act of
    provenance. Before Phase 4D2 the avatar crops wrote no row at all, so a crop
    of an Adult Studio or Editor Studio image was suppressed on every shared
    surface by ``character_home_media.resolve_public_media_url`` — not because
    it had been judged, but because nothing could be found to judge. 4D2 gives
    those crops a real row, and a row that resolves is a row the predicate will
    answer for. A crop written with ``provider=None`` and fresh metadata would
    therefore answer True: an unsafe source would become publicly presentable by
    the act of being cropped, and — because the crop is itself a
    ``CharacterImage`` its owner can select — usable as the source for a
    character avatar that :func:`is_public_surface_safe` had refused minutes
    earlier. That laundering path is created BY the migration; it did not exist
    while the crops were rowless.

    So a derived asset inherits exactly the three signals
    :func:`is_public_surface_safe` reads, and nothing else:

    * the ``provider`` column — the bytes ARE that provider's output, cropped;
    * the provider recorded inside the source's metadata payload;
    * any truthy :data:`NON_PUBLIC_METADATA_FLAGS`.

    It does NOT inherit ``safety_state``. An approval or a rejection is a
    decision taken about specific bytes under a stated policy version, and
    copying one onto different bytes would be a fabricated decision — the exact
    thing ``SAFETY_STATE_APPROVED`` documents must never be written by
    inference. This function moves EVIDENCE, which is inheritable; the decision
    stays Phase 4E's.

    Conservative in one direction only: it can make a derived asset ineligible
    and can never make one eligible, because every marker it copies excludes.

    Duck-typed like the predicate itself, so a ``UserImage`` source works too.
    """
    source_provider = getattr(source, "provider", None) or None
    source_metadata = getattr(source, "metadata_json", None) or {}

    fragment: dict[str, Any] = {}
    metadata_provider = source_metadata.get("provider") or None
    if metadata_provider:
        fragment["provider"] = metadata_provider
    for flag in NON_PUBLIC_METADATA_FLAGS:
        if source_metadata.get(flag):
            fragment[flag] = True
    return source_provider, fragment


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
    #: Optional since Phase 4C. ``null`` means the asset has no character — it
    #: is still owned, still in its owner's library, and every character-scoped
    #: action on it is unavailable. Clients must not build a character URL from
    #: this without checking it first.
    character_id: Optional[int] = None
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
