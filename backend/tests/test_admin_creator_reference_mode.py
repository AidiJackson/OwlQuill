"""Deliberate reference mode — Admin Creator's reference-driven generation.

Admin Creator offers four reference cards and means them: those cards and the
prompt ARE the brief. Before this mode existed a canon-complete character filled
the six-reference provider budget on its own and every hand-picked card was
dropped (observed for character 58: ``budget=6 canon=6 manual_selected=2
manual_sent=0``), which made the four cards decorative.

``reference_mode`` isolates the two workflows, and this file pins both halves:

* the Image Generator on /images names no mode, gets ``augment``, and behaves
  byte-for-byte as it always has — canon compiled, canon references routed
  first, cards in whatever capacity is left;
* Admin Creator names ``deliberate`` and canon is BYPASSED: not queried, not
  compiled, not routed, not required to be complete, and not verified against.
  The selected character is an ownership and storage destination only.

The bypass is proved by call counts on ``route_canon_refs`` and
``compile_canon_prompt`` rather than by the absence of canon-looking bytes — an
empty payload could mean the router ran and chose nothing, which is a different
thing and would still be wrong.

The manual-first branch in ``merge_reference_sets`` is retained as a safety net
against a regression of that bypass, so its unit tests below still exercise
canon and manual together even though the live pipeline never presents that
combination in deliberate mode.

Everything here is NON-SPENDING: providers are mocked and reference bytes are
synthesised, so no image is ever generated and no provider is ever called for
real. Canon is snapshotted before and after the end-to-end runs — a deliberate
generation must change what is SENT and nothing that is STORED.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.manual_references import (
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    merge_reference_sets,
    normalise_reference_mode,
)
from tests.canon_test_utils import setup_canon, stub_png_bytes
from tests.conftest import TestingSessionLocal, auth_headers, get_auth_token

PIPELINE = "app.services.image_generation_pipeline"


# ── Helpers ──────────────────────────────────────────────────────────────────


class _Ref:
    """Stand-in for a ResolvedReference — the merge reads only these two."""

    def __init__(self, i: int) -> None:
        self.image_id = i
        self.file_path = f"m{i}.png"


def _canon(n: int) -> list[str]:
    """``n`` canon URLs in router priority order."""
    return [f"c{i}.png" for i in range(n)]


def _png() -> bytes:
    return stub_png_bytes()


def _make_seeder(email: str) -> None:
    from app.models.user import User

    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        user.is_seeder = True
        user.is_admin = False
        db.commit()
    finally:
        db.close()


def _create_character(client, token: str, name: str = "Deliberate Test") -> int:
    resp = client.post(
        "/characters/", json={"name": name, "species": "human"}, headers=auth_headers(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _upload(client, token: str, cid: int):
    return client.post(
        f"/characters/{cid}/images/upload",
        files={"file": ("ref.png", _png(), "image/png")},
        headers=auth_headers(token),
    )


def _generate(client, token: str, cid: int, body: dict):
    return client.post(
        f"/characters/{cid}/image-generator/generate",
        json=body,
        headers=auth_headers(token),
    )


def _mock_provider():
    from app.services.provider_capabilities import Capability

    provider = MagicMock()
    provider.capabilities = frozenset(
        {Capability.TEXT_TO_IMAGE, Capability.IMAGE_GUIDANCE, Capability.MULTI_IMAGE_ANCHORS}
    )
    provider.generate_with_anchors = MagicMock(return_value=_png())
    provider.generate_grounded_image = MagicMock(return_value=_png())
    provider.generate_image = MagicMock(return_value=_png())
    provider.model_name = "mock-model"
    return provider


def _scene_meta(slots: list[str]):
    from app.services.scene_router import SceneMeta

    return SceneMeta(camera="front", routed=True, route_slots=list(slots))


def _canon_snapshot(cid: int) -> tuple:
    """Every byte of a character's canon, for before/after comparison."""
    from app.models.character_identity_canon import CharacterIdentityCanon

    db = TestingSessionLocal()
    try:
        row = (
            db.query(CharacterIdentityCanon)
            .filter(CharacterIdentityCanon.character_id == cid)
            .first()
        )
        if row is None:
            return ()
        return (
            row.status,
            row.face_canon_json,
            row.body_canon_json,
            row.accessories_json,
            row.face_locked,
            row.body_locked,
            row.locked_at,
        )
    finally:
        db.close()


