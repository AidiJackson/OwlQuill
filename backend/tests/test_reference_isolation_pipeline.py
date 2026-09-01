"""Isolation as the pipeline applies it — what leaves the process.

The unit suite proves the TRANSFORM. This one proves the WIRING: that a feature
card is transformed before dispatch, that a failure refuses instead of degrading
to the donor, that the audit records what happened, and that nothing else on the
board changed.

The load hook returns identifiable bytes per URL, so an assertion can say "the
provider received something other than the donor" precisely rather than by
inspecting pixels.
"""
import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from app.services.manual_references import ReferenceRole
from app.services.reference_isolation import DERIVATION_VERSION, IsolationError

from tests.test_admin_creator_reference_mode import (  # reuse the harness
    PIPELINE,
    _generate,
    _mock_provider,
    _png,
    _scene_meta,
    _upload,
    founder,  # noqa: F401 — pytest fixture
)

#: Per-URL raw bytes, so the identity card's donor and a feature card's donor
#: are distinguishable in the captured anchor list. A single shared DONOR value
#: cannot tell "Person A was sent raw" (correct) from "the Hair donor was sent
#: raw" (the leak).
def _raw_for(url: str) -> bytes:
    return f"RAW::{url}".encode()


DERIVED = b"DERIVED-PROVIDER-BYTES"


def _body(roles, ids, prompt="A portrait."):
    return {
        "prompt": prompt,
        "include_character": False,
        "provider_option": "option2",
        "reference_image_ids": ids,
        "reference_roles": roles,
        "reference_mode": "deliberate",
    }


def _run(client, token, cid, body, *, isolate_side_effect=None):
    """Run one generation; report the anchors the provider actually received."""
    provider = _mock_provider()
    captured: dict = {}
    provider.generate_with_anchors = MagicMock(
        side_effect=lambda *, prompt, anchor_images, **kw: (
            captured.update(prompt=prompt, anchors=list(anchor_images)) or _png()
        )
    )
    provider.generate_image = MagicMock(
        side_effect=lambda *, prompt, **kw: (
            captured.update(prompt=prompt, anchors=[]) or _png()
        )
    )
    iso = MagicMock(side_effect=isolate_side_effect or (lambda data, role: DERIVED))
    with patch(f"{PIPELINE}.get_provider_for_option", return_value=provider), \
         patch(f"{PIPELINE}.route_canon_refs",
               MagicMock(return_value=([], _scene_meta([])))), \
         patch(f"{PIPELINE}.load_image_bytes", side_effect=_raw_for), \
         patch(f"{PIPELINE}.isolate_reference", iso):
        resp = _generate(client, token, cid, body)
    return resp, captured, iso


def _isolated_donor_bytes(iso) -> bytes:
    """The raw bytes the transform was handed — i.e. the feature card's donor."""
    return iso.call_args[0][0]


def _two(client, token, cid):
    return _upload(client, token, cid).json()["id"], _upload(client, token, cid).json()["id"]


# ── 1. The provider never sees the donor ─────────────────────────────────────


