"""Provider-payload verification for exposure-gated permanent-mark image refs.

`test_mark_detail_cards.py` proves the SCENE ROUTER *selects* the right marking
image URLs. This file closes the next gap: it proves those selected refs are
actually loaded into bytes and delivered to the image PROVIDER'S anchor payload
on the canon scene-generation path (`/identity-canon/scenes/generate`).

Character (matches the established repo fixture):
    - Right Arm Wolf Sleeve | right_upper_arm  (non-sleeve, covered by a shirt)
    - Left Arm Scripture Sleeve | left_full_arm (full sleeve; forearm shows)

Proven end-to-end through the provider call:
    1. arms visible (sleeveless)  → BOTH mark images + body card reach provider
    2. covered (long-sleeve suit) → NEITHER mark image reaches provider
    3. short-sleeve               → scripture (exposed forearm) reaches provider,
                                     wolf (covered upper arm) does NOT
    4. BODY_MARK_REF_USED diagnostic log fires for the refs that reached provider
"""
import logging
from unittest.mock import patch

import pytest

from app.core.storage import load_image_bytes
from tests.canon_test_utils import setup_canon, stub_image_url
from tests.conftest import auth_headers, get_auth_token


@pytest.fixture(autouse=True)
def _local_storage(monkeypatch):
    """Deterministic local disk storage so stub URLs are byte-loadable."""
    from app.core.config import settings
    monkeypatch.setattr(settings, "USE_OBJECT_STORAGE", False)


_STUB_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _CapturingProvider:
    """Records the anchor_images payload handed to generate_with_anchors."""

    supports_multi_image_input = True

    def __init__(self):
        self.calls: list[dict] = []

    def generate_with_anchors(self, *, prompt, anchor_images, size="1024x1024"):
        self.calls.append({"prompt": prompt, "anchor_images": list(anchor_images)})
        return _STUB_PNG

    # Only reached if generate_with_anchors raises; defined for completeness.
    def generate_grounded_image(self, *, prompt, reference_image_bytes, size="1024x1024"):
        return _STUB_PNG

    def generate_image(self, *, prompt, size="1024x1024"):
        return _STUB_PNG


