"""Cover framing survives — ``POST /cover`` must not silently recentre it.

WHAT THIS PINS. A character's cover framing lives in two nullable columns,
``cover_position_x`` and ``cover_position_y``, and is written by two different
endpoints: ``PATCH /characters/{id}`` (the reposition control) and
``POST /characters/{id}/cover`` (the governed image setter, which also accepts
framing so that choosing an image and framing it can be one action).

THE BUG THESE TESTS EXIST FOR. ``SetCharacterCoverRequest`` used to declare both
positions as ``float`` defaulting to ``0.5``, and the route assigned both
columns unconditionally. Omission was therefore indistinguishable from "centre
it", and one real caller omits them — ``handleSetAsCover`` in
``CharacterDetail.tsx``, the "Set as cover" action on the media tab. So a
creator who carefully repositioned a cover and later set that same image as the
cover from the gallery had their framing silently reset to the middle, in the
database, permanently. It survived a reload, which is what made it look as
though repositioning had never saved at all.

The distinction under test is therefore narrow and exact:

    omitted            -> PRESERVE whatever is stored
    supplied           -> SET to that value
    supplied AS 0.5    -> SET to centre (still expressible, deliberately)

That last case is why "treat 0.5 as absent" would have been the wrong fix:
recentring is a legitimate request, and it stays sayable precisely because
omission no longer says it.

Everything here goes through the HTTP API and then reads the COLUMN, so a test
passes only if the value was really persisted — not merely echoed back in a
response, which is the failure mode a response-only assertion would miss.
"""
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    TestingSessionLocal,
    auth_headers,
    character_owner_id,
    get_auth_token,
)


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Keep the storage layer off object storage for these tests."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _creator(client: TestClient, email: str, username: str) -> tuple[str, int]:
    token = get_auth_token(client, email=email, username=username)
    resp = client.post(
        "/characters/",
        json={"name": f"{username} Char", "species": "human"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return token, resp.json()["id"]


def _seed_image(cid: int):
    """One ACTIVE, cover-eligible ``CharacterImage`` owned by *cid*'s owner.

    ``file_path`` is an absolute https url — the shape a row has in
    object-storage mode, which is what production runs. The R2 branch of the
    setter performs every ownership, status, safety and kind check and then
    points the column at the source, so the checks under test are exercised
    without a test needing to write bytes into the repository tree.
    """
    from uuid import uuid4

    from app.models.character_image import (
        CharacterImage,
        ImageKindEnum,
        ImageStatusEnum,
        ImageVisibilityEnum,
    )

    db = TestingSessionLocal()
    try:
        img = CharacterImage(
            character_id=cid,
            user_id=character_owner_id(db, cid),
            kind=ImageKindEnum.GENERATED,
            status=ImageStatusEnum.ACTIVE,
            visibility=ImageVisibilityEnum.PRIVATE,
            file_path=f"https://cdn.test.invalid/generated/{uuid4().hex}.png",
        )
        db.add(img)
        db.commit()
        db.refresh(img)
        return img.id
    finally:
        db.close()


def _framing(character_id: int) -> tuple:
    """The STORED framing — what is in the row, not what a response claimed."""
    from app.models.character import Character

    db = TestingSessionLocal()
    try:
        row = db.query(Character).filter(Character.id == character_id).one()
        return row.cover_position_x, row.cover_position_y
    finally:
        db.close()


def _reposition(client: TestClient, token: str, cid: int, x: float, y: float) -> None:
    """Frame the cover exactly as the reposition control does."""
    resp = client.patch(
        f"/characters/{cid}",
        json={"cover_position_x": x, "cover_position_y": y},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


# ── A. Omission preserves ────────────────────────────────────────────────────


def test_setting_a_cover_without_positions_preserves_existing_framing(client):
    """THE REGRESSION TEST. Omitted framing must leave the stored framing alone.

    This is the exact sequence a creator performs: reposition the cover, then
    later use "Set as cover" on an image from the media tab. Before the fix the
    second step wrote 0.5/0.5 over the first and the composition was gone.
    """
    token, cid = _creator(client, "cvr_keep@test.com", "cvrkeep")
    image_id = _seed_image(cid)

    _reposition(client, token, cid, 0.2, 0.8)
    assert _framing(cid) == (0.2, 0.8)

    resp = client.post(
        f"/characters/{cid}/cover",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    assert _framing(cid) == (0.2, 0.8), "setting the cover image recentred the framing"


def test_the_preserving_response_reports_the_effective_framing(client):
    """The response must describe what is STORED, not echo an absent request.

    A caller that omits the positions still needs to know how the cover is
    framed; answering ``None`` (or 0.5) for a cover that is in fact framed at
    0.8 would make the response a worse source of truth than the database.
    """
    token, cid = _creator(client, "cvr_resp@test.com", "cvrresp")
    image_id = _seed_image(cid)

    _reposition(client, token, cid, 0.2, 0.8)

    body = client.post(
        f"/characters/{cid}/cover",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    ).json()

    assert body["cover_position_x"] == 0.2
    assert body["cover_position_y"] == 0.8


def test_never_positioned_character_still_reports_centre(client):
    """A legacy row holding NULL framing reports the value renderers draw with.

    Every renderer coalesces NULL to 0.5 (``coverObjectPosition``, ``?? 0.5``),
    so that is the effective position and the response says so rather than
    returning a null the client would have to re-interpret.
    """
    token, cid = _creator(client, "cvr_null@test.com", "cvrnull")
    image_id = _seed_image(cid)

    body = client.post(
        f"/characters/{cid}/cover",
        json={"image_type": "character", "image_id": image_id},
        headers=auth_headers(token),
    ).json()

    assert body["cover_position_x"] == 0.5
    assert body["cover_position_y"] == 0.5


# ── B. Supplied values still set ─────────────────────────────────────────────


def test_setting_a_cover_with_explicit_positions_writes_them(client):
    """Preserving omission must not have cost the endpoint its framing ability."""
    token, cid = _creator(client, "cvr_set@test.com", "cvrset")
    image_id = _seed_image(cid)

    resp = client.post(
        f"/characters/{cid}/cover",
        json={
            "image_type": "character",
            "image_id": image_id,
            "cover_position_x": 0.1,
            "cover_position_y": 0.9,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text

    assert _framing(cid) == (0.1, 0.9)
    body = resp.json()
    assert body["cover_position_x"] == 0.1
    assert body["cover_position_y"] == 0.9


def test_explicit_centre_still_recentres(client):
    """0.5 SUPPLIED means centre — the case a "treat 0.5 as absent" fix would break.

    Pinned because it is the difference between "omission is not a value" and
    "0.5 is not a value", and only the first of those is true.
    """
    token, cid = _creator(client, "cvr_mid@test.com", "cvrmid")
    image_id = _seed_image(cid)

    _reposition(client, token, cid, 0.2, 0.8)
    assert _framing(cid) == (0.2, 0.8)

    resp = client.post(
        f"/characters/{cid}/cover",
        json={
            "image_type": "character",
            "image_id": image_id,
            "cover_position_x": 0.5,
            "cover_position_y": 0.5,
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _framing(cid) == (0.5, 0.5)


def test_one_axis_may_be_set_while_the_other_is_preserved(client):
    """The axes are independent — the guard is per-field, not per-request."""
    token, cid = _creator(client, "cvr_axis@test.com", "cvraxis")
    image_id = _seed_image(cid)

    _reposition(client, token, cid, 0.2, 0.8)

    resp = client.post(
        f"/characters/{cid}/cover",
        json={"image_type": "character", "image_id": image_id, "cover_position_x": 0.9},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text
    assert _framing(cid) == (0.9, 0.8)


# ── C. The framing is READ BACK by the surfaces that render it ───────────────


def test_patch_framing_then_get_character_returns_both_axes(client):
    """The authenticated page reloads through this endpoint.

    Both axes are asserted deliberately: the pre-existing coverage checked only
    ``cover_position_y`` in a PATCH response and never re-fetched, so a read
    path that dropped X would have gone unnoticed.
    """
    token, cid = _creator(client, "cvr_get@test.com", "cvrget")

    _reposition(client, token, cid, 0.3, 0.7)

    body = client.get(f"/characters/{cid}", headers=auth_headers(token)).json()
    assert body["cover_position_x"] == 0.3
    assert body["cover_position_y"] == 0.7


def test_public_home_returns_framing_written_through_the_api(client, db_session):
    """The public Home renders from the same stored fractions.

    Complements the existing public-home coverage, which writes the columns
    directly: this one arrives through the real reposition endpoint, so it
    pins the whole write-then-publish-then-read path rather than the
    serializer alone.
    """
    from app.models.character import Character

    token, cid = _creator(client, "cvr_pub@test.com", "cvrpub")
    _reposition(client, token, cid, 0.25, 0.75)

    row = db_session.query(Character).filter(Character.id == cid).first()
    row.public_home_enabled = True
    db_session.commit()

    body = client.get(f"/characters/{cid}/public-home").json()
    assert body["cover_position_x"] == 0.25
    assert body["cover_position_y"] == 0.75
