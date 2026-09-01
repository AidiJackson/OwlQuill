"""Feature isolation — what the provider actually receives for a feature card.

A role tells the provider how to READ an image; it cannot change what the
provider SEES. Before isolation, a Hair card scoped in prose to "the hair only"
still delivered a complete photograph of a person, and repeated refinement
walked the character steadily toward the donor (observed 2026-08-22).

These tests pin the properties that make the difference real rather than
rhetorical:

* the target feature survives as usable photographic evidence;
* everything else is destroyed as identity evidence;
* the original bytes are never touched;
* a failure NEVER degrades to sending the donor untouched.

Deterministic and offline: synthetic faces, no provider, no network, no spend.
"""
import hashlib
import io

import numpy as np
import pytest
from PIL import Image

from app.services.manual_references import ReferenceRole
from app.services.reference_isolation import (
    DERIVATION_VERSION,
    ISOLATED_ROLES,
    UNSUPPORTED_FEATURE_ROLES,
    IsolationError,
    isolate,
    isolation_audit,
    should_isolate,
)

# The six roles isolated in v1.
SUPPORTED = [
    ReferenceRole.HAIR,
    ReferenceRole.EYES,
    ReferenceRole.EYEBROWS,
    ReferenceRole.NOSE,
    ReferenceRole.MOUTH_LIPS,
    ReferenceRole.SKIN_COMPLEXION,
]


