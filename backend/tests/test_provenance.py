"""Evidence-based provenance — the badge must be earned, not asserted.

Covers the four properties the sprint exists to establish:

1. A client cannot choose its own badge.
2. "Written in Ficshon" requires a composition session the server issued.
3. Ficshon's own AI output is recognised when it is pasted back in, whatever
   the client claims about how it was typed.
4. Publishing carries provenance across instead of discarding it.
"""
from datetime import datetime, timedelta

import pytest

from app.models.provenance import Provenance
from app.services import text_fingerprint
from app.services.provenance import register_ai_output, rollup
from tests.conftest import auth_headers, get_auth_token


# ── helpers ───────────────────────────────────────────────────────────────────

def _character_for(client, token):
    resp = client.post("/characters/", json={"name": "ProvChar"}, headers=auth_headers(token))
    if resp.status_code == 201:
        return resp.json()["id"]
    owned = client.get("/characters/", headers=auth_headers(token))
    assert owned.json(), "no character available"
    return owned.json()[0]["id"]


def _commons_realm(client, token):
    resp = client.get("/realms/?public_only=true", headers=auth_headers(token))
    assert resp.status_code == 200, resp.text
    for realm in resp.json():
        if realm.get("is_commons"):
            return realm["id"]
    created = client.post(
        "/realms/",
        json={"name": "Prov Realm", "slug": "prov-realm", "is_public": True},
        headers=auth_headers(token),
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _open_session(client, token, surface="commons_composer", **kwargs):
    resp = client.post(
        "/composition/sessions",
        json={"surface": surface, "target_kind": "post", **kwargs},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _report_metrics(client, token, session_id, **metrics):
    base = {
        "typed_chars": 0,
        "inserted_chars": 0,
        "internal_insert_chars": 0,
        "largest_insertion": 0,
        "insertion_count": 0,
        "edit_duration_ms": 0,
    }
    base.update(metrics)
    resp = client.patch(
        f"/composition/sessions/{session_id}",
        json={"metrics": base},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200, resp.text


def _post(client, token, realm_id, content, **extra):
    resp = client.post(
        f"/posts/realms/{realm_id}/posts",
        json={"content": content, "character_id": _character_for(client, token), **extra},
        headers=auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# A passage long enough to fingerprint (the matcher ignores anything under
# MIN_WORDS, so a short string would prove nothing).
AI_TEXT = " ".join(
    f"the lantern guttered against {w} glass and the harbour went quiet beneath it"
    for w in ["salt", "black", "cold", "old", "grey", "thin", "wet", "pale"]
)


# ── 1. the client cannot choose its own badge ─────────────────────────────────

def test_client_cannot_forge_the_badge(client):
    """A submitted ``source_type`` is ignored — it is not even a field any more."""
    token = get_auth_token(client, email="forge@test.com", username="forgeuser")
    realm = _commons_realm(client, token)

    post = _post(client, token, realm, "Trying to claim a badge.", source_type="user")

    assert "source_type" not in post
    # No session was supplied, so the honest answer is that nothing is known.
    assert post["provenance"] == Provenance.EXTERNAL.value


def test_no_session_yields_unknown_not_user_written(client):
    """The old default asserted authorship for every post. It must not any more."""
    token = get_auth_token(client, email="nosession@test.com", username="nosessionuser")
    realm = _commons_realm(client, token)

    post = _post(client, token, realm, "Posted straight at the API.")

    assert post["provenance"] == Provenance.EXTERNAL.value


# ── 2. written in Ficshon requires a session ──────────────────────────────────

def test_typed_in_editor_earns_user_written(client):
    token = get_auth_token(client, email="typed@test.com", username="typeduser")
    realm = _commons_realm(client, token)
    content = "I wrote every word of this in the composer."

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=len(content), edit_duration_ms=45_000)

    post = _post(client, token, realm, content, composition_session_id=session)

    assert post["provenance"] == Provenance.USER_WRITTEN.value


def test_metrics_that_contradict_the_content_are_discarded(client):
    """Under-reported counters cannot buy a badge — the server has the text."""
    token = get_auth_token(client, email="liar@test.com", username="liaruser")
    realm = _commons_realm(client, token)
    content = "x" * 4000

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=5)

    post = _post(client, token, realm, content, composition_session_id=session)

    assert post["provenance"] == Provenance.EXTERNAL.value


def test_a_session_with_no_reported_typing_earns_nothing(client):
    """Opening a session must not be enough on its own.

    Short posts fit inside the consistency slack, so without a positive
    typing requirement a silent session would hand out the badge by default —
    which is the defect this sprint exists to remove.
    """
    token = get_auth_token(client, email="silent@test.com", username="silentuser")
    realm = _commons_realm(client, token)

    session = _open_session(client, token)
    post = _post(client, token, realm, "hi", composition_session_id=session)

    assert post["provenance"] == Provenance.EXTERNAL.value


def test_externally_pasted_text_is_not_user_written(client):
    token = get_auth_token(client, email="paster@test.com", username="pasteruser")
    realm = _commons_realm(client, token)
    content = "y" * 2000

    session = _open_session(client, token)
    _report_metrics(
        client, token, session,
        typed_chars=20, inserted_chars=1980, insertion_count=1, largest_insertion=1980,
    )

    post = _post(client, token, realm, content, composition_session_id=session)

    assert post["provenance"] != Provenance.USER_WRITTEN.value


def test_external_paste_is_recorded_distinguishably(client, db_session):
    """The verdict is EXTERNAL, and the evidence still records *why*.

    The distinct bases no longer change the public statement, but they are what
    a future rule version would re-decide on, so they must survive."""
    from app.models.post import Post as PostModel

    token = get_auth_token(client, email="extbasis@test.com", username="extbasisuser")
    realm = _commons_realm(client, token)
    content = "z" * 2000

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=10, inserted_chars=1990, insertion_count=1)
    created = _post(client, token, realm, content, composition_session_id=session)

    db_session.expire_all()
    row = db_session.query(PostModel).filter(PostModel.id == created["id"]).first()
    assert row.provenance_evidence["basis"] == "external_insertion"
    from app.services.provenance import RULE_VERSION
    assert row.provenance_rule_version == RULE_VERSION


def test_a_session_cannot_be_redeemed_twice(client):
    """Single-use, so one evidenced session cannot launder a second post."""
    token = get_auth_token(client, email="replay@test.com", username="replayuser")
    realm = _commons_realm(client, token)
    content = "Written once, in the composer."

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=len(content))

    first = _post(client, token, realm, content, composition_session_id=session)
    second = _post(client, token, realm, content, composition_session_id=session)

    assert first["provenance"] == Provenance.USER_WRITTEN.value
    assert second["provenance"] == Provenance.EXTERNAL.value


