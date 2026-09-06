"""Phase 4D3-3 — what the weekly image allowance actually meters.

The quota counted every ``CharacterImage`` row the account owned. That was a
workable proxy for "images you generated" only while ordinary generation was the
sole thing creating rows. Phase 4D3 made durable canon assets first-class rows
and the proxy broke the same day: one v2 canon pack writes 13 cards plus a crop
per permanent mark, against an ``IMAGE_WEEKLY_LIMIT`` of 10 — so building a pack
would overshoot the entire weekly allowance and lock the founder out of image
generation, scene generation and Editor Studio for a week.

The fix is not a bigger number. "A row exists" and "the user generated an image"
are different statements now, and the quota asks the second one.
"""
import pytest

from app.core.config import settings
from app.models.character import Character
from app.models.character_image import (
    QUOTA_COUNTED_IMAGE_KINDS,
    CharacterImage,
    ImageKindEnum,
    ImageStatusEnum,
    ImageVisibilityEnum,
)
from app.models.user import User
from app.schemas.canon import SLOT_IMAGE_KIND
from app.services.image_quota import get_quota_status

#: Everything a v2 pack writes, plus the mark crop. None may cost a generation.
V2_PACK_KINDS = tuple(SLOT_IMAGE_KIND.values()) + (ImageKindEnum.IDENTITY_MARK_DETAIL,)


@pytest.fixture()
def user(db_session):
    u = User(email="quota@4d3q.test.com", username="quota4d3", hashed_password="x")
    db_session.add(u)
    db_session.flush()
    c = Character(owner_id=u.id, name="Quota Character")
    db_session.add(c)
    db_session.commit()
    return u, c


def _row(db, user, character, kind):
    img = CharacterImage(
        user_id=user.id, character_id=character.id, kind=kind,
        status=ImageStatusEnum.ACTIVE, visibility=ImageVisibilityEnum.PRIVATE,
        provider="google",
        file_path=f"https://r2.example/generated/{kind.value}-{id(kind)}.png",
    )
    db.add(img)
    db.commit()
    return img


# ── what the policy says ─────────────────────────────────────────────────────


def test_the_counted_set_is_exactly_the_ordinary_generation_kinds():
    assert QUOTA_COUNTED_IMAGE_KINDS == frozenset({
        ImageKindEnum.GENERATED, ImageKindEnum.SCENE_ONLY, ImageKindEnum.COVER,
    })


def test_uploads_do_not_count():
    """The founder supplied the bytes; nothing was generated and nothing spent.
    This also covers avatar/cover crops, which are written as UPLOADED."""
    assert ImageKindEnum.UPLOADED not in QUOTA_COUNTED_IMAGE_KINDS


@pytest.mark.parametrize("kind", sorted(set(V2_PACK_KINDS), key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_no_canon_kind_counts(kind):
    assert kind not in QUOTA_COUNTED_IMAGE_KINDS


def test_the_quota_set_is_not_aliased_to_the_gallery_set():
    """They coincide today and answer different questions. Aliasing them would
    let a gallery decision silently change what users are billed for."""
    from app.schemas.character_image import PUBLIC_GALLERY_KINDS

    assert QUOTA_COUNTED_IMAGE_KINDS is not PUBLIC_GALLERY_KINDS


# ── the behaviour ────────────────────────────────────────────────────────────


def test_a_full_v2_pack_does_not_decrement_the_allowance(db_session, user):
    """The regression that started this: 13 cards against a limit of 10."""
    u, c = user
    before = get_quota_status(u, db_session)
    assert before["used"] == 0

    for slot, kind in SLOT_IMAGE_KIND.items():
        _row(db_session, u, c, kind)
    _row(db_session, u, c, ImageKindEnum.IDENTITY_MARK_DETAIL)

    after = get_quota_status(u, db_session)
    assert after["used"] == 0, "a canon pack consumed the ordinary allowance"
    assert after["remaining"] == before["remaining"]
    assert after["remaining"] == settings.IMAGE_WEEKLY_LIMIT


def test_a_v2_pack_leaves_ordinary_generation_still_possible(db_session, user):
    """Not merely 'not exhausted' — the founder can still generate afterwards."""
    u, c = user
    for kind in SLOT_IMAGE_KIND.values():
        _row(db_session, u, c, kind)

    from app.services.image_quota import check_weekly_quota
    assert check_weekly_quota(u, db_session) is None


def test_a_canon_upload_does_not_consume_the_allowance(db_session, user):
    u, c = user
    _row(db_session, u, c, ImageKindEnum.IDENTITY_FACE_FRONT)
    _row(db_session, u, c, ImageKindEnum.IDENTITY_MARK_REFERENCE)
    _row(db_session, u, c, ImageKindEnum.UPLOADED)
    assert get_quota_status(u, db_session)["used"] == 0


@pytest.mark.parametrize("kind", sorted(QUOTA_COUNTED_IMAGE_KINDS, key=lambda k: k.value),
                         ids=lambda k: k.value)
def test_an_ordinary_generated_image_still_counts(db_session, user, kind):
    u, c = user
    _row(db_session, u, c, kind)
    assert get_quota_status(u, db_session)["used"] == 1


def test_the_allowance_still_runs_out_for_ordinary_generation(db_session, user):
    """The protection the quota exists for must survive the narrowing."""
    from app.services.image_quota import check_weekly_quota

    u, c = user
    for _ in range(settings.IMAGE_WEEKLY_LIMIT):
        _row(db_session, u, c, ImageKindEnum.GENERATED)

    status = get_quota_status(u, db_session)
    assert status["used"] == settings.IMAGE_WEEKLY_LIMIT
    assert status["remaining"] == 0
    refusal = check_weekly_quota(u, db_session)
    assert refusal is not None and refusal.status_code == 429


def test_canon_rows_do_not_dilute_a_used_allowance(db_session, user):
    """Mixed history: canon rows must neither add to nor mask real usage."""
    u, c = user
    for _ in range(3):
        _row(db_session, u, c, ImageKindEnum.SCENE_ONLY)
    for kind in SLOT_IMAGE_KIND.values():
        _row(db_session, u, c, kind)
    assert get_quota_status(u, db_session)["used"] == 3


def test_the_reset_anchor_ignores_canon_rows(db_session, user):
    """``reset_at`` is derived from the OLDEST counted row. A canon row written
    first must not become the anchor and misreport when a slot reopens."""
    u, c = user
    for kind in SLOT_IMAGE_KIND.values():
        _row(db_session, u, c, kind)
    assert get_quota_status(u, db_session)["reset_at"] is None

    _row(db_session, u, c, ImageKindEnum.GENERATED)
    assert get_quota_status(u, db_session)["reset_at"] is not None