def _create_character(client, headers, name="MarkRefChar"):
    resp = client.post(
        "/characters/", json={"name": name, "visibility": "public"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _setup(client, db_session, email):
    """Char + locked canon with body_front and two arm markings (real stub images)."""
    token = get_auth_token(client, email=email, username=email.split("@")[0])
    hdrs = auth_headers(token)
    cid = _create_character(client, hdrs)
    wolf_url = stub_image_url("wolf_sleeve")
    script_url = stub_image_url("scripture_sleeve")
    setup_canon(
        db_session,
        cid,
        marks=[
            {
                # A non-sleeve upper-arm tattoo: covered by a short sleeve, so it
                # exercises selective per-region gating (the full "Wolf Sleeve"
                # case lives in test_canon_router_arm_visibility.py).
                "label": "Right Arm Wolf", "type": "tattoo",
                "body_region": "right_upper_arm", "side": "right",
                "description": "howling wolf head, grey ink",
                "reference_image_url": wolf_url,
            },
            {
                "label": "Left Arm Scripture Sleeve", "type": "tattoo",
                "body_region": "left_full_arm", "side": "left",
                "description": "scripture sleeve, black lettering",
                "reference_image_url": script_url,
            },
        ],
        with_images=True,
        lock=True,
    )
    return hdrs, cid, wolf_url, script_url


def _body_front_url(client, hdrs, cid):
    resp = client.get(f"/characters/{cid}/identity-canon", headers=hdrs)
    assert resp.status_code == 200, resp.text
    return resp.json()["body_canon"]["body_front_image_url"]


def _generate_anchor_payload(client, hdrs, cid, prompt):
    """Generate a scene; return the anchor_images bytes the provider received."""
    provider = _CapturingProvider()
    with patch(
        "app.api.routes.canon_api.get_provider_for_option", return_value=provider
    ):
        resp = client.post(
            f"/characters/{cid}/identity-canon/scenes/generate",
            json={"prompt": prompt, "provider_option": "option2"},
            headers=hdrs,
        )
    assert resp.status_code == 200, resp.text
    assert provider.calls, "provider.generate_with_anchors was never called"
    return provider.calls[-1]["anchor_images"]


class TestMarkingImageReachesProviderPayload:
    """The marking image bytes must reach the provider when the region is exposed."""

    def test_both_arm_marks_reach_provider_when_arms_visible(self, client, db_session):
        hdrs, cid, wolf_url, script_url = _setup(client, db_session, "mref_both@bt.com")
        body_front_url = _body_front_url(client, hdrs, cid)

        anchors = _generate_anchor_payload(
            client, hdrs, cid, "facing camera in a sleeveless tank top, arms visible"
        )

        # Right arm visible → Right Wolf Sleeve image ref reaches the provider.
        assert load_image_bytes(wolf_url) in anchors
        # Left arm visible → Left Scripture Sleeve image ref reaches the provider.
        assert load_image_bytes(script_url) in anchors
        # The relevant body card travels alongside the marking crops.
        assert load_image_bytes(body_front_url) in anchors

    def test_no_arm_marks_reach_provider_when_covered(self, client, db_session):
        hdrs, cid, wolf_url, script_url = _setup(client, db_session, "mref_cov@bt.com")
        body_front_url = _body_front_url(client, hdrs, cid)

        anchors = _generate_anchor_payload(
            client, hdrs, cid, "front view, wearing a long-sleeve wool suit and tie"
        )

        # Covered arms → NO tattoo image refs reach the provider.
        assert load_image_bytes(wolf_url) not in anchors
        assert load_image_bytes(script_url) not in anchors
        # Body truth still reaches the provider (only marking crops are gated).
        assert load_image_bytes(body_front_url) in anchors

    def test_only_exposed_region_mark_reaches_provider(self, client, db_session):
        """Short sleeve: scripture forearm exposed → routed; wolf upper arm covered → not."""
        hdrs, cid, wolf_url, script_url = _setup(client, db_session, "mref_sel@bt.com")

        anchors = _generate_anchor_payload(
            client, hdrs, cid, "wearing a short-sleeve shirt, facing the camera"
        )

        assert load_image_bytes(script_url) in anchors      # left forearm exposed
        assert load_image_bytes(wolf_url) not in anchors     # right upper arm covered


class TestBodyMarkRefUsedDiagnostic:
    """The BODY_MARK_REF_USED log proves, in production, which mark refs were sent."""

    def test_log_emitted_for_exposed_marks_only(self, client, db_session, caplog):
        hdrs, cid, _wolf, _script = _setup(client, db_session, "mref_log@bt.com")

        with caplog.at_level(logging.INFO, logger="app.api.routes.canon_api"):
            _generate_anchor_payload(
                client, hdrs, cid, "facing camera in a sleeveless tank top, arms visible"
            )

        used = [r.getMessage() for r in caplog.records if "BODY_MARK_REF_USED" in r.getMessage()]
        assert any(
            "Right Arm Wolf" in m and "source=reference_image_url" in m for m in used
        ), used
        assert any("Left Arm Scripture Sleeve" in m for m in used), used

    def test_no_log_when_marks_covered(self, client, db_session, caplog):
        hdrs, cid, _wolf, _script = _setup(client, db_session, "mref_nolog@bt.com")

        with caplog.at_level(logging.INFO, logger="app.api.routes.canon_api"):
            _generate_anchor_payload(
                client, hdrs, cid, "front view, wearing a long-sleeve wool suit and tie"
            )

        used = [r.getMessage() for r in caplog.records if "BODY_MARK_REF_USED" in r.getMessage()]
        assert used == [], f"Covered marks must not log a used ref: {used}"