def test_another_users_session_is_not_usable(client):
    token_a = get_auth_token(client, email="owner_a@test.com", username="owneruser")
    token_b = get_auth_token(client, email="thief_b@test.com", username="thiefuser")
    realm = _commons_realm(client, token_b)
    content = "Borrowing someone else's evidence."

    session = _open_session(client, token_a)
    _report_metrics(client, token_a, session, typed_chars=len(content))

    post = _post(client, token_b, realm, content, composition_session_id=session)

    assert post["provenance"] == Provenance.EXTERNAL.value


def test_expired_session_is_refused(client, db_session):
    from app.models.composition import CompositionSession

    token = get_auth_token(client, email="stale@test.com", username="staleuser")
    realm = _commons_realm(client, token)
    content = "Composed a very long time ago."

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=len(content))

    db_session.expire_all()
    row = db_session.query(CompositionSession).filter(CompositionSession.id == session).first()
    row.created_at = datetime.utcnow() - timedelta(days=3)
    db_session.commit()

    post = _post(client, token, realm, content, composition_session_id=session)

    assert post["provenance"] == Provenance.EXTERNAL.value


def test_internal_handoff_is_credited_only_up_to_the_parent(client):
    """WriteSpace → composer paste is genuine writing, but the credit is bounded
    by what the parent session was independently seen to type."""
    token = get_auth_token(client, email="handoff@test.com", username="handoffuser")
    realm = _commons_realm(client, token)
    content = "w" * 1200

    parent = _open_session(client, token, surface="workspace")
    _report_metrics(client, token, parent, typed_chars=1200, edit_duration_ms=600_000)

    child = _open_session(client, token, continues_session_id=parent)
    _report_metrics(
        client, token, child,
        typed_chars=0, inserted_chars=1200, internal_insert_chars=1200, insertion_count=1,
    )

    post = _post(client, token, realm, content, composition_session_id=child)

    assert post["provenance"] == Provenance.USER_WRITTEN.value