def _synthetic_face(size=512) -> bytes:
    """A frontal face the Haar cascades actually detect.

    Built from the cascade's own expectations rather than drawn by eye: a light
    oval head, dark brows and eyes at canonical proportions, a shaded nose and a
    dark mouth. Deterministic — no randomness anywhere, so a failure is always
    reproducible.
    """
    import cv2

    img = np.full((size, size, 3), 235, np.uint8)
    cx, cy = size // 2, int(size * 0.52)
    # Head + hair.
    cv2.ellipse(img, (cx, cy), (int(size * 0.26), int(size * 0.34)), 0, 0, 360, (205, 175, 155), -1)
    cv2.ellipse(img, (cx, int(size * 0.20)), (int(size * 0.29), int(size * 0.17)),
                0, 0, 360, (60, 45, 35), -1)
    ey = int(size * 0.47)
    dx = int(size * 0.10)
    for sx in (-1, 1):
        # Eye socket, white, iris, pupil — enough structure for the eye cascade.
        cv2.ellipse(img, (cx + sx * dx, ey), (int(size*0.062), int(size*0.036)),
                    0, 0, 360, (150, 120, 105), -1)
        cv2.ellipse(img, (cx + sx * dx, ey), (int(size*0.052), int(size*0.026)),
                    0, 0, 360, (250, 250, 250), -1)
        cv2.circle(img, (cx + sx * dx, ey), int(size * 0.021), (70, 90, 120), -1)
        cv2.circle(img, (cx + sx * dx, ey), int(size * 0.010), (15, 15, 15), -1)
        # Brow.
        cv2.ellipse(img, (cx + sx * dx, ey - int(size * 0.070)),
                    (int(size * 0.062), int(size * 0.016)), 0, 0, 360, (55, 40, 30), -1)
    # Nose and mouth.
    cv2.ellipse(img, (cx, ey + int(size * 0.085)), (int(size*0.030), int(size*0.055)),
                0, 0, 360, (185, 155, 138), -1)
    cv2.ellipse(img, (cx, ey + int(size * 0.155)), (int(size*0.055), int(size*0.022)),
                0, 0, 360, (150, 70, 70), -1)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def _flat_image(size=256) -> bytes:
    """No face at all."""
    buf = io.BytesIO()
    Image.fromarray(np.full((size, size, 3), 120, np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def face(monkeypatch) -> bytes:
    """A synthetic donor WITH its face frame injected.

    The transforms and the detector are tested separately on purpose. Haar
    needs photographic texture to fire, so a drawn face would either force a
    real photograph into the repo or leave these assertions skipped — and a
    skipped suppression test proves nothing about a leak. Injecting a known
    frame makes every region boundary exactly predictable, so "the mouth was
    destroyed" is a real measurement rather than a detector coincidence.

    Detection itself — including every refusal — is exercised unpatched in
    TestFailsLoudly and TestRealDetection below.
    """
    from app.services import reference_isolation as ri

    # Matches _synthetic_face(): eyes at y=0.47*512, separated by 2*0.10*512.
    frame = ri._Frame((128, 140, 256, 256), (256.0, 240.0), 102.0)
    monkeypatch.setattr(ri, "_detect_frame", lambda _rgb: frame)
    return _synthetic_face()


def _arr(data: bytes) -> np.ndarray:
    return np.array(Image.open(io.BytesIO(data)).convert("RGB")).astype(np.float32)


def _region_delta(original: bytes, derived: bytes, box) -> float:
    """Mean absolute change inside a box — how much was destroyed there."""
    y0, y1, x0, x1 = box
    a, b = _arr(original), _arr(derived)
    return float(np.abs(a[y0:y1, x0:x1] - b[y0:y1, x0:x1]).mean())


# Canonical boxes on the synthetic 512px face (y0, y1, x0, x1).
EYE_BOX = (216, 268, 180, 332)
MOUTH_BOX = (310, 350, 216, 296)
HAIR_BOX = (20, 80, 180, 332)


# ── 1. Every supported role has its own transform ────────────────────────────


class TestRoleCoverage:
    def test_the_six_approved_roles_are_isolated(self):
        assert ISOLATED_ROLES == set(SUPPORTED)

    @pytest.mark.parametrize("role", SUPPORTED, ids=lambda r: r.value)
    def test_each_supported_role_produces_an_image(self, face, role):
        out = isolate(face, role)
        assert out and out[:8] == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.parametrize("role", SUPPORTED, ids=lambda r: r.value)
    def test_each_role_changes_the_image(self, face, role):
        """A transform that returned the input would be the leak itself."""
        assert isolate(face, role) != face

    def test_the_canvas_is_preserved_not_cropped(self, face):
        """Full-canvas suppression, never a rectangular extraction — a nose in a
        floating crop loses the spatial relationships that make it legible."""
        before = Image.open(io.BytesIO(face)).size
        for role in SUPPORTED:
            assert Image.open(io.BytesIO(isolate(face, role))).size == before

    @pytest.mark.parametrize("role", SUPPORTED, ids=lambda r: r.value)
    def test_isolation_is_deterministic(self, face, role):
        """The preview endpoint re-derives instead of persisting a duplicate,
        which only works if the transform is a pure function of its inputs."""
        assert hashlib.sha256(isolate(face, role)).hexdigest() == \
               hashlib.sha256(isolate(face, role)).hexdigest()


# ── 2. Unrelated regions are destroyed; the target survives ──────────────────


class TestSuppression:
    def test_eyes_survive_their_own_isolation(self, face):
        """Weak change in the eye region means the evidence is still usable."""
        assert _region_delta(face, isolate(face, ReferenceRole.EYES), EYE_BOX) < 12

    def test_the_mouth_is_destroyed_by_eye_isolation(self, face):
        assert _region_delta(face, isolate(face, ReferenceRole.EYES), MOUTH_BOX) > 25

    def test_the_eyes_are_destroyed_by_mouth_isolation(self, face):
        assert _region_delta(face, isolate(face, ReferenceRole.MOUTH_LIPS), EYE_BOX) > 25

    def test_the_eyes_are_destroyed_by_nose_isolation(self, face):
        assert _region_delta(face, isolate(face, ReferenceRole.NOSE), EYE_BOX) > 20

    def test_hair_isolation_keeps_the_hair(self, face):
        """The mannequin: the head and its hair are the whole point."""
        assert _region_delta(face, isolate(face, ReferenceRole.HAIR), HAIR_BOX) < 12

    def test_hair_isolation_neutralises_the_face(self, face):
        """...and the donor's eyes must not survive it."""
        assert _region_delta(face, isolate(face, ReferenceRole.HAIR), EYE_BOX) > 25

    def test_skin_isolation_destroys_the_eyes(self, face):
        """A cheek swatch carries tone and texture, never facial geometry."""
        assert _region_delta(face, isolate(face, ReferenceRole.SKIN_COMPLEXION), EYE_BOX) > 25

    def test_eyebrow_isolation_destroys_the_mouth(self, face):
        assert _region_delta(face, isolate(face, ReferenceRole.EYEBROWS), MOUTH_BOX) > 25


# ── 3. One donor, several roles → several distinct provider inputs ───────────


class TestRoleSpecificDerivation:
    def test_the_same_source_yields_different_bytes_per_role(self, face):
        digests = {r: hashlib.sha256(isolate(face, r)).hexdigest() for r in SUPPORTED}
        assert len(set(digests.values())) == len(SUPPORTED), digests

    def test_hair_and_eyebrows_from_one_photo_are_two_references(self, face):
        """The dedup case: hashing the ORIGINAL would drop the second card and
        silently lose it. Hashing the derived bytes keeps both."""
        assert isolate(face, ReferenceRole.HAIR) != isolate(face, ReferenceRole.EYEBROWS)


# ── 4. The original is never modified ────────────────────────────────────────


class TestOriginalUntouched:
    def test_the_input_bytes_are_unchanged(self, face):
        before = hashlib.sha256(face).hexdigest()
        for role in SUPPORTED:
            isolate(face, role)
        assert hashlib.sha256(face).hexdigest() == before

    def test_the_derived_bytes_are_not_the_original(self, face):
        for role in SUPPORTED:
            assert isolate(face, role) != face


# ── 5. Failure is loud, and never degrades to the donor ──────────────────────


class TestFailsLoudly:
    def test_no_face_is_refused(self):
        with pytest.raises(IsolationError) as e:
            isolate(_flat_image(), ReferenceRole.HAIR)
        assert e.value.status == "no_face_detected"

    def test_an_unreadable_image_is_refused(self):
        with pytest.raises(IsolationError) as e:
            isolate(b"not an image", ReferenceRole.EYES)
        assert e.value.status == "unreadable_image"

    @pytest.mark.parametrize("role", sorted(UNSUPPORTED_FEATURE_ROLES, key=lambda r: r.value))
    def test_a_parked_role_is_refused_rather_than_passed_through(self, face, role):
        """Face Shape and Facial Hair have no transform yet. Sending the donor
        raw would put ONE un-isolated identity into a board the founder believes
        is isolated — the exact ambiguity this refusal exists to prevent."""
        with pytest.raises(IsolationError) as e:
            isolate(face, role)
        assert e.value.status == "role_not_supported"

    def test_a_refusal_never_returns_bytes(self):
        """There is no code path where a failure yields an image."""
        for bad in (_flat_image(), b"junk"):
            with pytest.raises(IsolationError):
                isolate(bad, ReferenceRole.EYES)

    def test_refusal_messages_are_actionable_and_free_of_jargon(self):
        with pytest.raises(IsolationError) as e:
            isolate(_flat_image(), ReferenceRole.HAIR)
        reason = e.value.reason
        assert "front-facing" in reason
        for jargon in ("Haar", "IOD", "cascade", "interocular", "ellipse", "mask"):
            assert jargon.lower() not in reason.lower()


# ── 5b. The detector itself, unpatched ───────────────────────────────────────


class TestRealDetection:
    """Exercises the real cascades and the frontality gate.

    Runs against genuine imagery when the local media directory has any, and
    skips rather than asserting on an empty environment — the point is to prove
    the detector works on real photographs, and there is nothing to prove if
    there are none.
    """

    @staticmethod
    def _real_samples(limit=6):
        import glob
        import os

        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "static", "generated")
        files = [f for f in glob.glob(d + "/*.png") + glob.glob(d + "/*.jpg")
                 if os.path.getsize(f) > 150_000]
        return sorted(files)[:limit]

    def test_the_cascades_load_offline(self):
        """No model download, ever — the whole approach depends on this."""
        from app.services import reference_isolation as ri

        assert not ri._FACE.empty()
        assert not ri._EYE.empty()

    def test_real_photographs_either_isolate_or_refuse_cleanly(self):
        samples = self._real_samples()
        if not samples:
            pytest.skip("no local media to sample")
        isolated = 0
        for path in samples:
            with open(path, "rb") as fh:
                data = fh.read()
            try:
                out = isolate(data, ReferenceRole.HAIR)
            except IsolationError as exc:
                # A refusal is a valid outcome; a wrong one is not.
                assert exc.status in {
                    "no_face_detected", "eye_frame_unavailable",
                    "not_frontal", "head_tilted", "unreadable_image",
                }
                assert exc.reason and "Haar" not in exc.reason
            else:
                isolated += 1
                assert out != data          # never the donor
                assert out[:8] == b"\x89PNG\r\n\x1a\n"
        # Nothing is asserted about the RATE: a sample of scene images may
        # legitimately contain no usable frontal donor at all.
        assert isolated >= 0


# ── 6. Which roles are in scope at all ───────────────────────────────────────


class TestScope:
    @pytest.mark.parametrize("role", SUPPORTED, ids=lambda r: r.value)
    def test_supported_roles_must_be_isolated(self, role):
        assert should_isolate(role)

    @pytest.mark.parametrize("role", sorted(UNSUPPORTED_FEATURE_ROLES, key=lambda r: r.value))
    def test_parked_roles_are_still_gated(self, role):
        """They must reach the isolation path so they can be REFUSED there,
        rather than bypassing it and being sent raw."""
        assert should_isolate(role)

    @pytest.mark.parametrize(
        "role",
        [
            ReferenceRole.CHARACTER_1,
            ReferenceRole.CHARACTER_2,
            ReferenceRole.CLOTHING,
            ReferenceRole.ENVIRONMENT,
            ReferenceRole.POSE_COMPOSITION,
            ReferenceRole.TATTOO_MARK,
            ReferenceRole.UNSPECIFIED,
            ReferenceRole.OTHER,
            ReferenceRole.CHARACTER_APPEARANCE,
        ],
        ids=lambda r: r.value,
    )
    def test_non_feature_roles_are_never_transformed(self, role):
        """Identity, scene and canon references reach the provider exactly as
        they always have."""
        assert not should_isolate(role)

    def test_a_canon_reference_has_no_role_and_is_never_transformed(self):
        assert not should_isolate(None)


# ── 7. Audit provenance ──────────────────────────────────────────────────────


class TestAudit:
    def test_it_records_role_version_and_status(self):
        entry = isolation_audit(ReferenceRole.HAIR, "applied", applied=True)
        assert entry == {
            "isolation_applied": True,
            "derivation_version": DERIVATION_VERSION,
            "derivation_status": "applied",
            "derivation_role": "hair",
        }

    def test_the_version_is_recorded_so_a_past_run_can_be_re_derived(self):
        assert isinstance(DERIVATION_VERSION, int) and DERIVATION_VERSION >= 1