class TestProviderReceivesDerivedBytes:
    @pytest.mark.parametrize(
        "role", ["hair", "eyes", "eyebrows", "nose", "mouth_lips", "skin_complexion"]
    )
    def test_a_feature_card_reaches_the_provider_isolated(self, client, founder, role):
        token, cid = founder
        a, b = _two(client, token, cid)
        resp, cap, iso = _run(client, token, cid, _body(["character_1", role], [a, b]))
        assert resp.status_code == 200, resp.text
        assert DERIVED in cap["anchors"], "the derived reference never reached the provider"
        assert iso.call_count == 1
        assert _isolated_donor_bytes(iso) not in cap["anchors"], \
            "the feature card's raw donor reached the provider"

    def test_the_identity_card_is_sent_untouched(self, client, founder):
        """Character 1 is identity truth and must never be transformed."""
        token, cid = founder
        a, b = _two(client, token, cid)
        _resp, cap, iso = _run(client, token, cid, _body(["character_1", "hair"], [a, b]))
        raw_anchors = [x for x in cap["anchors"] if x.startswith(b"RAW::")]
        assert len(raw_anchors) == 1, "Person A was altered, or a donor leaked"
        assert iso.call_args[0][1] is ReferenceRole.HAIR

    @pytest.mark.parametrize(
        "roles",
        [
            ["character_1", "character_2"],
            ["clothing", "environment"],
            ["character_1", "pose_composition"],
            ["tattoo_mark", "clothing"],
            ["unspecified", "unspecified"],
        ],
    )
    def test_a_board_with_no_feature_card_is_never_transformed(
        self, client, founder, roles
    ):
        token, cid = founder
        a, b = _two(client, token, cid)
        _resp, cap, iso = _run(client, token, cid, _body(roles, [a, b]))
        assert iso.call_count == 0
        assert all(x.startswith(b"RAW::") for x in cap["anchors"]), \
            "an unrelated reference was transformed"

    def test_one_donor_under_two_roles_yields_two_provider_references(
        self, client, founder
    ):
        """Dedup runs on the DERIVED bytes. Hashing the original would collapse
        these two cards into one and silently lose the founder's selection."""
        token, cid = founder
        a, b = _two(client, token, cid)
        per_role = {"hair": b"DERIVED-HAIR", "eyebrows": b"DERIVED-BROWS"}
        _resp, cap, _iso = _run(
            client, token, cid, _body(["hair", "eyebrows"], [a, b]),
            isolate_side_effect=lambda data, role: per_role[role.value],
        )
        assert sorted(cap["anchors"]) == sorted(per_role.values())

    def test_identical_derived_bytes_still_dedupe(self, client, founder):
        """The pre-existing dedup contract is unchanged: identical payload bytes
        collapse, whatever produced them."""
        token, cid = founder
        a, b = _two(client, token, cid)
        _resp, cap, _iso = _run(client, token, cid, _body(["hair", "eyes"], [a, b]))
        assert cap["anchors"] == [DERIVED]


# ── 2. Failure refuses; it never falls back ──────────────────────────────────


class TestFailureNeverFallsBack:
    def _failing(self, status="no_face_detected"):
        def _raise(_data, _role):
            raise IsolationError(status, "Use a clear front-facing photo with both eyes visible.")
        return _raise

    def test_a_failed_isolation_refuses_the_generation(self, client, founder):
        token, cid = founder
        a, b = _two(client, token, cid)
        resp, cap, _iso = _run(
            client, token, cid, _body(["character_1", "hair"], [a, b]),
            isolate_side_effect=self._failing(),
        )
        assert resp.status_code == 422, resp.text
        assert not cap, "the provider was called despite a failed isolation"

    def test_the_donor_is_not_sent_when_isolation_fails(self, client, founder):
        """The whole point: degrading to the untouched donor would silently
        restore the leak the founder believes was removed."""
        token, cid = founder
        a, b = _two(client, token, cid)
        _resp, cap, _iso = _run(
            client, token, cid, _body(["character_1", "hair"], [a, b]),
            isolate_side_effect=self._failing(),
        )
        assert not any(x.startswith(b"RAW::") for x in cap.get("anchors", []))

    def test_the_error_names_the_card_and_says_what_to_do(self, client, founder):
        token, cid = founder
        a, b = _two(client, token, cid)
        resp, _cap, _iso = _run(
            client, token, cid, _body(["character_1", "hair"], [a, b]),
            isolate_side_effect=self._failing(),
        )
        detail = resp.json()["detail"]
        assert "Hair reference 2" in detail, detail
        assert "front-facing" in detail

    def test_the_error_carries_no_implementation_jargon(self, client, founder):
        token, cid = founder
        a, b = _two(client, token, cid)
        resp, _cap, _iso = _run(
            client, token, cid, _body(["character_1", "eyes"], [a, b]),
            isolate_side_effect=self._failing("not_frontal"),
        )
        detail = resp.json()["detail"]
        for jargon in ("Haar", "IOD", "cascade", "interocular", "ellipse"):
            assert jargon.lower() not in detail.lower()

    @pytest.mark.parametrize("role", ["face_shape", "facial_hair"])
    def test_a_parked_role_refuses_rather_than_sending_a_raw_face(
        self, client, founder, role
    ):
        """Face Shape and Facial Hair have no transform. They must NOT slip
        through as raw donors inside an otherwise-isolated board."""
        token, cid = founder
        a, b = _two(client, token, cid)
        with patch(f"{PIPELINE}.get_provider_for_option", return_value=_mock_provider()), \
             patch(f"{PIPELINE}.route_canon_refs",
                   MagicMock(return_value=([], _scene_meta([])))), \
             patch(f"{PIPELINE}.load_image_bytes", side_effect=_raw_for):
            resp = _generate(client, token, cid, _body(["character_1", role], [a, b]))
        assert resp.status_code == 422, resp.text


