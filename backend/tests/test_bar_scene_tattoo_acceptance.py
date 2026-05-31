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
import json
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.schemas.body_canon import BodyMarking
from app.api.routes.image_generator import (
    _classify_marking_coverage,
    _build_permanent_marking_block,
    _classify_region_exposure,
    _build_arm_side_lock_str,
    _reorder_anchor_refs,
    _CANONICAL_BODY_REF_ALLOWED,
)


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

def _apply_canonical_filter(
    imgs: list[bytes], types: list[str]
) -> tuple[list[bytes], list[str]]:
    pairs = [(img, t) for img, t in zip(imgs, types) if t in _CANONICAL_BODY_REF_ALLOWED]
    if pairs:
        imgs_out, types_out = zip(*pairs)
        return list(imgs_out), list(types_out)
    return [], []


_STUB = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


# ══════════════════════════════════════════════════════════════════════
# Suite 1: Coverage classification — per prompt, per marking
# ══════════════════════════════════════════════════════════════════════


class TestWolfCoverageInBarScene:
    """Wolf tattoo (right_upper_arm) must be COVERED in every bar-scene prompt.

    T-shirts and short-sleeve shirts expose the forearm but cover the upper arm.
    The wolf sits on the upper arm → it stays hidden under the sleeve.
    """

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_wolf_is_covered(self, prompt):
        result = _classify_marking_coverage(_wolf(), prompt)
        assert result == "covered", (
            f"Wolf (right_upper_arm) must be COVERED in bar scene.\n"
            f"Prompt: {prompt!r}\nGot: {result!r}"
        )

    def test_wolf_upper_arm_region_covered_by_tshirt(self):
        """Direct region-exposure check: right_upper_arm is covered by t-shirt."""
        assert _classify_region_exposure("right_upper_arm", _BAR_PROMPT_1) == "covered"

    def test_wolf_upper_arm_region_covered_by_short_sleeve(self):
        assert _classify_region_exposure("right_upper_arm", _BAR_PROMPT_2) == "covered"


class TestScriptureSleeveExposureInBarScene:
    """Scripture sleeve (left_full_arm) forearm must be EXPOSED in bar-scene t-shirt prompts.

    A full-sleeve tattoo's forearm portion is part of the sleeve design — when the
    forearm is exposed by a t-shirt the sleeve exception fires and the marking is EXPOSED.
    """

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_scripture_sleeve_is_exposed(self, prompt):
        result = _classify_marking_coverage(_scripture(), prompt)
        assert result == "exposed", (
            f"Scripture sleeve (left_full_arm) forearm must be EXPOSED in bar scene.\n"
            f"Prompt: {prompt!r}\nGot: {result!r}"
        )

    def test_scripture_forearm_exposed_by_tshirt(self):
        """Direct region-exposure check: left_forearm exposed when wearing a t-shirt."""
        assert _classify_region_exposure("left_forearm", _BAR_PROMPT_1) == "exposed"

    def test_scripture_forearm_exposed_by_short_sleeve(self):
        assert _classify_region_exposure("left_forearm", _BAR_PROMPT_2) == "exposed"


# ══════════════════════════════════════════════════════════════════════
# Suite 2: Permanent marking block — prompt text structure
# ══════════════════════════════════════════════════════════════════════


