"""Route-level enforcement of the optional prompt.

The unit tests next door pin the RULE; these pin the BOUNDARY. The prompt field
was relaxed from ``min_length=1`` to ``min_length=0`` on a schema shared by
/images and Admin Creator, so the refusal now lives in application code. If it
were ever misplaced, /images would silently start accepting empty prompts —
which is the regression this file exists to catch.

No provider is reached: every case here is rejected or refused before
generation, so nothing spends.
"""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.test_admin_creator_reference_mode import (  # reuse the fixtures
    _create_character,
    _generate,
    _make_seeder,
    _upload,
    founder,  # noqa: F401 — pytest fixture
)
from tests.conftest import auth_headers, get_auth_token


def _body(prompt, ids=None, roles=None, mode=None):
    b = {"prompt": prompt, "include_character": False, "provider_option": "option2"}
    if ids is not None:
        b["reference_image_ids"] = ids
        b["reference_roles"] = roles or []
    if mode is not None:
        b["reference_mode"] = mode
    return b


def _two_refs(client, token, cid):
    a = _upload(client, token, cid).json()["id"]
    b = _upload(client, token, cid).json()["id"]
    return a, b


@contextmanager
def _isolation_stubbed():
    """Neutralise feature isolation for the duration of one request.

    These tests are about the PROMPT rule. The uploaded fixtures are flat stub
    PNGs with no face in them, so a board carrying a feature card is now
    correctly refused by isolation before the prompt rule is ever reached —
    which would make these assertions pass or fail for the wrong reason.
    Isolation has its own suites; here it is stubbed out so the prompt decision
    is the only thing under test.
    """
    with patch(
        "app.services.image_generation_pipeline.isolate_reference",
        side_effect=lambda data, role: data + b"-derived",
    ):
        yield


# ── /images and every ordinary caller: unchanged ─────────────────────────────


class TestPromptStillRequiredOnImages:
    def test_an_empty_prompt_with_no_references_is_refused(self, client, founder):
        token, cid = founder
        r = _generate(client, token, cid, _body(""))
        assert r.status_code == 422, r.text

    def test_a_whitespace_prompt_is_treated_as_empty(self, client, founder):
        token, cid = founder
        assert _generate(client, token, cid, _body("   \n  ")).status_code == 422

    def test_augment_mode_refuses_an_empty_prompt_even_with_feature_roles(
        self, client, founder
    ):
        """THE /images guard. Under augment those roles compile to nothing, so
        accepting a blank prompt here would send the provider an empty prompt."""
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        r = _generate(
            client, token, cid,
            _body("", ids=[a, b], roles=["character_1", "hair"]),  # no mode → augment
        )
        assert r.status_code == 422, r.text

    def test_an_ordinary_creator_still_needs_a_prompt(self, client, db_session):
        token = get_auth_token(client, email="plain@example.com", username="plainacct")
        cid = _create_character(client, token, name="Plain")
        assert _generate(client, token, cid, _body("")).status_code == 422

    def test_a_normal_prompt_is_unaffected(self, client, founder):
        """The relaxed field must not change the ordinary path in any way."""
        token, cid = founder
        r = _generate(client, token, cid, _body("A quiet room at dusk."))
        assert r.status_code != 422, r.text


# ── Admin Creator: allowed only for a self-describing board ──────────────────


class TestDeliberateBoards:
    @pytest.mark.parametrize(
        "roles",
        [
            ["character_1", "hair"],
            ["eyes", "nose"],
            ["character_1", "pose_composition"],
        ],
    )
    def test_a_self_describing_board_may_omit_the_prompt(self, client, founder, roles):
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        with _isolation_stubbed():
            r = _generate(
                client, token, cid,
                _body("", ids=[a, b], roles=roles, mode="deliberate"),
            )
        assert r.status_code != 422, r.text

    @pytest.mark.parametrize(
        "roles",
        [
            ["character_1", "character_2"],
            ["clothing", "environment"],
            ["unspecified", "unspecified"],
            ["character_1", "clothing"],
        ],
    )
    def test_a_board_that_states_no_operation_is_refused(self, client, founder, roles):
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        r = _generate(
            client, token, cid,
            _body("", ids=[a, b], roles=roles, mode="deliberate"),
        )
        assert r.status_code == 422, r.text

    def test_deliberate_with_no_cards_at_all_is_refused(self, client, founder):
        """Deliberate mode is not itself a licence to omit the prompt — an
        empty board describes nothing regardless of mode."""
        token, cid = founder
        r = _generate(client, token, cid, _body("", ids=[], roles=[], mode="deliberate"))
        assert r.status_code == 422, r.text

    def test_the_refusal_explains_when_a_prompt_can_be_omitted(self, client, founder):
        token, cid = founder
        r = _generate(client, token, cid, _body("", ids=[], roles=[], mode="deliberate"))
        assert "optional" in r.json()["detail"].lower()

    def test_a_prompt_is_still_accepted_alongside_a_self_describing_board(
        self, client, founder
    ):
        """Free text becomes ADDITIONAL direction, never forbidden."""
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        with _isolation_stubbed():
            r = _generate(
                client, token, cid,
                _body("Front-facing portrait in natural light.",
                      ids=[a, b], roles=["character_1", "hair"], mode="deliberate"),
            )
        assert r.status_code != 422, r.text


# ── The async job route enforces the same rule ───────────────────────────────


class TestJobRouteMatchesSyncRoute:
    def _submit(self, client, token, cid, body):
        body = {**body, "idempotency_key": "k" + str(abs(hash(str(body))))[:12]}
        return client.post(
            f"/characters/{cid}/image-generator/jobs",
            json=body,
            headers=auth_headers(token),
        )

    def test_the_job_route_refuses_a_blank_prompt_on_a_bare_board(self, client, founder):
        token, cid = founder
        r = self._submit(client, token, cid, _body("", ids=[], roles=[], mode="deliberate"))
        assert r.status_code == 422, r.text

    def test_the_job_route_refuses_a_blank_prompt_under_augment(self, client, founder):
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        r = self._submit(client, token, cid, _body("", ids=[a, b], roles=["character_1", "hair"]))
        assert r.status_code == 422, r.text

    def test_the_job_route_accepts_a_self_describing_board(self, client, founder):
        """Submission only — the job is validated at the route and the driver
        never runs here, so isolation is not reached."""
        token, cid = founder
        a, b = _two_refs(client, token, cid)
        r = self._submit(
            client, token, cid,
            _body("", ids=[a, b], roles=["character_1", "hair"], mode="deliberate"),
        )
        assert r.status_code != 422, r.text