# ── 3. Audit provenance ──────────────────────────────────────────────────────


class TestAuditRecordsTheDerivation:
    def _metadata(self, client, founder_fixture, roles):
        token, cid = founder_fixture
        a, b = _two(client, token, cid)
        resp, _cap, _iso = _run(client, token, cid, _body(roles, [a, b]))
        assert resp.status_code == 200, resp.text
        return resp.json()["metadata_json"], (a, b)

    def test_an_isolated_reference_records_its_provenance(self, client, founder):
        md, (a, b) = self._metadata(client, founder, ["character_1", "hair"])
        entry = next(r for r in md["manual_refs"] if r["role"] == "hair")
        assert entry["image_id"] == b, "the ORIGINAL image id must identify the source"
        assert entry["isolation_applied"] is True
        assert entry["derivation_version"] == DERIVATION_VERSION
        assert entry["derivation_status"] == "applied"
        assert entry["derivation_role"] == "hair"

    def test_the_identity_card_records_no_isolation_at_all(self, client, founder):
        """Absence of the key means "never in play", which is exactly true."""
        md, (a, _b) = self._metadata(client, founder, ["character_1", "hair"])
        entry = next(r for r in md["manual_refs"] if r["role"] == "character_1")
        assert "isolation_applied" not in entry
        assert entry["image_id"] == a
        assert entry["identity_group"] == "person_a"

    def test_unrelated_roles_keep_their_existing_audit_shape(self, client, founder):
        md, _ids = self._metadata(client, founder, ["clothing", "environment"])
        for entry in md["manual_refs"]:
            assert "isolation_applied" not in entry
            assert {"image_id", "role", "position", "kind", "sent"} <= set(entry)

    def test_no_derived_image_row_is_created(self, client, founder, db_session):
        """Derived references are provider-only and in-memory. A second
        CharacterImage would be a duplicate of someone's photograph."""
        from app.models.character_image import CharacterImage

        token, cid = founder
        before = db_session.query(CharacterImage).filter_by(character_id=cid).count()
        a, b = _two(client, token, cid)
        resp, _cap, _iso = _run(client, token, cid, _body(["character_1", "hair"], [a, b]))
        assert resp.status_code == 200
        after = db_session.query(CharacterImage).filter_by(character_id=cid).count()
        # Two uploads + exactly one generated result. No derived rows.
        assert after == before + 3, f"{after - before} rows created, expected 3"


# ── 4. Nothing else moved ────────────────────────────────────────────────────


class TestUnrelatedBehaviourUnchanged:
    def test_augment_mode_never_isolates(self, client, founder):
        """/images submits under augment. Even a feature role there must reach
        the provider untouched — isolation is a deliberate-mode contract."""
        token, cid = founder
        a, b = _two(client, token, cid)
        body = _body(["character_1", "hair"], [a, b])
        del body["reference_mode"]  # → augment
        _resp, cap, iso = _run(client, token, cid, body)
        assert iso.call_count == 0
        assert all(x.startswith(b"RAW::") for x in cap["anchors"])

    def test_a_feature_free_board_is_byte_identical_end_to_end(self, client, founder):
        token, cid = founder
        a, b = _two(client, token, cid)
        _resp, cap, iso = _run(
            client, token, cid, _body(["character_1", "character_2"], [a, b])
        )
        assert iso.call_count == 0
        assert "SUPPLIED REFERENCES" in cap["prompt"]
        assert "two DIFFERENT people" in cap["prompt"]
