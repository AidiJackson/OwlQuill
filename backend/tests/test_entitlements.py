"""Unit tests for the creator-tool entitlement helpers.

These exist so the Writer unlock has a harness to change against: when the rule
moves from "owns a character" to "has the Writer entitlement", these tests are
where the new expectations land — and the guard against the two helpers being
silently merged lives here too.

The second half covers the ROUTE GUARDS. The frontend hides creator workspaces
from Wanderers, but a hidden nav link is not access control — every guarded
mutation must refuse on its own, so these hit the endpoints directly.
"""
import pytest

from app.core.entitlements import can_use_creator_tools, has_acting_character
from tests.conftest import get_auth_token, auth_headers


def _make_character(db_session, owner_id, name="C"):
    from app.models.character import Character
    c = Character(owner_id=owner_id, name=name, species="human")
    db_session.add(c)
    db_session.commit()
    return c


def _make_user(db_session, email, username, **flags):
    from app.models.user import User
    from app.core.security import get_password_hash
    u = User(
        email=email, username=username,
        hashed_password=get_password_hash("x"),
        **flags,
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    return u


def test_plain_wanderer_is_not_a_creator(db_session):
    u = _make_user(db_session, "w@e.com", "w")
    assert can_use_creator_tools(db_session, u) is False
    assert has_acting_character(db_session, u) is False


def test_owning_a_character_grants_creator_tools(db_session):
    u = _make_user(db_session, "o@e.com", "o")
    _make_character(db_session, u.id)
    assert can_use_creator_tools(db_session, u) is True
    assert has_acting_character(db_session, u) is True


def test_admin_without_character_can_use_creator_tools(db_session):
    u = _make_user(db_session, "a@e.com", "a", is_admin=True)
    assert can_use_creator_tools(db_session, u) is True


def test_seeder_without_character_can_use_creator_tools(db_session):
    u = _make_user(db_session, "s@e.com", "s", is_seeder=True)
    assert can_use_creator_tools(db_session, u) is True


def test_zero_character_admin_has_no_acting_character(db_session):
    """The two helpers must NOT be equivalent. An admin with no character can
    open creator tools but has nothing to *act as* — merging them would grant a
    character-to-character action with no character behind it."""
    u = _make_user(db_session, "a2@e.com", "a2", is_admin=True)
    assert can_use_creator_tools(db_session, u) is True
    assert has_acting_character(db_session, u) is False


# ── Route guards: require_creator must refuse Wanderers ─────────────────────

#: Every creator mutation carrying ``dependencies=[Depends(require_creator)]``
#: that is NOT already character-scoped. (Character-scoped routes are gated a
#: second time by ownership, so a Wanderer cannot reach them at all.)
#:
#: Payloads are deliberately minimal: the guard runs as a route dependency,
#: before the endpoint's own body validation, so an incomplete body must still
#: produce 403 rather than 422. That ordering IS the property under test — if it
#: ever inverts, a Wanderer learns the request shape of a workspace they have no
#: access to.
GUARDED_MUTATIONS = [
    ("/images/generate", {"prompt": "anything"}),
    ("/storylab/generate", {}),
    ("/storylab/stories", {}),
    ("/storylab/rp-reply/generate", {}),
    ("/story-spaces/", {}),
    ("/rp-stories", {}),
]


@pytest.mark.parametrize("path,payload", GUARDED_MUTATIONS, ids=lambda v: v if isinstance(v, str) else "")
def test_wanderer_is_refused_by_every_creator_mutation(client, path, payload):
    wanderer = get_auth_token(client, email="guard-w@test.com", username="guardw")
    resp = client.post(path, json=payload, headers=auth_headers(wanderer))
    assert resp.status_code == 403, f"{path} returned {resp.status_code}: {resp.text}"


@pytest.mark.parametrize("path,payload", GUARDED_MUTATIONS, ids=lambda v: v if isinstance(v, str) else "")
def test_creator_gets_past_the_guard(client, path, payload):
    """The mirror of the above: a character owner must NOT be stopped by the
    entitlement. Any non-403 status is a pass — these deliberately-thin bodies
    will often fail validation downstream, which is the endpoint's business,
    not the guard's. Without this direction the guard could return 403 for
    everyone and the refusal tests above would still be green.
    """
    creator = get_auth_token(client, email="guard-c@test.com", username="guardc")
    resp = client.post(
        "/characters/",
        json={"name": "Guardian", "species": "human", "visibility": "public"},
        headers=auth_headers(creator),
    )
    assert resp.status_code == 201, resp.text

    resp = client.post(path, json=payload, headers=auth_headers(creator))
    assert resp.status_code != 403, f"{path} refused a character owner: {resp.text}"
