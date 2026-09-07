"""The closed-beta image-ingress boundary — who may supply image input to Ficshon.

THIS IS A PRODUCT BOUNDARY, NOT A TRUST OR AUTHORITY LEVEL, and the distinction
is the whole reason this module exists separately from
``app.core.entitlements``.

The product rule it encodes:

    An ordinary user brings the CHARACTER — name, bio, personality, history,
    relationships, writing. Ficshon creates the character's visual identity.
    An ordinary user does NOT supply image bytes, image URLs, or any other
    image input that Ficshon did not itself produce.

Admin and Seeder accounts are the deliberate exception: they are internal
founder tooling (Admin Creator, the founder upload, canon reference cards) and
they keep every image-input capability they have today.

WHY THIS IS NOT ``require_creator``. ``can_use_creator_tools`` admits any
account that owns a single character — which is precisely the outsider beta
persona this boundary exists to constrain. A guard written in terms of the
creator entitlement would therefore admit exactly the accounts it is meant to
refuse. The two questions are genuinely different:

    require_creator          — "is this a creator workspace you may open?"
    may_supply_image_input   — "may the bytes/URLs you are sending exist here?"

WHY IT IS NOT ``require_founder`` EITHER, despite resolving to the same
accounts today. ``require_founder`` answers a question about ACCOUNT AUTHORITY
("is this founder tooling?"). This answers a question about PRODUCT SHAPE
("does the closed beta accept user-supplied imagery?"). They coincide right
now because the only accounts that should be supplying reference images are the
founder accounts — but they will diverge the moment the beta opens image input
to a paid tier, or narrows it away from Seeder. When that happens it is changed
HERE, in one predicate, and no authority semantics move with it.

The frontend has no mirror of this yet — hiding the controls is a separate
increment. That is deliberate and safe in this order: the server refusing is
what makes the boundary real, and a visible control that 403s is a worse UI
than a hidden one but not a weaker boundary.

GUARDED INGRESS INVENTORY (Beta Boundary 1). Kept here, beside the predicate,
because a boundary nobody can enumerate is a boundary nobody can audit. Every
route below is one an ORDINARY OWNER can reach; each names the mechanism, since
the two are not interchangeable.

  Role guard — ``guard_supplied_image_fields`` / ``may_supply_image_input``:
    PATCH /characters/{id}/identity-canon/face        5 face slot urls
    PATCH /characters/{id}/identity-canon/body       10 body slot urls
    POST  /characters/{id}/identity-canon/body/marks  reference_image_url,
                                                      detail_crop_url
    POST  /characters/{id}/identity-canon/accessories design_anchor_image_url,
                                                      fit_anchor_image_url
    POST  /characters/{id}/identity-accessory         anchor_image_url  (v1
                                                      store; guarded even though
                                                      nothing loads it as
                                                      conditioning today)
    POST  /editor/generate                            multipart ``images``

  Asset resolution — every role, not a founder check:
    POST  /characters/{id}/identity-evolution/candidate-slot   image_url

Guarded FIELD-BY-FIELD, never route-by-route: each of those endpoints also
carries written identity (a face description, a build, a mark's description, an
accessory's visual rules) that the character's owner must keep editing. The
GENERATED route to several of the same columns is untouched — an owner still
generates a canon pack, an accessory design anchor and a fit anchor, all of
which write a url Ficshon produced. Supplying one is what closes.

Deliberately NOT in scope here, and each recorded rather than forgotten: the
display-only url fields (``Character.avatar_url`` / ``cover_url`` /
``portrait_url``, ``User.avatar_url`` / ``cover_url``, ``Realm.banner_url``,
``StorySpace.cover_url``), ``load_image_bytes`` hardening, and the
canon-urls-to-asset-ids redesign that would make this structural rather than
role-scoped.
"""
from typing import Any, Iterable, Optional

from fastapi import HTTPException, status

from app.core.entitlements import is_founder_account
from app.models.user import User