@pytest.fixture
def founder(client):
    """A seeder account (Lauren's shape) owning a canon-complete character."""
    token = get_auth_token(client, email="deliberate@example.com", username="deliberateacct")
    _make_seeder("deliberate@example.com")
    cid = _create_character(client, token)
    db = TestingSessionLocal()
    try:
        setup_canon(db, cid)
    finally:
        db.close()
    return token, cid


# ── 1. The merge policy itself (pure, no provider, no spend) ─────────────────


class TestMergePolicy:
    def test_default_is_unchanged_canon_first_behaviour(self):
        """No mode named → exactly the policy /images has always had."""
        canon, manual = _canon(6), [_Ref(i) for i in range(4)]

        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6
        )
        assert ordered == canon, "canon survives intact and fills the budget"
        assert sent == []
        assert [r.image_id for r in dropped] == [0, 1, 2, 3], "every card dropped, reported"

        # Explicitly naming augment must be identical to not naming a mode.
        assert merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode=REFERENCE_MODE_AUGMENT
        )[0] == ordered

    def test_deliberate_four_cards_against_full_canon(self):
        """4 manual + 6 canon → 4 manual, then the 2 highest-priority canon."""
        canon, manual = _canon(6), [_Ref(i) for i in range(4)]
        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        assert ordered == ["m0.png", "m1.png", "m2.png", "m3.png", "c0.png", "c1.png"]
        assert [r.image_id for r in sent] == [0, 1, 2, 3], "no card dropped"
        assert dropped == []
        assert len(ordered) == 6, "the budget is still the budget"

    def test_deliberate_two_cards_leave_four_canon(self):
        canon, manual = _canon(6), [_Ref(i) for i in range(2)]
        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        assert ordered == ["m0.png", "m1.png", "c0.png", "c1.png", "c2.png", "c3.png"]
        assert [r.image_id for r in sent] == [0, 1]
        assert dropped == []

    @pytest.mark.parametrize("cards,expected_canon", [(1, 5), (3, 3), (4, 2)])
    def test_deliberate_canon_takes_exactly_what_is_left(self, cards, expected_canon):
        canon, manual = _canon(6), [_Ref(i) for i in range(cards)]
        ordered, sent, _ = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        assert len(sent) == cards
        assert ordered[:cards] == [r.file_path for r in manual]
        assert ordered[cards:] == canon[:expected_canon]

    def test_deliberate_with_no_cards_is_plain_canon(self):
        """An empty board must not disturb canon routing at all."""
        canon = _canon(6)
        deliberate = merge_reference_sets(
            canon_urls=canon, manual=[], budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        augment = merge_reference_sets(canon_urls=canon, manual=[], budget=6)
        assert deliberate == augment
        assert deliberate[0] == canon

    def test_deliberate_below_full_canon_keeps_every_canon_reference(self):
        """Nothing is displaced when the cards fit in the spare capacity."""
        canon, manual = _canon(2), [_Ref(i) for i in range(4)]
        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        assert ordered == ["m0.png", "m1.png", "m2.png", "m3.png", "c0.png", "c1.png"]
        assert len(sent) == 4 and dropped == []

    def test_card_order_is_preserved_exactly(self):
        """Card order is priority order; the merge never re-sorts it."""
        manual = [_Ref(i) for i in (7, 3, 9, 1)]
        ordered, sent, _ = merge_reference_sets(
            canon_urls=_canon(6), manual=manual, budget=6, mode=REFERENCE_MODE_DELIBERATE
        )
        assert [r.image_id for r in sent] == [7, 3, 9, 1]
        assert ordered[:4] == ["m7.png", "m3.png", "m9.png", "m1.png"]

    def test_deliberate_still_reports_a_card_it_cannot_send(self):
        """A budget narrower than the board drops from the TAIL and reports it.

        The only way a card is dropped in deliberate mode: a model whose
        documented reference limit is below the number of cards filled.
        """
        canon, manual = _canon(6), [_Ref(i) for i in range(4)]
        ordered, sent, dropped = merge_reference_sets(
            canon_urls=canon, manual=manual, budget=2, mode=REFERENCE_MODE_DELIBERATE
        )
        assert ordered == ["m0.png", "m1.png"], "no canon room left, and that is reported too"
        assert [r.image_id for r in sent] == [0, 1]
        assert [r.image_id for r in dropped] == [2, 3], "dropped from the tail, in order"

    def test_unknown_mode_falls_back_to_augment(self):
        """An unrecognised mode must degrade to the safe policy, never raise."""
        assert normalise_reference_mode(None) == REFERENCE_MODE_AUGMENT
        assert normalise_reference_mode("") == REFERENCE_MODE_AUGMENT
        assert normalise_reference_mode("nonsense") == REFERENCE_MODE_AUGMENT
        assert normalise_reference_mode("deliberate") == REFERENCE_MODE_DELIBERATE

        canon, manual = _canon(6), [_Ref(0)]
        assert merge_reference_sets(
            canon_urls=canon, manual=manual, budget=6, mode="nonsense"
        )[0] == canon


# ── 2. Params round-trip (the no-migration guarantee) ────────────────────────


class TestParamsRoundTrip:
    def test_old_job_row_without_the_field_replays_as_augment(self):
        """A job queued before this field existed must not change behaviour."""
        from app.services.image_generation_pipeline import GenerationParams

        legacy = {
            "prompt": "standing in a field",
            "include_character": True,
            "provider_option": "option2",
            "is_cover": False,
            "reference_image_ids": [1, 2],
            "reference_roles": ["clothing", "environment"],
            "is_admin": False,
            "is_founder": True,
        }
        assert "reference_mode" not in legacy
        assert GenerationParams.from_json(legacy).reference_mode == REFERENCE_MODE_AUGMENT

    def test_deliberate_survives_the_json_round_trip(self):
        """The detached driver reconstructs the mode from params_json alone."""
        from app.services.image_generation_pipeline import GenerationParams

        params = GenerationParams(
            prompt="a scene", reference_mode=REFERENCE_MODE_DELIBERATE, is_founder=True
        )
        blob = params.to_json()
        assert blob["reference_mode"] == "deliberate"
        assert GenerationParams.from_json(blob).reference_mode == REFERENCE_MODE_DELIBERATE

    def test_a_corrupt_stored_mode_replays_as_augment(self):
        from app.services.image_generation_pipeline import GenerationParams

        assert (
            GenerationParams.from_json({"prompt": "x", "reference_mode": "whatever"}).reference_mode
            == REFERENCE_MODE_AUGMENT
        )

    def test_default_params_are_augment(self):
        from app.services.image_generation_pipeline import GenerationParams

        assert GenerationParams(prompt="x").reference_mode == REFERENCE_MODE_AUGMENT


# ── 3. Entitlement: only a founder may ask for deliberate ────────────────────


class TestDeliberateEntitlement:
    def test_ordinary_creator_cannot_request_deliberate_mode(self, client, db_session):
        """Refused even with no references selected: the mode alone re-budgets
        canon, so it is not merely a modifier on a selection."""
        token = get_auth_token(client, email="plain@example.com", username="plainacct")
        cid = _create_character(client, token, "Plain One")
        resp = _generate(client, token, cid, {
            "prompt": "a scene",
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 403, resp.text
        assert "founder" in resp.json()["detail"].lower()

    def test_ordinary_creator_cannot_request_deliberate_with_references(
        self, client, db_session
    ):
        token = get_auth_token(client, email="plain2@example.com", username="plain2acct")
        cid = _create_character(client, token, "Plain Two")
        resp = _generate(client, token, cid, {
            "prompt": "a scene",
            "reference_image_ids": [1],
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 403, resp.text

    def test_ordinary_creator_may_still_generate_without_a_mode(self, client, db_session):
        """The gate must not catch the ordinary path it does not apply to."""
        token = get_auth_token(client, email="plain3@example.com", username="plain3acct")
        cid = _create_character(client, token, "Plain Three")
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider):
            resp = _generate(client, token, cid, {"prompt": "a scene"})
        assert resp.status_code == 200, resp.text

    def test_an_invented_mode_is_rejected_outright(self, client, founder):
        token, cid = founder
        resp = _generate(client, token, cid, {
            "prompt": "a scene",
            "reference_mode": "canon_only",
        })
        assert resp.status_code == 422, resp.text


# ── 4. End to end: what actually reaches the provider ────────────────────────


class TestProviderPayload:
    """The provider payload, captured verbatim, with canon routing available.

    ``route_canon_refs`` is patched to hand back six canon references. Under
    ``augment`` those are what the provider gets; under ``deliberate`` the router
    is never called at all, and these tests assert that directly rather than
    inferring it from the payload.

    ``load_image_bytes`` is patched to a URL→bytes function so every reference is
    byte-distinct and identifiable in the captured anchor list. That is what
    makes an ORDERING assertion possible: the real stub PNGs are byte-identical
    to each other and would collapse under the pipeline's dedup pass.
    """

    CANON_URLS = [f"/static/canon/slot{i}.png" for i in range(6)]

    @staticmethod
    def _bytes_for(url: str) -> bytes:
        return f"BYTES::{url}".encode()

    def _run(self, client, token, cid, body, *, load=None, canon_urls=None):
        """Run one generation and report what the provider saw.

        Returns ``(response, captured, spies)``. ``spies`` holds the canon entry
        points, so "deliberate never consults canon" is provable as a call count
        rather than as an absence of canon-looking bytes.
        """
        from app.services.canon_compiler import compile_canon_prompt as _real_compile

        provider = _mock_provider()
        captured: dict = {}
        provider.generate_with_anchors = MagicMock(
            side_effect=lambda *, prompt, anchor_images, **kw: (
                captured.update(prompt=prompt, anchors=list(anchor_images)) or _png()
            )
        )
        # A board with no cards and no canon reaches the provider with no
        # references at all — that is the text-only path, and it carries the
        # prompt this suite still needs to inspect.
        provider.generate_image = MagicMock(
            side_effect=lambda *, prompt, **kw: (
                captured.update(prompt=prompt, anchors=[]) or _png()
            )
        )

        urls = list(self.CANON_URLS if canon_urls is None else canon_urls)
        route = MagicMock(return_value=(urls, _scene_meta([f"slot{i}" for i in range(len(urls))])))
        compile_spy = MagicMock(side_effect=_real_compile)

        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider), \
             patch(f"{PIPELINE}.route_canon_refs", route), \
             patch(f"{PIPELINE}.compile_canon_prompt", compile_spy), \
             patch(f"{PIPELINE}.load_image_bytes", side_effect=load or self._bytes_for):
            resp = _generate(client, token, cid, body)
        return resp, captured, {"route": route, "compile": compile_spy, "provider": provider}

    def _sent_urls(self, captured) -> list[str]:
        return [b.decode().removeprefix("BYTES::") for b in captured["anchors"]]

    # ── deliberate: the cards and nothing else ───────────────────────────────

    def test_only_the_cards_reach_the_provider(self, client, founder):
        """Four cards, six canon references available, and canon contributes
        nothing: not a reference, not a prompt clause, not a router call."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(4)]
        paths = self._paths_for(ids)

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": False,
            "reference_image_ids": ids,
            "reference_roles": ["character_appearance", "clothing", "environment", "other"],
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 200, resp.text

        assert self._sent_urls(captured) == [paths[i] for i in ids], \
            "exactly the four cards, in card order, and nothing else"
        spies["route"].assert_not_called()
        spies["compile"].assert_not_called()

        meta = resp.json()["metadata_json"]
        assert meta["reference_mode"] == "deliberate"
        assert meta["canon_bypassed"] is True
        assert meta["canon_bypass_reason"] == "deliberate_reference_mode"
        assert meta["canon_used"] is False
        assert meta["canon_refs_sent"] == 0
        assert meta["canon_refs_dropped"] == 0
        assert meta["manual_refs_sent"] == 4
        assert meta["manual_refs_dropped"] == 0
        assert meta["refs_source"] == "manual"

    def test_card_order_and_roles_survive_to_the_provider(self, client, founder):
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(3)]
        paths = self._paths_for(ids)
        # Deliberately not ascending id order — the BOARD's order is the one
        # that must survive.
        ordered = [ids[2], ids[0], ids[1]]

        resp, captured, _ = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": False,
            "reference_image_ids": ordered,
            "reference_roles": ["clothing", "environment", "other"],
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 200, resp.text
        assert self._sent_urls(captured) == [paths[i] for i in ordered]

        # Roles are numbered by payload position, and card 1 is position 1
        # because nothing precedes the manual block any more.
        prompt = captured["prompt"]
        # Deliberate mode uses the fuller role vocabulary — the sentences that
        # say what each card is NOT authority for. Their exact wording is pinned
        # in test_admin_creator_reference_roles.py; here we only check that the
        # numbering follows card order.
        assert "Reference image 1 is the clothing and outfit to reproduce" in prompt
        assert "Reference image 2 is the environment" in prompt
        assert "Reference image 3 is an additional visual reference" in prompt

        audit = resp.json()["metadata_json"]["manual_refs"]
        assert [a["image_id"] for a in audit] == ordered
        assert [a["role"] for a in audit] == ["clothing", "environment", "other"]
        assert all(a["sent"] for a in audit)

    def test_the_prompt_carries_no_canon_clauses(self, client, founder):
        """The founder's words plus role notes. No compiled canon, and no
        canon-precedence clause — there is no canon to defer to."""
        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": False,
            "reference_image_ids": [image_id],
            "reference_roles": ["clothing"],
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 200, resp.text
        prompt = captured["prompt"]
        assert prompt.startswith("standing in a field")
        assert "never override that identity" not in prompt
        assert "sharp angular jaw" not in prompt, "the fixture's canon face description"
        assert "athletic build" not in prompt, "the fixture's canon body description"
        spies["compile"].assert_not_called()

    def test_an_empty_board_sends_no_references_at_all(self, client, founder):
        token, cid = founder
        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "an empty room",
            "include_character": False,
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 200, resp.text
        assert captured["anchors"] == []
        spies["route"].assert_not_called()
        meta = resp.json()["metadata_json"]
        assert meta["refs_source"] == "none"
        assert meta["canon_bypassed"] is True

    def test_a_character_with_no_canon_still_works(self, client):
        """Deliberate mode must not require canon. Before the bypass this raised
        409 "Character canon incomplete" and the founder could not generate at
        all against a fresh character."""
        token = get_auth_token(client, email="nocanon@example.com", username="nocanonacct")
        _make_seeder("nocanon@example.com")
        cid = _create_character(client, token, "No Canon At All")
        image_id = _upload(client, token, cid).json()["id"]

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": False,
            "reference_image_ids": [image_id],
            "reference_mode": "deliberate",
        }, canon_urls=[])
        assert resp.status_code == 200, resp.text
        assert len(captured["anchors"]) == 1
        spies["route"].assert_not_called()
        spies["compile"].assert_not_called()

    def test_include_character_true_cannot_re_enable_canon(self, client, founder):
        """A broken or stale client sending include_character=true alongside
        deliberate must NOT get canon back. The server decides."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(2)]
        paths = self._paths_for(ids)

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": True,       # the client lying, or out of date
            "reference_image_ids": ids,
            "reference_mode": "deliberate",
        })
        assert resp.status_code == 200, resp.text
        assert self._sent_urls(captured) == [paths[i] for i in ids]
        spies["route"].assert_not_called()
        spies["compile"].assert_not_called()
        meta = resp.json()["metadata_json"]
        assert meta["canon_bypassed"] is True
        assert meta["canon_used"] is False
        assert meta["canon_refs_sent"] == 0

    def test_canon_dependent_verification_never_runs(self, client, founder):
        """Face and mark verification are canon-dependent, so a deliberate
        generation must not invoke them — they would have no canon to verify
        against, and each face-verify retry is another paid provider call."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(2)]

        with patch(f"{PIPELINE}._verify_and_regenerate") as face_verify, \
             patch("app.services.mark_verifier.verify_mark_regions") as mark_verify, \
             patch.object(settings, "IDENTITY_FACE_VERIFY", True), \
             patch.object(settings, "CANON_MARK_VERIFY", True):
            resp, _captured, spies = self._run(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": True,
                "reference_image_ids": ids,
                "reference_mode": "deliberate",
            })
        assert resp.status_code == 200, resp.text
        face_verify.assert_not_called()
        mark_verify.assert_not_called()
        spies["route"].assert_not_called()

    # ── augment: /images, unchanged ──────────────────────────────────────────

    def test_images_generator_behaviour_is_unchanged(self, client, founder):
        """The same four cards with no mode: canon takes the whole budget, every
        card is dropped and reported. This is the character-58 behaviour, kept
        deliberately — it is what /images does and must keep doing."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(4)]

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": True,
            "reference_image_ids": ids,
        })
        assert resp.status_code == 200, resp.text
        assert self._sent_urls(captured) == self.CANON_URLS, "canon takes the whole budget"
        spies["route"].assert_called_once()
        spies["compile"].assert_called_once()

        meta = resp.json()["metadata_json"]
        assert meta["reference_mode"] == "augment"
        assert meta["canon_bypassed"] is False
        assert meta["canon_bypass_reason"] is None
        assert meta["canon_used"] is True
        assert meta["manual_refs_sent"] == 0
        assert meta["manual_refs_dropped"] == 4
        assert meta["canon_refs_dropped"] == 0
        assert meta["manual_ref_policy"] == "canon_first_manual_appended_tail_trimmed"

    def test_augment_still_appends_cards_behind_canon(self, client, founder):
        """Two canon references leave room, so /images appends the cards after
        them and numbers the role notes from position 3."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(2)]
        paths = self._paths_for(ids)

        resp, captured, spies = self._run(client, token, cid, {
            "prompt": "standing in a field",
            "include_character": True,
            "reference_image_ids": ids,
            "reference_roles": ["clothing", "environment"],
        }, canon_urls=self.CANON_URLS[:2])
        assert resp.status_code == 200, resp.text
        assert self._sent_urls(captured) == self.CANON_URLS[:2] + [paths[i] for i in ids]
        assert "Reference image 3 is the clothing and outfit to reproduce." in captured["prompt"]
        assert "never override that identity" in captured["prompt"]
        spies["compile"].assert_called_once()

    def test_augment_without_a_character_is_untouched(self, client, founder):
        """include_character=false has always meant "no canon". That path must
        still behave the same and must NOT be reported as a deliberate bypass."""
        token, cid = founder
        resp, _captured, spies = self._run(client, token, cid, {
            "prompt": "an empty room",
            "include_character": False,
        })
        assert resp.status_code == 200, resp.text
        spies["route"].assert_not_called()
        meta = resp.json()["metadata_json"]
        assert meta["canon_used"] is False
        assert meta["canon_bypassed"] is False, "absent canon is not withheld canon"
        assert meta["canon_bypass_reason"] is None

    @staticmethod
    def _paths_for(ids: list[int]) -> dict[int, str]:
        """image id → the file_path the pipeline uses as its reference URL."""
        from app.models.character_image import CharacterImage

        db = TestingSessionLocal()
        try:
            rows = db.query(CharacterImage).filter(CharacterImage.id.in_(ids)).all()
            return {int(r.id): str(r.file_path) for r in rows}
        finally:
            db.close()


# ── 5. Canon safety and storage destination ──────────────────────────────────


class TestCanonUntouched:
    def _deliberate(self, client, token, cid, ids):
        provider = _mock_provider()
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider), \
             patch(f"{PIPELINE}.route_canon_refs",
                   return_value=(list(TestProviderPayload.CANON_URLS),
                                 _scene_meta([f"slot{i}" for i in range(6)]))), \
             patch(f"{PIPELINE}.load_image_bytes",
                   side_effect=TestProviderPayload._bytes_for):
            return _generate(client, token, cid, {
                "prompt": "standing in a field",
                "include_character": False,
                "reference_image_ids": ids,
                "reference_mode": "deliberate",
            })

    def test_a_deliberate_generation_does_not_mutate_canon(self, client, founder):
        """Identity locks, anchors, accessories — byte-identical afterwards."""
        token, cid = founder
        ids = [_upload(client, token, cid).json()["id"] for _ in range(4)]
        before = _canon_snapshot(cid)
        assert before, "fixture must have canon to compare"

        resp = self._deliberate(client, token, cid, ids)
        assert resp.status_code == 200, resp.text
        assert _canon_snapshot(cid) == before, "deliberate mode changed stored canon"

    def test_the_result_is_saved_to_the_selected_character_as_scene_only(
        self, client, founder
    ):
        """The character is the storage destination — that half must hold even
        though it contributes nothing to the image."""
        from app.models.character_image import CharacterImage

        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]

        resp = self._deliberate(client, token, cid, [image_id])
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["kind"] == "scene_only"
        assert body["metadata_json"]["scene_only"] is True

        db = TestingSessionLocal()
        try:
            row = db.query(CharacterImage).filter(CharacterImage.id == body["id"]).first()
            assert row is not None
            assert int(row.character_id) == cid, "saved under the selected character"
            assert row.status.value == "active"
            assert row.visibility.value == "private"
        finally:
            db.close()

    def test_a_selected_reference_is_not_promoted(self, client, founder):
        """Using an image as a card must not change that image."""
        from app.models.character_image import CharacterImage

        token, cid = founder
        image_id = _upload(client, token, cid).json()["id"]

        def snapshot():
            db = TestingSessionLocal()
            try:
                row = db.query(CharacterImage).filter(CharacterImage.id == image_id).first()
                return (row.kind, row.status, row.visibility, row.metadata_json)
            finally:
                db.close()

        before = snapshot()
        resp = self._deliberate(client, token, cid, [image_id])
        assert resp.status_code == 200, resp.text
        assert snapshot() == before, "the reference image itself was modified"


# ── 6. Reporting ─────────────────────────────────────────────────────────────


class TestNothingIsSilent:
    def test_a_deliberate_summary_states_the_bypass(self):
        from app.services.image_generation_pipeline import build_summary

        summary = build_summary(
            refs_source="manual",
            budget=6,
            canon_refs_sent=0,
            manual_refs=[],
            manual_sent=4,
            manual_dropped=0,
            refs_loaded=4,
            provider="google",
            reference_mode=REFERENCE_MODE_DELIBERATE,
            canon_dropped=0,
            canon_bypassed=True,
        )
        assert summary["reference_mode"] == "deliberate"
        assert summary["canon_bypassed"] is True
        assert summary["canon_refs_sent"] == 0
        assert "warning" not in summary, "nothing was dropped; there is nothing to warn about"

    def test_displaced_canon_would_still_be_reported(self):
        """Unreachable while the bypass holds, and kept as its reporting half:
        a regression that let canon back in would tell the founder their cards
        had cost canon capacity rather than leaving them to infer it."""
        from app.services.image_generation_pipeline import build_summary

        summary = build_summary(
            refs_source="mixed",
            budget=6,
            canon_refs_sent=2,
            manual_refs=[],
            manual_sent=4,
            manual_dropped=0,
            refs_loaded=6,
            provider="google",
            reference_mode=REFERENCE_MODE_DELIBERATE,
            canon_dropped=4,
        )
        assert "4 lower-priority canon reference" in summary["warning"]
        assert "took priority" in summary["warning"]

    def test_the_augment_warning_is_word_for_word_unchanged(self):
        from app.services.image_generation_pipeline import build_summary

        summary = build_summary(
            refs_source="canon",
            budget=6,
            canon_refs_sent=6,
            manual_refs=[],
            manual_sent=0,
            manual_dropped=3,
            refs_loaded=6,
            provider="google",
        )
        assert summary["warning"] == (
            "3 of your reference images could not be sent: this character's canon "
            "already fills the 6-reference limit for this provider. Canon references "
            "are never dropped."
        )
        assert summary["reference_mode"] == "augment"
        assert summary["canon_bypassed"] is False