def test_handoff_credit_cannot_exceed_what_the_parent_typed(client):
    token = get_auth_token(client, email="overclaim@test.com", username="overclaimuser")
    realm = _commons_realm(client, token)
    content = "v" * 2000

    parent = _open_session(client, token, surface="workspace")
    _report_metrics(client, token, parent, typed_chars=50)

    child = _open_session(client, token, continues_session_id=parent)
    _report_metrics(
        client, token, child,
        typed_chars=0, inserted_chars=2000, internal_insert_chars=2000, insertion_count=1,
    )

    post = _post(client, token, realm, content, composition_session_id=child)

    assert post["provenance"] != Provenance.USER_WRITTEN.value


# ── 3. Ficshon's own AI output is recognised ──────────────────────────────────

def test_pasted_ai_output_is_labelled_despite_a_clean_session(client, db_session):
    """The gap the sprint was called to close: generate in StoryLab, copy, post.

    The client here reports a perfectly typed session. Server-held evidence wins.
    """
    from app.models.user import User as UserModel

    token = get_auth_token(client, email="genpaste@test.com", username="genpasteuser")
    realm = _commons_realm(client, token)

    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == "genpaste@test.com").first()
    register_ai_output(
        db_session,
        user_id=user.id,
        text=AI_TEXT,
        source_kind="storylab_chapter",
        source_ref="story-1#1",
    )
    db_session.commit()

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=len(AI_TEXT), edit_duration_ms=900_000)

    post = _post(client, token, realm, AI_TEXT, composition_session_id=session)

    assert post["provenance"] == Provenance.AI_ASSISTED.value


def test_fingerprints_are_author_scoped(client, db_session):
    """One user's generations never label another user's post."""
    from app.models.user import User as UserModel

    token_a = get_auth_token(client, email="gen_a@test.com", username="genauser")
    token_b = get_auth_token(client, email="gen_b@test.com", username="genbuser")
    realm = _commons_realm(client, token_b)

    db_session.expire_all()
    user_a = db_session.query(UserModel).filter(UserModel.email == "gen_a@test.com").first()
    register_ai_output(
        db_session, user_id=user_a.id, text=AI_TEXT, source_kind="storylab_chapter"
    )
    db_session.commit()

    session = _open_session(client, token_b)
    _report_metrics(client, token_b, session, typed_chars=len(AI_TEXT))

    post = _post(client, token_b, realm, AI_TEXT, composition_session_id=session)

    assert post["provenance"] == Provenance.USER_WRITTEN.value


def test_original_writing_is_not_flagged_by_a_brief_ai_quote(client, db_session):
    """A short quotation inside a long original post must not relabel it."""
    from app.models.user import User as UserModel

    token = get_auth_token(client, email="quoter@test.com", username="quoteruser")
    realm = _commons_realm(client, token)

    db_session.expire_all()
    user = db_session.query(UserModel).filter(UserModel.email == "quoter@test.com").first()
    register_ai_output(
        db_session, user_id=user.id, text=AI_TEXT, source_kind="storylab_chapter"
    )
    db_session.commit()

    original = " ".join(
        f"she counted {n} steps down to the water and none of them were hers"
        for n in range(60)
    )
    content = AI_TEXT[:120] + " " + original

    session = _open_session(client, token)
    _report_metrics(client, token, session, typed_chars=len(content))

    post = _post(client, token, realm, content, composition_session_id=session)

    assert post["provenance"] == Provenance.USER_WRITTEN.value


# ── 4. publishing carries provenance across ───────────────────────────────────