#: The refusal a caller sees when they supply image input the beta does not
#: accept from them. Defined once so every guarded route says the same thing —
#: three routes inventing three phrasings for one product rule is how a rule
#: stops reading as a rule and starts reading as a bug.
#:
#: Worded as a statement about the PRODUCT, not about the account. "You are not
#: allowed" invites the user to go looking for the permission; "Ficshon creates
#: the imagery" tells them what the product actually is, which is the true
#: answer and also the one that does not sound like a defect.
USER_SUPPLIED_IMAGE_INPUT_CLOSED_MESSAGE = (
    "Ficshon creates your character's imagery. Supplying your own images or "
    "image links isn't part of the beta — describe the character in words and "
    "generate the visual identity instead."
)


def may_supply_image_input(user: Optional[User]) -> bool:
    """May this account supply image input Ficshon did not create?

    THE single predicate for the closed-beta image boundary. Covers uploaded
    bytes, externally-hosted image URLs, and any other channel by which an
    account can hand Ficshon imagery it did not produce.

    For the closed beta the answer is :func:`is_founder_account` — admin OR
    seeder — composed rather than restated, so this cannot drift from the
    definition the founder tooling already uses. Composing it also means the
    Seeder decision is made in exactly one place: if Seeder is later brought
    under the ordinary restriction, this body becomes ``user_is_admin(user)``
    and every guarded route follows without being touched.

    Says nothing about ownership, entitlement or authentication. The routes
    check those already; this answers only "may these bytes/this URL exist
    here at all".
    """
    if user is None:
        return False
    return is_founder_account(user)


def reject_user_supplied_image_input(fields: Iterable[str] = ()) -> None:
    """Raise the uniform 403 for a refused image input.

    Always ``NoReturn`` in practice; typed as ``None`` so callers can write it
    as a plain statement. *fields* names the offending request fields and is
    logged into the detail payload so a founder debugging a client sees WHICH
    field tripped the rule, not merely that something did.

    403 rather than 422: the payload is well-formed and the caller owns the
    character. What is refused is the account's ability to supply this KIND of
    input — an authorization-shaped answer, and the same status the founder
    tools already return for "this is a founder tool".
    """
    named = sorted({f for f in fields if f})
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "user_supplied_image_input_closed",
            "detail": USER_SUPPLIED_IMAGE_INPUT_CLOSED_MESSAGE,
            "fields": named,
        },
    )


def supplied_image_fields(payload: Any, fields: Iterable[str]) -> list[str]:
    """Which of *fields* this request actually supplies an image value for.

    Reads ``model_fields_set`` — what the CLIENT sent — rather than the dumped
    dict, for two reasons that both matter:

    * it is alias-proof. ``model_dump()`` keys follow the serialisation alias
      and ``model_dump(by_alias=True)`` follows another; ``model_fields_set``
      always holds the canonical field names, so a schema that grows an alias
      later cannot slip a field past a name-matched guard.
    * it does not depend on the route's own dump flags. Each guarded route
      dumps differently (``exclude_none``, ``exclude_unset``), and a guard that
      re-derived the set would have to mirror each one correctly forever.

    ``None`` is not a supplied image. The writers all drop None (they dump with
    ``exclude_none=True``), so an explicit ``"face_front_image_url": null``
    writes nothing and there is nothing to refuse — refusing it would reject a
    request that changes no image at all. Everything else counts, INCLUDING the
    empty string: ``""`` is a value the writer would store, and "supplied
    something falsy" must not be a way through.
    """
    supplied = getattr(payload, "model_fields_set", None)
    if supplied is None:  # not a pydantic model — nothing declared, nothing set
        return []
    return [
        name
        for name in fields
        if name in supplied and getattr(payload, name, None) is not None
    ]


def guard_supplied_image_fields(
    user: Optional[User], payload: Any, fields: Iterable[str]
) -> None:
    """Refuse *payload* if it supplies image fields this account may not supply.

    The composition every guarded canon route uses, so the ordering — check
    what was supplied, then check who is asking — is written once. A founder
    passes untouched; a non-founder who supplied none of *fields* passes
    untouched, which is what keeps ordinary TEXT canon edits working through
    the very same endpoints.
    """
    offending = supplied_image_fields(payload, fields)
    if not offending:
        return
    if may_supply_image_input(user):
        return
    reject_user_supplied_image_input(offending)
