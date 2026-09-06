"""Phase 4D3-1 — the canon cluster gets honest kinds, and nothing else changes.

This checkpoint adds ten ``ImageKindEnum`` values and the Alembic migration that
puts them in the PostgreSQL type. No writer produces one yet; 4D3-3 does that,
after the avatar policy lands in 4D3-2.

So what is worth testing is not "the enum has ten more members" — it is the two
properties that make shipping a taxonomy on its own safe, and the one that makes
it correct:

* **Adding a kind grants nothing.** Every publication allowlist is opt-in, so a
  kind nobody opted in is private. If a future edit widens one of them by
  accident, these tests fail before any canon image exists to be exposed.
* **The migration and the model cannot drift.** A member added to one and
  forgotten in the other is an INSERT that fails in production and passes in
  tests, because SQLite stores the column as TEXT and would accept anything.
* **The names mean what they say.** Specifically, the full-body side views are
  NOT the marking detail crops, which is the reuse this taxonomy exists to
  refuse.
"""
import importlib.util
import pathlib
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.character import Character
from app.models.character_image import (
    POST_ATTACHABLE_IMAGE_KINDS,
    PROTECTED_IMAGE_KINDS,
    REFERENCE_SELECTABLE_IMAGE_KINDS,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.schemas.character_image import PUBLIC_GALLERY_KINDS

#: The ten, as approved. Written out literally rather than derived from the
#: model, so a member renamed or dropped in the model fails here instead of
#: quietly redefining what the test is checking.
CANON_KINDS_4D3 = (
    ImageKindEnum.IDENTITY_FACE_PROFILE,
    ImageKindEnum.IDENTITY_FACE_EXPRESSION,
    ImageKindEnum.IDENTITY_BODY_LEFT,
    ImageKindEnum.IDENTITY_BODY_RIGHT,
    ImageKindEnum.IDENTITY_TORSO_FRONT,
    ImageKindEnum.IDENTITY_TORSO_SIDE,
    ImageKindEnum.IDENTITY_POSE_STANDING,
    ImageKindEnum.IDENTITY_POSE_SEATED,
    ImageKindEnum.IDENTITY_MARK_REFERENCE,
    ImageKindEnum.IDENTITY_MARK_DETAIL,
)

_MIGRATION_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "alembic" / "versions" / "p4d3_01_add_canon_image_kinds.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("p4d3_01", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ── the values themselves ────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", CANON_KINDS_4D3, ids=lambda k: k.value)
def test_the_kind_exists_with_the_approved_value(kind):
    assert ImageKindEnum(kind.value) is kind


def test_the_side_views_are_not_the_detail_crops():
    """The reuse this taxonomy exists to refuse.

    ``identity_body_left_detail`` means a tight high-fidelity crop of a marking
    and is in use for that. A full-body left-side VIEW is a different image, and
    giving it the same label would make "detail crop" unqueryable.
    """
    assert ImageKindEnum.IDENTITY_BODY_LEFT is not ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL
    assert ImageKindEnum.IDENTITY_BODY_RIGHT is not ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL
    assert ImageKindEnum.IDENTITY_BODY_LEFT.value != ImageKindEnum.IDENTITY_BODY_LEFT_DETAIL.value
    assert ImageKindEnum.IDENTITY_BODY_RIGHT.value != ImageKindEnum.IDENTITY_BODY_RIGHT_DETAIL.value


def test_no_generic_body_pose_kind_was_introduced():
    """The collapsed taxonomy was considered and rejected: each pose card keeps
    its own label, so the kind column alone identifies the canon slot."""
    assert not hasattr(ImageKindEnum, "IDENTITY_BODY_POSE")
    assert "identity_body_pose" not in {k.value for k in ImageKindEnum}


def test_generated_mark_anchors_share_the_reference_kind():
    """A generated close-up and an uploaded reference photo are one semantic
    object; ``provider`` separates them, so no ``identity_mark_anchor`` exists."""
    assert not hasattr(ImageKindEnum, "IDENTITY_MARK_ANCHOR")
    assert "identity_mark_anchor" not in {k.value for k in ImageKindEnum}


# ── adding a kind grants nothing ─────────────────────────────────────────────


@pytest.mark.parametrize("kind", CANON_KINDS_4D3, ids=lambda k: k.value)
def test_the_kind_is_not_public_gallery_material(kind):
    assert kind not in PUBLIC_GALLERY_KINDS


@pytest.mark.parametrize("kind", CANON_KINDS_4D3, ids=lambda k: k.value)
def test_the_kind_is_not_post_attachable(kind):
    # This allowlist holds .value strings; check both spellings so the test
    # cannot pass merely because the membership test compares the wrong type.
    assert kind not in POST_ATTACHABLE_IMAGE_KINDS
    assert kind.value not in POST_ATTACHABLE_IMAGE_KINDS


