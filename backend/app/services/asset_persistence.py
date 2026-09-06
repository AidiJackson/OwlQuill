"""The canonical way to persist a durable image asset (Phase 4D1).

ONE ENTRANCE
------------
:func:`persist_image_asset` writes bytes and creates the ``CharacterImage`` row
in one call. Splitting those two steps is what produced every rowless object in
the bucket: 98 identity-canon images, every account avatar, five character
avatars — bytes somebody is accountable for, with no owner, no safety state and
no lifecycle, invisible to the library and withheld from every shared surface
because no row could be found to judge.

WHY OWNERSHIP IS A PRINCIPAL AND NOT AN INT
-------------------------------------------
``owner_id: int`` accepts ``current_user.id`` exactly as readily as
``character.owner_id``, and at the call site the two are indistinguishable. That
ambiguity is not hypothetical here: Phase 4B1 found ``user_id`` had drifted to
mean "whoever generated this", 4B2 corrected two writers, 4C corrected five
more. :class:`OwnedBy` makes the two cases syntactically different, so naming
the wrong one is visible in review rather than merely wrong at runtime.

There is deliberately no constructor taking a bare id, and none taking a
requester. Requester identity belongs to ``image_generation_jobs.user_id`` and
``editor_jobs.user_id``, which Phase 4C made survive character deletion for
exactly that reason.

WHAT THIS FUNCTION WILL NOT LET YOU DO
--------------------------------------
* create an asset with no owner — there is no call shape that omits one;
* create an ``approved`` or ``rejected`` asset — no parameter reaches
  ``safety_state``. Provenance is evidence; eligibility is a decision, and
  nothing has been decided (there is no policy version 1 yet);
* commit. The row joins the caller's transaction — see
  :func:`_register_pending_object`.

DERIVED ASSETS ARE A SEPARATE ENTRANCE (Phase 4D2)
--------------------------------------------------
:func:`persist_derived_image_asset` is the same write with one thing that is not
optional: a crop, resize or other transformation carries its SOURCE's provenance
markers. It exists as its own function because the alternative — a flag on this
one — is a flag a writer can forget, and forgetting it reopens a laundering
path. See that function for what the path is and why the migration created it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.storage import StoredObject, delete_object, mint_object_key, put_object
from app.models.character_image import (
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_UNREVIEWED,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.schemas.character_image import derived_provenance

if TYPE_CHECKING:  # pragma: no cover
    from app.models.character import Character
    from app.models.user import User

logger = logging.getLogger(__name__)

#: Key under ``Session.info`` holding object keys written during the current
#: transaction whose rows are not committed yet. Session-scoped, so a session
#: that never persists an asset carries nothing and costs nothing.
_PENDING_KEYS = "_ficshon_pending_object_keys"

#: Stable log prefix for an object that could not be cleaned up. Grep-able on
#: purpose: it is the only record that a byte survived without a row, and the
#: seam a future reconciliation would read.
ORPHAN_OBJECT = "ORPHAN_OBJECT"


@dataclass(frozen=True)
class OwnedBy:
    """Who owns an asset, and — if anything — what it is associated with.

    Built through :meth:`character` or :meth:`account`. The constructor is not
    the API; the two named constructors are, because the point is that the two
    cases cannot be confused for one another at a call site.
    """

    user_id: int
    character_id: Optional[int]

    @classmethod
    def character(cls, character: "Character") -> "OwnedBy":
        """Owned by the character's OWNER, associated with the character.

        Both values come from the same ``Character`` object, so they cannot
        disagree, and neither can be quietly supplied by the caller. An admin
        generating onto somebody else's character produces the OWNER's asset —
        that is the whole reason this takes an object rather than two ints.
        """
        owner_id = getattr(character, "owner_id", None)
        if not owner_id:
            raise ValueError(
                "Character has no owner_id; refusing to persist an asset that "
                "would belong to nobody."
            )
        character_id = getattr(character, "id", None)
        if not character_id:
            raise ValueError(
                "Character has no id; flush it before persisting an asset "
                "associated with it."
            )
        return cls(user_id=owner_id, character_id=character_id)

    @classmethod
    def account(cls, user: "User") -> "OwnedBy":
        """Owned by an account, associated with no character.

        The account-level case Phase 4C made representable: ``character_id`` is
        NULL, the asset stays in its owner's library, and no character-scoped
        route can reach it.
        """
        user_id = getattr(user, "id", None)
        if not user_id:
            raise ValueError(
                "User has no id; refusing to persist an asset that would belong "
                "to nobody."
            )
        return cls(user_id=user_id, character_id=None)


def _register_pending_object(db: Session, storage_key: str) -> None:
    """Remember *storage_key* until the caller's transaction resolves.

    THE PROBLEM THIS SOLVES. Compensating only when the INSERT fails is not
    enough. ``persist_image_asset`` returns successfully, the route then does
    something else that raises, the transaction rolls back — and the object
    survives forever with no row that ever existed. That is the same orphan,
    produced one step later.

    So the object's fate follows the transaction's:

    * ``after_commit`` — the rows are durable; forget the keys.
    * outermost ``after_transaction_end`` with keys still pending — the
      transaction ended WITHOUT committing; delete the objects.

    ``after_transaction_end`` rather than ``after_rollback`` because
    ``after_rollback`` does not fire on the path that actually matters:
    FastAPI's ``get_db`` only calls ``Session.close()``, and a close without a
    commit emits neither ``after_rollback`` nor ``after_soft_rollback``.
    Verified against SQLAlchemy 2.0.25 rather than assumed; the test suite pins
    all four lifecycles.

    This is a session-scoped unit of work, not a garbage collector. It knows
    only about objects written during this transaction, and it forgets them the
    moment they are committed.
    """
    db.info.setdefault(_PENDING_KEYS, []).append(storage_key)


def _forget_pending_objects(session: Session) -> None:
    session.info.pop(_PENDING_KEYS, None)


def _compensate_pending_objects(session: Session) -> None:
    """Delete objects whose rows never committed. Best effort, never raises."""
    keys = session.info.pop(_PENDING_KEYS, None)
    if not keys:
        return
    for key in keys:
        try:
            delete_object(key)
            logger.info(
                "ASSET_OBJECT_COMPENSATED key=%s reason=transaction_not_committed", key
            )
        except Exception as exc:  # noqa: BLE001 — cleanup must never raise
            logger.error(
                "%s key=%s reason=transaction_not_committed cleanup_error=%s: %s",
                ORPHAN_OBJECT, key, type(exc).__name__, exc,
            )


@event.listens_for(Session, "after_commit")
def _assets_committed(session: Session) -> None:
    _forget_pending_objects(session)


@event.listens_for(Session, "after_transaction_end")
def _assets_transaction_ended(session: Session, transaction) -> None:
    # Only the outermost transaction decides. A flush opens and closes a
    # subtransaction, and that is not the caller resolving anything.
    if transaction.parent is None:
        _compensate_pending_objects(session)


def persist_image_asset(
    db: Session,
    *,
    content: bytes,
    owner: OwnedBy,
    kind: ImageKindEnum,
    provider: Optional[str],
    derived_from: Optional[CharacterImage] = None,
    prompt_summary: Optional[str] = None,
    seed: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    visibility: ImageVisibilityEnum = ImageVisibilityEnum.PRIVATE,
) -> CharacterImage:
    """Persist *content* as a durable, owned image asset. Returns the row.

    Returns the ``CharacterImage``, never a URL. The asset's identity is its
    row; the URL is a way to deliver it, and treating the URL as the identity is
    what left ~200 objects on DEV that no query can attribute to anybody.

    ORDER, AND WHY. Bytes are written first, then the row is inserted with the
    key that was just written. The alternative — insert a pending row, write
    bytes, finalise — adds a third lifecycle state that every reader, query and
    safety predicate would have to learn, to guard a failure that cannot happen
    today. If storage fails, nothing is inserted. If the insert fails, the
    object written by THIS call is deleted, and a cleanup that itself fails logs
    :data:`ORPHAN_OBJECT` and re-raises the ORIGINAL error — a diagnostic must
    never outrank the error it describes.

    NO COMMIT. The row is added and flushed so its id exists, and the
    transaction remains the caller's to commit or abandon. If the caller
    abandons it, the object is deleted too (:func:`_register_pending_object`).

    ``provider`` is REQUIRED, though it may be ``None``. It is the input to
    ``is_public_surface_safe``, and an image whose provenance nobody stated
    cannot be judged — the one Editor Studio row that reached the public gallery
    got there because its provider was ``gpt-image``, not ``self_hosted``.
    Passing ``None`` is a statement ("no provider — a user supplied these
    bytes"), and it has to be made rather than defaulted into.

    ``derived_from`` records SINGLE-source lineage only, and only when the
    source is a ``CharacterImage``. A multi-reference generation has several
    sources and this column can name one; claiming lineage there would be a
    false record, so those writers leave it unset and describe their references
    in ``metadata``.
    """
    if not content:
        raise ValueError("Refusing to persist an empty image asset.")
    if not isinstance(owner, OwnedBy):
        raise TypeError(
            "owner must be OwnedBy.character(character) or OwnedBy.account(user). "
            "A raw id is not accepted: it cannot distinguish the asset's owner "
            "from whoever happened to make the request."
        )
    if not isinstance(kind, ImageKindEnum):
        raise TypeError("kind must be an ImageKindEnum member.")

    derived_from_image_id = None
    if derived_from is not None:
        if not isinstance(derived_from, CharacterImage):
            raise TypeError(
                "derived_from must be a CharacterImage. There is no lineage "
                "column for any other source; record it in metadata instead."
            )
        derived_from_image_id = derived_from.id
        if derived_from_image_id is None:
            raise ValueError(
                "derived_from has no id; flush the source row before deriving "
                "from it."
            )

    storage_key = mint_object_key(content)
    stored: StoredObject = put_object(content, key=storage_key)

    image = CharacterImage(
        user_id=owner.user_id,
        character_id=owner.character_id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
        visibility=visibility,
        provider=provider,
        prompt_summary=prompt_summary,
        seed=seed,
        metadata_json=metadata,
        file_path=stored.file_path,
        storage_key=stored.storage_key,
        derived_from_image_id=derived_from_image_id,
        # Set explicitly, and unconditionally. The DB default says the same
        # thing and stays as defence-in-depth for writers nobody remembered to
        # update; stating it here makes it the application's answer rather than
        # a value that happened to arrive. There is no parameter that can change
        # it: an asset is reviewed by a policy, and no policy has run.
        safety_state=SAFETY_STATE_UNREVIEWED,
        safety_policy_version=SAFETY_POLICY_VERSION_NONE,
    )

    try:
        db.add(image)
        db.flush()
    except Exception:
        # The object exists and its row does not. Delete exactly the key this
        # call minted — held in a local, never looked up, never guessed.
        try:
            delete_object(stored.storage_key)
            logger.info(
                "ASSET_OBJECT_COMPENSATED key=%s reason=row_insert_failed",
                stored.storage_key,
            )
        except Exception as cleanup_exc:  # noqa: BLE001
            logger.error(
                "%s key=%s reason=row_insert_failed cleanup_error=%s: %s",
                ORPHAN_OBJECT, stored.storage_key,
                type(cleanup_exc).__name__, cleanup_exc,
            )
        raise

    _register_pending_object(db, stored.storage_key)
    return image


# ── Derived assets ────────────────────────────────────────────────────────────


def source_image_for_url(db: Session, url: Optional[str]) -> Optional[CharacterImage]:
    """The ONE ``CharacterImage`` whose stored file serves *url*, or ``None``.

    For writers handed a url rather than a row — the candidate-slot promoter is
    the case in 4D2 — so a crop can name the asset it came from instead of
    losing the connection because the caller's parameter happened to be a
    string.

    ``None`` when nothing matches AND when several rows match. An ambiguous
    answer is not a source: ``derived_from_image_id`` names exactly one row, and
    guessing which of two it should be would put a false record in the lineage
    column. The caller then persists with ``source=None``, which inherits no
    provenance and claims no lineage — the honest description of "we do not know
    where these bytes came from".

    Shares :func:`~app.services.character_home_media.candidate_file_paths` with
    the public resolver so the two cannot disagree about which stored path a url
    names.
    """
    if not url:
        return None
    from app.services.character_home_media import candidate_file_paths

    rows = (
        db.query(CharacterImage)
        .filter(CharacterImage.file_path.in_(list(candidate_file_paths(url))))
        .all()
    )
    return rows[0] if len(rows) == 1 else None


def persist_derived_image_asset(
    db: Session,
    *,
    content: bytes,
    owner: OwnedBy,
    kind: ImageKindEnum,
    source: Optional[Any],
    prompt_summary: Optional[str] = None,
    seed: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    visibility: ImageVisibilityEnum = ImageVisibilityEnum.PRIVATE,
) -> CharacterImage:
    """Persist bytes DERIVED from an existing asset — a crop, a resize.

    The same call as :func:`persist_image_asset` with one difference that must
    not be optional: *source* decides the new asset's ``provider`` and carries
    its provenance markers forward
    (:func:`~app.schemas.character_image.derived_provenance`).

    WHY IT IS A SEPARATE FUNCTION rather than a parameter. Until Phase 4D2 the
    avatar crops wrote no row, so a crop of Adult Studio or Editor Studio output
    was withheld from every shared surface — because nothing could be found to
    judge, not because anything had judged it. Giving those crops a real row
    makes them resolvable, and a resolvable row with ``provider=None`` and fresh
    metadata reads as SAFE. Then, since the crop is itself a ``CharacterImage``
    its owner may select, it can be set as a character avatar that
    ``is_public_surface_safe`` refused for the original. The laundering path is
    created by the migration, so the migration is where it has to be closed —
    and a derived writer that simply forgot to pass a flag would reopen it. Here
    there is no call shape that omits the source.

    ``source`` may be:

    * a ``CharacterImage`` — provenance inherited AND ``derived_from_image_id``
      set, because the lineage column can name it;
    * a ``UserImage`` (duck-typed: anything else with ``provider`` /
      ``metadata_json``) — provenance inherited, lineage recorded in metadata as
      ``{"derived_from": {"table": ..., "id": ...}}``. There is no FK to
      ``user_images`` and 4D2 does not add one, so the honest record is the one
      the schema can actually hold;
    * ``None`` — for a caller that genuinely cannot identify its source. It
      inherits nothing and claims nothing; use it only when the source is
      unknown, never to skip the inheritance.

    What it does NOT copy is ``safety_state``. Evidence about where bytes came
    from is inheritable; a decision made about specific bytes under a stated
    policy version is not. See :func:`derived_provenance`.
    """
    provider, provenance = derived_provenance(source) if source is not None else (None, {})

    merged: dict[str, Any] = dict(metadata or {})
    if source is not None and not isinstance(source, CharacterImage):
        table = getattr(getattr(source, "__table__", None), "name", None)
        merged["derived_from"] = {"table": table, "id": getattr(source, "id", None)}
    # Provenance last: a caller's metadata must not be able to overwrite the
    # markers that exclude, whatever it thought it was describing.
    merged.update(provenance)

    return persist_image_asset(
        db,
        content=content,
        owner=owner,
        kind=kind,
        provider=provider,
        derived_from=source if isinstance(source, CharacterImage) else None,
        prompt_summary=prompt_summary,
        seed=seed,
        metadata=merged or None,
        visibility=visibility,
    )