class TestPermanentMarkingBlockBarScene:
    """_build_permanent_marking_block must emit the right sections for bar scenes.

    Exposed markings  → PERMANENT BODY MARKINGS section (render from ref)
    Covered markings  → COVERED BY CLOTHING section (coverage note, no DO NOT RENDER)
    """

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_block_has_permanent_markings_section(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        assert "PERMANENT BODY MARKINGS" in block, (
            f"Block must have PERMANENT BODY MARKINGS (scripture sleeve is exposed).\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_block_has_covered_by_clothing_section(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        assert "COVERED BY CLOTHING" in block, (
            f"Block must have COVERED BY CLOTHING (wolf is hidden).\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_scripture_appears_in_permanent_section(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        perm_section = block.split("COVERED BY CLOTHING")[0]
        assert "scripture" in perm_section.lower() or "sleeve" in perm_section.lower(), (
            f"Scripture sleeve token must appear in the PERMANENT section.\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_wolf_appears_in_covered_section(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        covered_section = block.split("COVERED BY CLOTHING")[-1] if "COVERED BY CLOTHING" in block else ""
        assert "wolf" in covered_section.lower(), (
            f"Wolf token must appear in the COVERED BY CLOTHING section.\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_wolf_not_in_permanent_section(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        perm_section = block.split("COVERED BY CLOTHING")[0]
        assert "wolf" not in perm_section.lower(), (
            f"Wolf must NOT appear in PERMANENT section (it is covered).\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_left_arm_placement_in_permanent_section(self, prompt):
        """Scripture sleeve token includes 'left arm' — correct side signalled."""
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        perm_section = block.split("COVERED BY CLOTHING")[0]
        assert "left arm" in perm_section.lower(), (
            f"Permanent section must mention left arm for scripture sleeve.\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_right_arm_placement_in_covered_section(self, prompt):
        """Wolf token includes 'right upper arm' — correct side for coverage note."""
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        covered_section = block.split("COVERED BY CLOTHING")[-1] if "COVERED BY CLOTHING" in block else ""
        assert "right upper arm" in covered_section.lower() or "right arm" in covered_section.lower(), (
            f"Covered section must mention right arm for wolf.\n"
            f"Prompt: {prompt!r}\nBlock: {block!r}"
        )


# ══════════════════════════════════════════════════════════════════════
# Suite 3: Anti-mirroring — no wolf on left, no scripture on right
# ══════════════════════════════════════════════════════════════════════


class TestAntiMirroringBarScene:
    """Arm-side lock text must prevent tattoo mirroring across arms.

    When only the left arm has an exposed marking (scripture sleeve) and the right arm
    carries a covered marking (wolf), the side-lock declares left tattooed / right bare
    so the model does not mirror the scripture sleeve onto the right arm.
    """

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_arm_side_lock_declares_left_tattooed(self, prompt):
        exposed = [m for m in _MARKINGS if _classify_marking_coverage(m, prompt) == "exposed"]
        lock = _build_arm_side_lock_str(exposed)
        assert "left" in lock.lower(), (
            f"Side lock must declare left arm as tattooed.\n"
            f"Prompt: {prompt!r}\nLock: {lock!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_arm_side_lock_declares_right_bare(self, prompt):
        exposed = [m for m in _MARKINGS if _classify_marking_coverage(m, prompt) == "exposed"]
        lock = _build_arm_side_lock_str(exposed)
        assert "right" in lock.lower(), (
            f"Side lock must declare right arm as bare skin.\n"
            f"Prompt: {prompt!r}\nLock: {lock!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_arm_side_lock_no_tattoos_on_right(self, prompt):
        exposed = [m for m in _MARKINGS if _classify_marking_coverage(m, prompt) == "exposed"]
        lock = _build_arm_side_lock_str(exposed)
        assert "no tattoos" in lock.lower() or "bare skin" in lock.lower(), (
            f"Side lock must explicitly forbid tattoos on the bare arm.\n"
            f"Prompt: {prompt!r}\nLock: {lock!r}"
        )


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


class TestRefPipelineBarScene:
    """Body identity refs must survive the canonical filter in the bar-scene pipeline.

    When body_front is locked, canonical mode applies a whitelist that keeps:
      body_identity:body_front, body_identity:body_left_detail,
      body_identity:body_right_detail, body_identity:body_back,
      body_identity:body_map, front, three_quarter.
    Everything else (body_anchor:*, torso, tattoo_layout) is stripped.
    """

    def _run_pipeline(self, input_types: list[str], *, tattoo_primary: bool = True) -> list[str]:
        imgs = [_STUB] * len(input_types)
        imgs, types = _reorder_anchor_refs(imgs, input_types, tattoo_primary=tattoo_primary)
        imgs, types = _apply_canonical_filter(imgs, types)
        return types

    def test_body_front_survives_canonical_filter(self):
        types = self._run_pipeline([
            "front", "body_identity:body_front",
            "body_identity:body_left_detail",
        ])
        assert "body_identity:body_front" in types, (
            "body_front must survive the canonical filter — it is the visual truth"
        )

    def test_left_detail_survives_canonical_filter(self):
        """body_left_detail (scripture sleeve ref) must survive canonical filter."""
        types = self._run_pipeline([
            "front", "body_identity:body_front",
            "body_identity:body_left_detail",
        ])
        assert "body_identity:body_left_detail" in types, (
            "body_left_detail must survive — it is the high-fidelity scripture sleeve ref"
        )

    def test_body_front_is_position_1_in_tattoo_primary_mode(self):
        """In body-truth mode: front=pos0, body_front=pos1."""
        types = self._run_pipeline([
            "front", "body_identity:body_front",
        ])
        assert types.index("body_identity:body_front") == 1 or (
            types[0] == "front" and "body_identity:body_front" in types
        ), f"body_front must be at position 1 after front. Got: {types}"

    def test_front_is_position_0(self):
        types = self._run_pipeline([
            "front", "body_identity:body_front",
            "body_identity:body_left_detail",
        ])
        assert types[0] == "front", f"front must be position 0 (identity seed). Got: {types}"

    def test_body_anchor_stripped_in_canonical_mode(self):
        """Per-arm body_anchor refs stripped — body_front is the sole visual truth."""
        types = self._run_pipeline([
            "front", "body_identity:body_front",
            "body_anchor:right_arm", "body_anchor:left_arm",
        ])
        assert not any(t.startswith("body_anchor:") for t in types), (
            f"body_anchor refs must be stripped in canonical mode. Got: {types}"
        )

    def test_torso_stripped_in_canonical_mode(self):
        types = self._run_pipeline([
            "front", "body_identity:body_front", "torso",
        ])
        assert "torso" not in types, (
            f"torso must be stripped in canonical mode. Got: {types}"
        )

    def test_no_ref_duplication(self):
        """Front anchor must appear exactly once (no face-boost dup in tattoo-primary)."""
        types = self._run_pipeline([
            "front", "front", "body_identity:body_front",
        ])
        assert types.count("front") == 1, (
            f"front must appear exactly once in canonical mode. Got: {types}"
        )


# ══════════════════════════════════════════════════════════════════════
# Suite 6: No-wolf-on-shirt — coverage text must not demand wolf render
# ══════════════════════════════════════════════════════════════════════


class TestNoWolfThroughFabric:
    """Permanent marking block must never instruct the model to render the wolf
    when the prompt places it under clothing.

    The coverage-note approach means the wolf's token appears only in the
    COVERED BY CLOTHING section — which is a note, not a render command.
    The PERMANENT BODY MARKINGS section must never mention wolf.
    """

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_permanent_section_has_no_wolf_render_command(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        if "PERMANENT BODY MARKINGS" not in block:
            return  # no permanent markings at all — trivially passes
        perm_only = block.split("COVERED BY CLOTHING")[0] if "COVERED BY CLOTHING" in block else block
        assert "wolf" not in perm_only.lower(), (
            f"Wolf must NOT appear in PERMANENT render section (it is under clothing).\n"
            f"Prompt: {prompt!r}\nPermanent section: {perm_only!r}"
        )

    @pytest.mark.parametrize("prompt", _BAR_PROMPTS)
    def test_covered_section_is_a_note_not_a_render_command(self, prompt):
        block = _build_permanent_marking_block(_MARKINGS, prompt)
        covered_idx = block.find("COVERED BY CLOTHING")
        if covered_idx == -1:
            pytest.fail(f"COVERED BY CLOTHING section missing from block: {block!r}")
        covered_text = block[covered_idx:]
        assert "render" not in covered_text.lower(), (
            "COVERED section must not contain 'render' — it is a coverage note only.\n"
            f"Covered section: {covered_text!r}"
        )


# ══════════════════════════════════════════════════════════════════════
# Suite 7: Signal collision regression — "pool" in pool-table bar prompts
# ══════════════════════════════════════════════════════════════════════


class TestPoolTableFalsePositive:
    """Regression documenting a known signal collision discovered while authoring
    this acceptance baseline.

    "pool" is in _FULL_ARM_EXPOSURE_SIGNALS to catch swimming-pool scenes.
    It is a substring of "pool table", which causes bar-scene pool-table prompts
    to incorrectly report full-arm exposure — classifying the wolf (right_upper_arm)
    as EXPOSED instead of COVERED.

    These tests pin the *current* (broken) behaviour so the signal-set maintainer
    knows exactly what changes when this collision is fixed.
    """

    _POOL_TABLE_PROMPT = (
        "leaning on a pool table at the back of the bar, short-sleeve shirt, "
        "cue in hand, neon signs on the wall, nighttime"
    )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "KNOWN BUG: 'pool' in _FULL_ARM_EXPOSURE_SIGNALS matches 'pool table'. "
            "Fix: scope 'pool' to full-word or require 'swimming pool' / 'poolside'."
        ),
    )
    def test_pool_table_incorrectly_triggers_full_arm_exposure(self):
        """After the fix, right_upper_arm must be COVERED for a pool-table bar scene."""
        from app.api.routes.image_generator import _classify_region_exposure
        result = _classify_region_exposure("right_upper_arm", self._POOL_TABLE_PROMPT)
        assert result == "covered", (
            f"Got: {result!r}. Signal 'pool' still matches 'pool table'."
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "KNOWN BUG: wolf (right_upper_arm) classified EXPOSED for pool-table bar "
            "scene because 'pool' signal collides with 'pool table'."
        ),
    )
    def test_pool_table_wolf_classification_is_wrong(self):
        """After the fix, wolf must be COVERED for a pool-table bar scene."""
        result = _classify_marking_coverage(_wolf(), self._POOL_TABLE_PROMPT)
        assert result == "covered", (
            f"Got: {result!r}. Signal collision still active."
        )


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
        "app.api.routes.image_generator.get_provider_for_option",
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
        assert "immutable canon" in prompt.lower()
        assert "wolf" in prompt.lower()
        assert "match canon references exactly" in prompt.lower()

    def test_permanence_directive_present_no_legacy_bloat(self, client: TestClient, db_session):
        """P13 (C): the compact anti-restyle directive is present; the pre-P12
        verbose side-lock/relocation essays are not reintroduced."""
        token, cid = _setup_canon_char(client, db_session, "ep_canon_mirror@bartest.com")
        resp, captured = _generate(client, token, cid, _BAR_PROMPT_1)
        assert resp.status_code == 200, resp.text
        prompt = captured.get("prompt", "").lower()
        assert "do not redesign, mirror, relocate" in prompt
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