def test_publish_inherits_and_rolls_up_provenance(client, db_session):
    from app.models.story_space import StorySpacePost

    token = get_auth_token(client, email="publisher@test.com", username="publisheruser")
    _character_for(client, token)  # creator entitlement

    space = client.post(
        "/story-spaces/", json={"name": "Prov Space"}, headers=auth_headers(token)
    )
    assert space.status_code == 201, space.text
    space_id = space.json()["id"]
    story_channel = next(
        c for c in space.json()["channels"] if c["channel_type"] == "story"
    )

    def _space_post(content, session_id=None):
        payload = {"content": content, "content_type": "ic"}
        if session_id:
            payload["composition_session_id"] = session_id
        resp = client.post(
            f"/story-spaces/{space_id}/channels/{story_channel['id']}/posts",
            json=payload,
            headers=auth_headers(token),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    typed = "Every word of this beat was typed in the channel."
    session = _open_session(client, token, surface="story_space")
    _report_metrics(client, token, session, typed_chars=len(typed))
    clean = _space_post(typed, session)
    assert clean["provenance"] == Provenance.USER_WRITTEN.value

    assisted = _space_post("A second beat with no evidence at all.")

    # Force the second post to AI_ASSISTED to exercise the roll-up.
    db_session.expire_all()
    row = db_session.query(StorySpacePost).filter(StorySpacePost.id == assisted["id"]).first()
    row.provenance = Provenance.AI_ASSISTED.value
    db_session.commit()

    published = client.post(
        f"/story-spaces/{space_id}/publish",
        json={"title": "Rolled Up", "post_ids": [clean["id"], assisted["id"]]},
        headers=auth_headers(token),
    )
    assert published.status_code == 201, published.text
    data = published.json()

    # Worst case wins at the story level; segments keep their own truth.
    assert data["provenance"] == Provenance.AI_ASSISTED.value
    by_position = {s["position"]: s["provenance"] for s in data["segments"]}
    assert by_position[1] == Provenance.USER_WRITTEN.value
    assert by_position[2] == Provenance.AI_ASSISTED.value


# ── unit: fingerprint symmetry and roll-up precedence ─────────────────────────

def test_fingerprint_matches_a_passage_inside_a_larger_document():
    """Sampling must be symmetric, or a paste would never match its source."""
    document = AI_TEXT + " " + " ".join(f"and then nothing happened at all for {n} days" for n in range(40))
    passage_hashes = text_fingerprint.fingerprint(AI_TEXT)
    document_hashes = set(text_fingerprint.fingerprint(document))

    matched, ratio = text_fingerprint.overlap(passage_hashes, document_hashes)

    assert matched > 0
    assert ratio > 0.5


def test_short_text_is_not_fingerprinted():
    assert text_fingerprint.fingerprint("Too short to attribute.") == []


def test_fingerprint_ignores_case_and_whitespace():
    a = text_fingerprint.fingerprint(AI_TEXT)
    b = text_fingerprint.fingerprint(AI_TEXT.upper().replace(" ", "\n  "))
    assert a == b


@pytest.mark.parametrize(
    "states, expected",
    [
        (["user_written", "user_written"], Provenance.USER_WRITTEN),
        (["user_written", "ai_assisted"], Provenance.AI_ASSISTED),
        (["user_written", "unknown"], Provenance.UNKNOWN),   # legacy row preserved as stored
        (["unknown", "ai_assisted"], Provenance.AI_ASSISTED),
        ([], Provenance.EXTERNAL),
    ],
)
def test_rollup_precedence(states, expected):
    assert rollup(states).verdict == expected


# ── three states, and only three ──────────────────────────────────────────────

def test_rules_never_emit_unknown(client):
    """UNKNOWN is legacy storage only — no decision may produce it.

    The guard that enforces this lives in the service; this pins the intent so a
    future rule change cannot quietly reintroduce an unbadged state.
    """
    from app.services.provenance import EMITTED_VERDICTS

    assert Provenance.UNKNOWN not in EMITTED_VERDICTS
    assert EMITTED_VERDICTS == {
        Provenance.USER_WRITTEN,
        Provenance.AI_ASSISTED,
        Provenance.EXTERNAL,
    }


def test_pasted_from_outside_is_written_elsewhere(client):
    """The Notepad case: copied in from another application, nothing typed."""
    token = get_auth_token(client, email="notepad@test.com", username="notepaduser")
    realm = _commons_realm(client, token)
    body = "Text composed in another application entirely and pasted in whole."

    session = _open_session(client, token)
    _report_metrics(
        client, token, session,
        typed_chars=0, inserted_chars=len(body), insertion_count=1,
        largest_insertion=len(body), edit_duration_ms=900,
    )
    post = _post(client, token, realm, body, composition_session_id=session)

    assert post["provenance"] == Provenance.EXTERNAL.value


def test_seeded_content_is_written_elsewhere(db_session):
    """Editorial seed posts were never composed in Ficshon either."""
    from app.services.provenance import not_composed_here

    decision = not_composed_here("starter_seed")
    assert decision.verdict == Provenance.EXTERNAL
    assert decision.evidence["basis"] == "not_composed_here"


def test_rp_partner_import_is_written_elsewhere():
    from app.services.provenance import external_import

    assert external_import("rp_partner").verdict == Provenance.EXTERNAL
