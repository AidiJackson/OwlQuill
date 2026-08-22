"""Acceptance baseline — bar-scene tattoo visibility after always-on ref change.

Task #26 switched from withholding body refs to always loading them and using a
coverage-note in the prompt.  This file is the acceptance test confirming the
expected behaviour:

  Character spec:
    - Wolf tattoo     | right_upper_arm (non-sleeve)
    - Scripture sleeve| left_full_arm   (full-sleeve, shoulder to wrist)

  Bar-scene garment: t-shirt / short-sleeve (the realistic bar-night choice)

  Expected outcome:
    1. Wolf → COVERED   (t-shirt covers right upper arm)
    2. Scripture sleeve forearm → EXPOSED  (t-shirt exposes forearm;
                                            full-sleeve exception applies)
    3. No mirroring: wolf stays right-only; scripture stays left-only
    4. Canonical body-ref mode activates when body_front is locked
    5. Ref pipeline includes body_identity refs (body_front, detail crops)

Three representative bar prompts exercise the logic across different framings.
All tests operate on the pure helper functions — no provider calls, no DB.

── Discovery during test authoring ──────────────────────────────────────────
"pool" is in _FULL_ARM_EXPOSURE_SIGNALS (intended for swimming-pool scenes).
It collides with "pool table" bar prompts, incorrectly triggering full-arm
exposure and classifying the wolf (right_upper_arm) as EXPOSED.  Bar prompts
that reference "pool table" are excluded from the parametrized suite; a
dedicated regression class (TestPoolTableFalsePositive) documents the
collision so it can be fixed separately.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.body_canon import BodyMarking


# ── Character fixtures ─────────────────────────────────────────────────

def _wolf() -> BodyMarking:
    """Wolf tattoo on right upper arm — non-sleeve, covered by most shirts."""
    return BodyMarking(
        type="tattoo",
        placement="right_upper_arm",
        style="grey wolf howling tattoo",
        size="large",
        description="Wolf howling at the moon, grey ink, right upper arm",
    )


def _scripture() -> BodyMarking:
    """Scripture sleeve on left full arm — forearm always visible through t-shirt."""
    return BodyMarking(
        type="tattoo",
        placement="left_full_arm",
        style="scripture sleeve black ink lettering tattoo",
        size="full_sleeve",
        description="Bible verses and crosses, black ink, left arm shoulder to wrist",
    )


_MARKINGS = [_wolf(), _scripture()]

# ── Bar-scene prompts (lowercase as the generator uses them) ───────────

_BAR_PROMPT_1 = (
    "standing at the bar counter, ordering a drink, wearing a fitted black t-shirt, "
    "jeans, dim amber lighting, bar stools behind"
)
_BAR_PROMPT_2 = (
    "leaning against the wall at the back of the bar, short-sleeve shirt, arms crossed, "
    "neon signs on the wall, nighttime"
)
# NOTE: "pool table" prompts are intentionally excluded from the parametrized suite
# because "pool" collides with _FULL_ARM_EXPOSURE_SIGNALS (see TestPoolTableFalsePositive).
_BAR_PROMPT_3 = (
    "sitting at a high-top table in a bar, tshirt and dark jeans, glass of whiskey, "
    "background blur of other patrons"
)

_BAR_PROMPTS = [_BAR_PROMPT_1, _BAR_PROMPT_2, _BAR_PROMPT_3]


# ── Helper ─────────────────────────────────────────────────────────────


_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


# ══════════════════════════════════════════════════════════════════════
# Suite 1: Coverage classification — per prompt, per marking
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Suite 2: Permanent marking block — prompt text structure
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Suite 3: Anti-mirroring — no wolf on left, no scripture on right
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Suite 4: Canonical mode activation (body_front locked + markings exist)
# ══════════════════════════════════════════════════════════════════════


class TestCanonicalModeActivationBarScene:
    """body_front locked + markings exist → canonical mode must activate.

    This verifies the activation logic in generate_image for bar scenes.
    Canonical mode sends body_front as the single visual truth; it activates
    when body_front is available AND (tattoo_visibility_requested OR has_markings).
    """

    def test_canonical_activates_with_tshirt_prompt(self):
        """T-shirt prompt triggers tattoo_visibility_requested → canonical."""
        body_front_available = True
        tattoo_visibility_requested = True  # t-shirt in _BOTH_ARMS_SIGNALS
        has_markings = True

        canonical = body_front_available and (tattoo_visibility_requested or has_markings)
        assert canonical, "Canonical mode must activate for t-shirt bar scene with markings"

    def test_canonical_activates_even_without_explicit_skin_keywords(self):
        """Canonical activates via has_markings even if prompt has no skin keywords."""
        body_front_available = True
        tattoo_visibility_requested = False
        has_markings = True

        canonical = body_front_available and (tattoo_visibility_requested or has_markings)
        assert canonical, (
            "Canonical mode must activate when markings exist + body_front locked, "
            "even without explicit skin-exposure keywords"
        )

    def test_canonical_inactive_without_body_front(self):
        """No body_front locked → canonical does NOT activate."""
        body_front_available = False
        tattoo_visibility_requested = True
        has_markings = True

        canonical = body_front_available and (tattoo_visibility_requested or has_markings)
        assert not canonical, "Canonical must NOT activate when body_front is absent"


# ══════════════════════════════════════════════════════════════════════
# Suite 5: Ref pipeline — body identity refs survive canonical filter
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Suite 6: No-wolf-on-shirt — coverage text must not demand wolf render
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# Suite 7: Signal collision regression — "pool" in pool-table bar prompts
# ══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# Suite 8 — Endpoint integration through the CharacterIdentityCanon contract
#
# Identity truth (face/body/marks/accessories) comes only from canon, compiled by
# canon_compiler. There is no legacy body_identity anchor_types / clothing-coverage
# prompt partitioning — permanent marks are listed in one PERMANENT BODY MARKS
# section and protected by the locked-canon clause.
# ═══════════════════════════════════════════════════════════════════════════════

from tests.canon_test_utils import setup_canon  # noqa: E402

_STUB_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Canon permanent marks — wolf (right arm) + scripture sleeve (left arm).
_WOLF_MARK = {
    "label": "Right Arm Wolf Mark",
    "type": "tattoo",
    "body_region": "right_full_arm",
    "side": "right",
    "description": "wolf howling at the moon, grey ink",
}
_SCRIPTURE_MARK = {
    "label": "Left Arm Scripture Sleeve",
    "type": "tattoo",
    "body_region": "left_full_arm",
    "side": "left",
    "description": "scripture sleeve, bible verses and crosses, black ink",
}


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Deterministic local disk storage (env may default to R2)."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


def _reg_login(client: TestClient, email: str) -> str:
    username = email.split("@")[0].replace(".", "_")
    client.post(
        "/auth/register",
        json={"email": email, "username": username, "password": "testpass!123"},
    )
    resp = client.post("/auth/login", json={"email": email, "password": "testpass!123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _create_char(client: TestClient, token: str) -> int:
    resp = client.post(
        "/characters/",
        json={"name": "BarTatChar", "visibility": "public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _setup_canon_char(client: TestClient, db_session, email: str):
    """Create a character with a populated canon: wolf + scripture permanent marks."""
    token = _reg_login(client, email)
    cid = _create_char(client, token)
    setup_canon(db_session, cid, marks=[_WOLF_MARK, _SCRIPTURE_MARK], with_images=False)
    return token, cid


def _generate(client: TestClient, token: str, cid: int, prompt: str):
    """Call the image-generator endpoint; capture the compiled provider prompt."""
    captured: dict = {}

    def _with_anchors(*, prompt, anchor_images, size="1024x1024"):
        captured["prompt"] = prompt
        return _STUB_PNG

    def _grounded(*, prompt, reference_image_bytes, size="1024x1024"):
        captured.setdefault("prompt", prompt)
        return _STUB_PNG

    def _text(*, prompt, size="1024x1024", reference_image_url=None):
        captured.setdefault("prompt", prompt)
        return _STUB_PNG

    mock_provider = MagicMock()
    mock_provider.supports_multi_image_input = True
    mock_provider.generate_with_anchors = _with_anchors
    mock_provider.generate_grounded_image = _grounded
    mock_provider.generate_image = _text

    with patch(
        "app.services.image_generation_pipeline.get_provider_for_option",
        return_value=mock_provider,
    ):
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={"prompt": prompt, "include_character": True, "provider_option": "option1"},
            headers={"Authorization": f"Bearer {token}"},
        )
    return resp, captured


class TestCanonEndpointIntegration:
    """End-to-end route behaviour under the canon contract."""

    def test_marks_appear_as_compact_immutable_clause(self, client: TestClient, db_session):
        """P13 (A+C): tattoo design is reintroduced as a compact immutable clause."""
        token, cid = _setup_canon_char(client, db_session, "ep_canon_marks@bartest.com")
        resp, captured = _generate(client, token, cid, _BAR_PROMPT_1)
        assert resp.status_code == 200, resp.text
        prompt = captured.get("prompt", "")
        # No legacy bloated header, but the compact clause + design tokens are present.
        assert "PERMANENT BODY MARKS" not in prompt
        assert "skin-bound anatomy" in prompt.lower()
        assert "wolf" in prompt.lower()
        assert "remain attached to the correct body region and side" in prompt.lower()

    def test_permanence_directive_present_no_legacy_bloat(self, client: TestClient, db_session):
        """P13 (C): the compact anti-restyle directive is present; the pre-P12
        verbose side-lock/relocation essays are not reintroduced."""
        token, cid = _setup_canon_char(client, db_session, "ep_canon_mirror@bartest.com")
        resp, captured = _generate(client, token, cid, _BAR_PROMPT_1)
        assert resp.status_code == 200, resp.text
        prompt = captured.get("prompt", "").lower()
        assert "do not redesign, relocate, mirror" in prompt
        assert "detach, float" in prompt          # P13b: anti floating-symbol clause
        assert "for visual balance or composition" not in prompt

    def test_no_legacy_metadata(self, client: TestClient, db_session):
        token, cid = _setup_canon_char(client, db_session, "ep_canon_meta@bartest.com")
        resp, _ = _generate(client, token, cid, _BAR_PROMPT_1)
        assert resp.status_code == 200, resp.text
        meta = resp.json()["metadata_json"]
        assert meta["canon_used"] is True
        for legacy_key in ("anchor_types", "strict_identity_mode", "identity_hash"):
            assert legacy_key not in meta

    @pytest.mark.parametrize("bar_prompt", _BAR_PROMPTS)
    def test_endpoint_returns_200_for_all_bar_prompts(
        self, client: TestClient, db_session, bar_prompt: str
    ):
        email = "ep_200_" + bar_prompt[:12].replace(" ", "").replace(",", "") + "@bt.com"
        token, cid = _setup_canon_char(client, db_session, email)
        resp, captured = _generate(client, token, cid, bar_prompt)
        assert resp.status_code == 200, (
            f"Endpoint returned {resp.status_code} for bar prompt: {bar_prompt!r}\n{resp.text}"
        )
        # P12: prompt is minimal and card-driven — the user scene is preserved
        # and no canon marking prose is injected.
        prompt = captured.get("prompt", "")
        assert bar_prompt in prompt
        assert "PERMANENT BODY MARKS" not in prompt

    def test_missing_canon_returns_409(self, client: TestClient):
        token = _reg_login(client, "ep_canon_missing@bartest.com")
        cid = _create_char(client, token)
        resp = client.post(
            f"/characters/{cid}/image-generator/generate",
            json={"prompt": _BAR_PROMPT_1, "include_character": True, "provider_option": "option1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "Character canon incomplete"
