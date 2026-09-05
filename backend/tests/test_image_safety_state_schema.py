"""Phase 4A — the safety-audit columns, and the fact that nothing reads them yet.

Two jobs, and the second matters as much as the first.

**The schema tells the truth.** ``safety_state`` exists so that six months from
now a row can say whether Ficshon actually reviewed it, rather than whether some
historical code happened not to reject its provider. That only holds if a
half-written decision is impossible, so the CHECK constraints are asserted
directly: an unreviewed row carries no decision residue, and a decided row
carries a complete decision — a policy version, a timestamp and a source.

**Nothing enforces it yet.** No predicate and no resolver reads ``safety_state``
in this increment, deliberately. Wiring it in today would either black out every
public surface (nothing is approved) or read as ``!= 'rejected'``, a no-op that
looks like protection. The tests below pin the *current* answer so the future
enforcement flip has to be a deliberate edit that also deletes them.

Foreign-key semantics need enforcement turned on, which SQLite does not do by
default; ``fk_session`` supplies a session that does. The same behaviours were
also confirmed against real PostgreSQL on an isolated replica before this
migration was applied to DEV.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    SAFETY_DECISION_SOURCE_AUTOMATED,
    SAFETY_DECISION_SOURCE_HUMAN,
    SAFETY_DECISION_SOURCES,
    SAFETY_POLICY_VERSION_NONE,
    SAFETY_STATE_APPROVED,
    SAFETY_STATE_REJECTED,
    SAFETY_STATE_UNREVIEWED,
    SAFETY_STATES,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.schemas.character_image import (
    is_public_gallery_image,
    is_public_post_image,
    is_public_surface_safe,
)


# ── A foreign-key-enforcing session ───────────────────────────────────────────

@pytest.fixture()
def fk_session(tmp_path):
    """A private SQLite session with ``PRAGMA foreign_keys=ON``.

    SQLite ignores foreign keys unless asked, and the shared test engine is left
    exactly as it was rather than being switched globally — turning enforcement
    on for the whole suite would be a behavioural change smuggled in under a
    schema increment.
    """
    engine = create_engine(f"sqlite:///{tmp_path/'fk.db'}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(session, username):
    u = User(email=f"{username}@test.invalid", username=username,
             hashed_password="x", created_at=datetime.utcnow(),
             updated_at=datetime.utcnow())
    session.add(u)
    session.commit()
    session.refresh(u)
    return u


def _character(session, owner_id, name="Owned"):
    c = Character(owner_id=owner_id, name=name, created_at=datetime.utcnow(),
                  updated_at=datetime.utcnow())
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _image(session, character_id, file_path="static/generated/a.png", **kw):
    # 4B2: user_id is NOT NULL and is derived from the character, exactly as
    # every production writer derives it.
    kw.setdefault(
        "user_id",
        session.query(Character).filter(Character.id == character_id).one().owner_id,
    )
    img = CharacterImage(
        character_id=character_id,
        kind=ImageKindEnum.GENERATED,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        file_path=file_path,
        **kw,
    )
    session.add(img)
    session.commit()
    session.refresh(img)
    return img


@pytest.fixture()
def owned(fk_session):
    user = _user(fk_session, "owner")
    return fk_session, _character(fk_session, user.id), user


# ── A. Default / historical state ─────────────────────────────────────────────

def test_a_new_row_is_unreviewed_with_no_decision_residue(owned):
    """The only honest default: nobody looked."""
    session, character, _ = owned
    img = _image(session, character.id)

    assert img.safety_state == SAFETY_STATE_UNREVIEWED
    assert img.safety_policy_version == SAFETY_POLICY_VERSION_NONE == 0
    assert img.safety_decided_at is None
    assert img.safety_decided_by is None
    assert img.safety_decision_source is None
    assert img.safety_reason is None


def test_raw_sql_insert_still_lands_on_the_fail_safe_default(owned):
    """The server default, not the Python one — the property that actually protects.

    Thirteen modules currently mint image files and write no row at all. When
    they are fixed, whichever of them forgets to set a safety state must still
    produce an unreviewed row, and that guarantee has to live in the DDL rather
    than in a model attribute someone can bypass.
    """
    session, character, _ = owned
    # ``user_id`` is NOT NULL as of Phase 4B2, so even the deliberately minimal
    # insert has to name an owner. The point of the test is unchanged: nothing
    # here sets a safety state, and the DDL still has to supply one.
    session.execute(text(
        "INSERT INTO character_images "
        "(character_id, user_id, kind, status, visibility, file_path, created_at) "
        "VALUES (:c, :u, 'generated', 'active', 'private', 'raw/insert.png', :t)"
    ), {"c": character.id, "u": character.owner_id, "t": datetime.utcnow()})
    session.commit()

    row = session.execute(text(
        "SELECT safety_state, safety_policy_version FROM character_images "
        "WHERE file_path = 'raw/insert.png'"
    )).one()
    assert row.safety_state == "unreviewed"
    assert row.safety_policy_version == 0


def test_new_columns_start_empty(owned):
    """``storage_key`` and lineage are declared, not yet populated by anything."""
    session, character, _ = owned
    img = _image(session, character.id)
    assert img.storage_key is None
    assert img.derived_from_image_id is None


def test_storage_key_is_nullable_and_not_yet_unique(owned):
    """Nullable, and deliberately WITHOUT a unique index in this increment.

    Uniqueness is achievable — all 1,429 DEV file_paths are already distinct —
    but the index is created after a deterministic backfill has run and been
    checked for collisions, not before.
    """
    session, character, _ = owned
    a = _image(session, character.id, file_path="a.png", storage_key=None)
    b = _image(session, character.id, file_path="b.png", storage_key="generated/x.png")
    c = _image(session, character.id, file_path="c.png", storage_key="generated/x.png")
    assert a.storage_key is None
    assert b.storage_key == c.storage_key == "generated/x.png"


# ── B. Recognised values ──────────────────────────────────────────────────────

def test_the_recognised_state_and_source_vocabularies(owned):
    assert SAFETY_STATES == {"unreviewed", "approved", "rejected"}
    assert SAFETY_DECISION_SOURCES == {"human", "automated"}


@pytest.mark.parametrize("bad_state", ["pending", "legacy_unreviewed",
                                       "review_required", "APPROVED", ""])
def test_an_unrecognised_state_is_rejected_by_the_database(owned, bad_state):
    """A state nobody has defined must not be storable.

    ``review_required`` is in this list on purpose: it is the state most likely
    to be wanted next, and it must arrive through a deliberate CHECK edit rather
    than by somebody writing the string and finding that it sticks.
    """
    session, character, _ = owned
    with pytest.raises(IntegrityError):
        _image(session, character.id, safety_state=bad_state)
    session.rollback()


@pytest.mark.parametrize("bad_source", ["robot", "system", "HUMAN", ""])
def test_an_unrecognised_decision_source_is_rejected(owned, bad_source):
    session, character, _ = owned
    with pytest.raises(IntegrityError):
        _image(session, character.id,
               safety_state=SAFETY_STATE_APPROVED, safety_policy_version=1,
               safety_decided_at=datetime.utcnow(), safety_decision_source=bad_source)
    session.rollback()


# ── C. Impossible audit combinations ──────────────────────────────────────────

@pytest.mark.parametrize("label,kw", [
    ("approved with policy version 0", dict(
        safety_state=SAFETY_STATE_APPROVED, safety_policy_version=0,
        safety_decided_at=datetime.utcnow(),
        safety_decision_source=SAFETY_DECISION_SOURCE_HUMAN)),
    ("approved without a timestamp", dict(
        safety_state=SAFETY_STATE_APPROVED, safety_policy_version=1,
        safety_decision_source=SAFETY_DECISION_SOURCE_HUMAN)),
    ("approved without a source", dict(
        safety_state=SAFETY_STATE_APPROVED, safety_policy_version=1,
        safety_decided_at=datetime.utcnow())),
    ("rejected without a timestamp", dict(
        safety_state=SAFETY_STATE_REJECTED, safety_policy_version=2,
        safety_decision_source=SAFETY_DECISION_SOURCE_AUTOMATED)),
    ("unreviewed carrying a timestamp", dict(
        safety_decided_at=datetime.utcnow())),
    ("unreviewed carrying a source", dict(
        safety_decision_source=SAFETY_DECISION_SOURCE_HUMAN)),
    ("unreviewed carrying a policy version", dict(safety_policy_version=1)),
])
def test_a_half_written_decision_cannot_be_stored(owned, label, kw):
    """The invariant, enforced where it cannot be forgotten.

    A row claiming a review without recording which policy, when, or by what
    mechanism is exactly the ambiguity these columns exist to remove. The
    database refuses it, so the guarantee survives code that has not been
    written yet.
    """
    session, character, _ = owned
    with pytest.raises(IntegrityError):
        _image(session, character.id, **kw)
    session.rollback()


def test_unreviewed_carrying_a_decider_is_rejected(owned):
    session, character, user = owned
    with pytest.raises(IntegrityError):
        _image(session, character.id, safety_decided_by=user.id)
    session.rollback()


def test_a_complete_human_decision_is_accepted(owned):
    session, character, _ = owned
    moderator = _user(session, "moderator")
    decided = datetime.utcnow()
    img = _image(session, character.id,
                 safety_state=SAFETY_STATE_APPROVED, safety_policy_version=3,
                 safety_decided_at=decided, safety_decided_by=moderator.id,
                 safety_decision_source=SAFETY_DECISION_SOURCE_HUMAN,
                 safety_reason="reviewed under policy 3")
    assert img.safety_state == "approved"
    assert img.safety_decided_by == moderator.id
    assert img.safety_decision_source == "human"


def test_a_complete_automated_decision_needs_no_human_and_no_reason(owned):
    """An automated decision has nobody to name, and a placeholder reason would
    be worse than an honest NULL — its structured reasoning belongs with the
    policy version.
    """
    session, character, _ = owned
    img = _image(session, character.id,
                 safety_state=SAFETY_STATE_REJECTED, safety_policy_version=2,
                 safety_decided_at=datetime.utcnow(),
                 safety_decision_source=SAFETY_DECISION_SOURCE_AUTOMATED)
    assert img.safety_decided_by is None
    assert img.safety_reason is None
    assert img.safety_decision_source == "automated"


# ── D. Amendment 1: NULL decider never means "automated" ──────────────────────

def test_deleting_the_human_decider_keeps_the_decision_and_its_source(owned):
    """Why ``safety_decision_source`` is a column rather than an inference.

    ``safety_decided_by`` is ON DELETE SET NULL, so a NULL there is ambiguous:
    it may mean "no human was involved" or "the human later deleted their
    account". The source field is what survives, and the decision itself must
    not weaken when its author leaves.
    """
    session, character, _ = owned
    moderator = _user(session, "leaver")
    img = _image(session, character.id,
                 safety_state=SAFETY_STATE_APPROVED, safety_policy_version=3,
                 safety_decided_at=datetime.utcnow(), safety_decided_by=moderator.id,
                 safety_decision_source=SAFETY_DECISION_SOURCE_HUMAN,
                 safety_reason="reviewed under policy 3")
    assert img.safety_decided_by is not None

    session.delete(moderator)
    session.commit()
    session.expire_all()

    after = session.get(CharacterImage, img.id)
    assert after is not None, "the asset must survive its moderator"
    assert after.safety_decided_by is None
    assert after.safety_decision_source == SAFETY_DECISION_SOURCE_HUMAN
    assert after.safety_state == SAFETY_STATE_APPROVED
    assert after.safety_policy_version == 3
    assert after.safety_reason == "reviewed under policy 3"


# ── E. Derivation self-FK ─────────────────────────────────────────────────────

def test_a_derivative_can_name_its_source(owned):
    session, character, _ = owned
    source = _image(session, character.id, file_path="static/generated/source.png")
    crop = _image(session, character.id, file_path="static/generated/crop.png",
                  derived_from_image_id=source.id)
    assert crop.derived_from_image_id == source.id
    assert crop.derived_from.id == source.id
    assert [d.id for d in source.derivatives] == [crop.id]


def test_a_derivative_cannot_name_a_source_that_does_not_exist(owned):
    session, character, _ = owned
    with pytest.raises(IntegrityError):
        _image(session, character.id, derived_from_image_id=987654321)
    session.rollback()


def test_deleting_the_source_keeps_the_derivative(owned):
    """SET NULL, not CASCADE: deleting an original must not delete every crop
    ever taken from it. The lineage is lost; the asset is not.
    """
    session, character, _ = owned
    source = _image(session, character.id, file_path="static/generated/source.png")
    crop = _image(session, character.id, file_path="static/generated/crop.png",
                  derived_from_image_id=source.id)

    session.delete(source)
    session.commit()
    session.expire_all()

    after = session.get(CharacterImage, crop.id)
    assert after is not None
    assert after.derived_from_image_id is None


# ── F. Nothing reads safety_state yet ─────────────────────────────────────────

class _Row:
    """Duck-typed row carrying a safety state the predicates must ignore."""

    def __init__(self, safety_state, **kw):
        self.safety_state = safety_state
        self.safety_policy_version = 0
        self.provider = kw.get("provider", "fal")
        self.metadata_json = kw.get("metadata_json", {})
        self.kind = kw.get("kind", ImageKindEnum.GENERATED)
        self.status = kw.get("status", ImageStatusEnum.ACTIVE)


@pytest.mark.parametrize("predicate", [
    is_public_surface_safe, is_public_post_image, is_public_gallery_image,
])
@pytest.mark.parametrize("state", ["unreviewed", "approved", "rejected"])
def test_the_presentation_predicates_ignore_safety_state(predicate, state):
    """Phase 4A must not change what anyone can see — in either direction.

    Requiring ``approved`` today would black out every public surface, since no
    row is approved. Excluding only ``rejected`` would be a no-op that reads
    like protection and would be cited as one. So the predicates ignore the
    column entirely, and this test says so out loud.

    When enforcement is switched on, this test must be deliberately rewritten —
    that is its purpose. The denylist stays the floor even then: an approval
    must never publish something the provenance rule rejects.
    """
    assert predicate(_Row(state)) is True
    assert predicate(_Row(state, provider="replicate_nsfw")) is False
    assert predicate(_Row(state, metadata_json={"adult_studio": True})) is False


def test_a_rejected_row_is_still_shown_today_and_that_is_intended(owned):
    """Stated as behaviour, not just as predicate input, so the flip is visible.

    A row can already be marked ``rejected`` and it changes nothing about what
    is served. That is correct for this increment and wrong for the next one.
    """
    session, character, _ = owned
    img = _image(session, character.id,
                 safety_state=SAFETY_STATE_REJECTED, safety_policy_version=1,
                 safety_decided_at=datetime.utcnow(),
                 safety_decision_source=SAFETY_DECISION_SOURCE_AUTOMATED)
    assert is_public_surface_safe(img) is True
    assert is_public_post_image(img) is True


def test_the_resolvers_still_key_on_file_path_not_storage_key(owned):
    """``storage_key`` is declared but is not yet an address anything resolves by."""
    from app.services.character_home_media import resolve_public_media_url

    session, character, _ = owned
    _image(session, character.id, file_path="static/generated/keyed.png",
           storage_key="generated/keyed.png")

    assert resolve_public_media_url(session, "/static/generated/keyed.png") == \
        "/static/generated/keyed.png"
    # The storage key is not an address: asking by it resolves to nothing.
    assert resolve_public_media_url(session, "/generated/keyed.png") is None


# ── G. Schema/lineage invariants ──────────────────────────────────────────────

def test_character_id_became_nullable_in_a_later_increment():
    """This assertion has flipped, on purpose.

    Phase 4A wrote it as ``character_id is still NOT NULL``, with the note that
    nullability was "a later increment — serializers, cascade, ownership and
    quota all still assume a character". Those four are exactly what 4B1, 4B2
    and 4C then dealt with, in that order, and Phase 4C landed the nullability
    the note was deferring.

    Kept rather than deleted because 4A's real claim was that the safety columns
    did not depend on the association — and that claim is worth more now that
    the association can be absent. ``test_optional_character_association.py``
    proves the safety audit survives a character deletion in full.
    """
    assert CharacterImage.__table__.c.character_id.nullable is True
    assert CharacterImage.__table__.c.user_id.nullable is False


def test_lifecycle_and_safety_remain_separate_columns():
    """No redundant states: ARCHIVED is still the owner's delete, and safety
    says nothing about lifecycle.
    """
    assert {e.value for e in ImageStatusEnum} == {"active", "archived"}
    assert "deleted" not in {e.value for e in ImageStatusEnum}
    assert CharacterImage.__table__.c.status.name != \
        CharacterImage.__table__.c.safety_state.name


def test_no_public_eligible_column_was_added():
    """A duplicated boolean would give two answers to one question."""
    assert "public_eligible" not in CharacterImage.__table__.c


def test_the_declared_constraints_are_the_three_we_intend():
    from sqlalchemy import CheckConstraint

    names = {c.name for c in CharacterImage.__table__.constraints
             if isinstance(c, CheckConstraint)}
    assert names == {
        "ck_character_images_safety_state",
        "ck_character_images_safety_decision_source",
        "ck_character_images_safety_audit_coherent",
    }


def test_alembic_has_exactly_one_head():
    """The history had one head before this revision and must have one after.

    Pinned by SHAPE, not by name. The original form asserted the head was
    literally ``p4a01_image_safety_state``, which turned every later revision
    into a failure of the 4A suite and said nothing about whether 4A was still
    in the history. What matters is that the line stayed unbranched and that
    this revision is still on it.
    """
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert len(heads) == 1, heads

    ancestry = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert "p4a01_image_safety_state" in ancestry