@pytest.mark.parametrize("kind", CANON_KINDS_4D3, ids=lambda k: k.value)
def test_the_kind_is_not_hand_pickable_as_a_generation_reference(kind):
    """Which canon slots reach a provider is the scene router's decision, taken
    from locked canon — never a founder hand-picking one in the library."""
    assert kind not in REFERENCE_SELECTABLE_IMAGE_KINDS
    assert kind.value not in REFERENCE_SELECTABLE_IMAGE_KINDS


def test_the_publication_allowlists_were_not_widened():
    """Pinned whole, not per-kind: a kind added to one of these lists by a later
    edit is caught even if it is not one of the ten."""
    assert PUBLIC_GALLERY_KINDS == frozenset({
        ImageKindEnum.GENERATED, ImageKindEnum.COVER, ImageKindEnum.SCENE_ONLY,
    })
    assert POST_ATTACHABLE_IMAGE_KINDS == frozenset({
        ImageKindEnum.GENERATED.value, ImageKindEnum.COVER.value,
        ImageKindEnum.SCENE_ONLY.value,
    })
    assert PROTECTED_IMAGE_KINDS == frozenset({
        ImageKindEnum.ANCHOR_FRONT, ImageKindEnum.ANCHOR_THREE_QUARTER,
        ImageKindEnum.ANCHOR_TORSO, ImageKindEnum.ANCHOR_FULL_BODY,
    })


# ── the migration and the model cannot drift ─────────────────────────────────


def test_the_migration_adds_exactly_these_values_in_declaration_order():
    module = _migration_module()
    declared = [k.value for k in CANON_KINDS_4D3]
    assert list(module._NEW_VALUES) == declared


def test_every_migrated_value_is_a_real_enum_member():
    module = _migration_module()
    known = {k.value for k in ImageKindEnum}
    assert set(module._NEW_VALUES) <= known


def test_the_migration_chains_onto_the_previous_head():
    module = _migration_module()
    assert module.revision == "p4d3_01_canon_image_kinds"
    assert module.down_revision == "p4c01_character_id_optional"


def test_the_migration_leaves_exactly_one_head():
    """A second head is how a migration silently stops being applied.

    Asked of Alembic's own ``ScriptDirectory`` rather than a regex over the
    versions directory: down_revision may be a string, a tuple (this chain has
    merge points) or None, and a hand-rolled parser that mishandles one of those
    reports a phantom head — which is a test failing for a reason that has
    nothing to do with the migration.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = pathlib.Path(__file__).resolve().parent.parent / "alembic.ini"
    script = ScriptDirectory.from_config(Config(str(ini)))
    assert script.get_heads() == ["p4d3_01_canon_image_kinds"]


def test_the_migration_is_idempotent_and_postgres_only():
    """``ADD VALUE IF NOT EXISTS`` for every value, and a no-op off PostgreSQL —
    the two properties that let it be re-run against a partially-upgraded DB."""
    source = _MIGRATION_PATH.read_text()
    assert 'if bind.dialect.name != "postgresql":' in source
    assert "ADD VALUE IF NOT EXISTS" in source
    assert "DROP TYPE" not in source and "ALTER TABLE" not in source


def test_downgrade_is_a_no_op():
    """PostgreSQL cannot remove an enum value; pretending otherwise would make
    a downgrade fail halfway rather than do nothing."""
    module = _migration_module()
    assert module.downgrade() is None


# ── the column actually accepts them ─────────────────────────────────────────


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'kinds.db'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def character(db):
    owner = User(email="owner@4d3.test", username="owner4d3", hashed_password="x")
    db.add(owner)
    db.flush()
    char = Character(owner_id=owner.id, name="Canon Character")
    db.add(char)
    db.flush()
    db.commit()
    return char


@pytest.mark.parametrize("kind", CANON_KINDS_4D3, ids=lambda k: k.value)
def test_a_row_round_trips_through_the_kind_column(db, character, kind):
    image = CharacterImage(
        user_id=character.owner_id,
        character_id=character.id,
        kind=kind,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="google",
        file_path=f"static/generated/{kind.value}.png",
    )
    db.add(image)
    db.commit()
    db.expire_all()

    stored = db.query(CharacterImage).filter(CharacterImage.id == image.id).one()
    assert stored.kind is kind
    assert stored.kind.value == kind.value


def test_no_writer_produces_a_canon_kind_yet():
    """4D3-1 is taxonomy only. The writers migrate in 4D3-3, after the avatar
    policy exists — so no application module may reference these kinds yet."""
    app_root = pathlib.Path(__file__).resolve().parent.parent / "app"
    names = {k.name for k in CANON_KINDS_4D3}
    offenders = []
    for path in app_root.rglob("*.py"):
        if path.name == "character_image.py" and path.parent.name == "models":
            continue  # the declaration itself
        text = path.read_text()
        for name in names:
            if re.search(rf"\bImageKindEnum\.{name}\b", text):
                offenders.append(f"{path.relative_to(app_root)}:{name}")
    assert offenders == [], f"4D3-1 must not wire up writers yet: {offenders}"
