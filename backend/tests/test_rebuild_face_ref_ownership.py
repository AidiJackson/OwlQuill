"""scripts/rebuild_face_ref.py must produce an OWNED face_ref (Phase 4B2).

The script is an operator tool: it is run by whoever is holding the terminal,
against characters belonging to other people. ``CharacterImage.user_id`` is NOT
NULL and means "the account that owns this asset", so the owner has to come
from the character being rebuilt — the operator has no claim on the image and
is not recorded on it at all.
"""
import importlib.util
from pathlib import Path

import pytest

from app.core.storage import save_image
from app.models.character import Character
from app.models.character_image import (
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User

# 1x1 PNG — real bytes, so save/load round-trips through the storage layer.
_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f030005fe02fea7568c4e0000000049454e44ae426082"
)


def _load_script():
    """Import the script by path — backend/scripts is not a package."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "rebuild_face_ref.py"
    spec = importlib.util.spec_from_file_location("rebuild_face_ref", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def script():
    return _load_script()


@pytest.fixture()
def locked_character(db_session):
    """An owned, locked character with an ANCHOR_FRONT and no face_ref yet."""
    owner = User(email="rebuild-owner@test.local", username="rebuildowner",
                 hashed_password="x")
    db_session.add(owner)
    db_session.flush()

    character = Character(
        owner_id=owner.id,
        name="Rebuild Target",
        identity_anchor_json='{"locked": true}',  # Text column, not JSON
    )
    db_session.add(character)
    db_session.flush()

    db_session.add(CharacterImage(
        character_id=character.id,
        user_id=owner.id,
        kind=ImageKindEnum.ANCHOR_FRONT,
        status=ImageStatusEnum.ACTIVE,
        visibility=ImageVisibilityEnum.PRIVATE,
        provider="openai",
        file_path=save_image(_PNG_BYTES),
    ))
    db_session.commit()
    return owner, character


def test_rebuilt_face_ref_is_owned_by_the_characters_owner(
    db_session, script, locked_character, monkeypatch
):
    owner, character = locked_character
    monkeypatch.setattr(script, "_crop_face_reference", lambda _raw: _PNG_BYTES)

    result = script.rebuild_for_character(db_session, character)
    assert result.startswith("BUILT"), result

    face_ref = (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character.id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
        )
        .one()
    )
    assert face_ref.user_id == owner.id


def test_an_ownerless_character_produces_no_image_at_all(
    db_session, script, locked_character, monkeypatch
):
    """Refuse loudly rather than write a row nobody can be held to.

    ``characters.owner_id`` is NOT NULL, so this state is not reachable through
    the ORM — the guard exists for a hand-edited row or a future schema where
    it is. What is asserted is the consequence: nothing is written.
    """
    _owner, character = locked_character
    monkeypatch.setattr(script, "_crop_face_reference", lambda _raw: _PNG_BYTES)
    monkeypatch.setattr(character, "owner_id", None, raising=False)

    result = script.rebuild_for_character(db_session, character)
    assert result.startswith("ERROR")
    assert "owner" in result

    assert (
        db_session.query(CharacterImage)
        .filter(
            CharacterImage.character_id == character.id,
            CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF,
        )
        .count()
        == 0
    )


def test_dry_run_writes_nothing_and_names_the_owner(
    db_session, script, locked_character, monkeypatch
):
    owner, character = locked_character
    monkeypatch.setattr(script, "_crop_face_reference", lambda _raw: _PNG_BYTES)

    result = script.rebuild_for_character(db_session, character, dry_run=True)
    assert result.startswith("DRY")
    assert f"owned by user {owner.id}" in result
    assert (
        db_session.query(CharacterImage)
        .filter(CharacterImage.kind == ImageKindEnum.IDENTITY_FACE_REF)
        .count()
        == 0
    )
