"""Provider-only feature isolation — the mannequin layer.

Why this exists
---------------
A role tells the provider how to READ an image; it cannot change what the
provider SEES. A Hair card scoped in prose to "the hair only" still delivers a
complete photograph of a person, so every identity cue — bone structure, eyes,
mouth, skin — arrives intact. Repeated refinement then compounds it: each pass
blends a little donor identity into Person A, and the next pass treats that
blend as the identity to preserve. Observed 2026-08-22: repeated Hair passes
walked the character steadily toward the donor.

This module removes the information rather than arguing about it. For a feature
role we derive a TEMPORARY representation in which the selected feature remains
useful photographic evidence and everything else has been destroyed as identity
evidence.

Three rules govern everything here
----------------------------------
1. **The original is never touched.** Input is bytes, output is bytes. Nothing
   in this module writes to storage or to the database, and no derived image is
   ever persisted as a CharacterImage.
2. **Full canvas, never a crop.** A nose in a floating rectangle loses the
   spatial relationships that make it legible. A nose on an otherwise-suppressed
   head keeps them, and is the only meaningful facial information left.
3. **Failure is loud.** If a feature cannot be isolated safely the caller must
   refuse the generation. Falling back to the untouched donor would reintroduce
   the exact leak this module exists to close, silently.

Geometry
--------
A face box alone is not enough: it spans roughly brow-to-chin, drifts with hair
and carries no orientation. Eye centres are far more stable, so the face frame
is built from the interocular distance (IOD) and eye midpoint, and every region
is expressed in IOD units — scale- and distance-invariant, so a donor shot
close or far yields the same anatomical region.

Determinism
-----------
Same bytes + same role + same version → same output, always. No randomness, no
time, no network, no model download. That is what lets the preview endpoint
re-derive on demand instead of persisting a duplicate, and what makes a past
generation reproducible from its audit record.

Face Shape / Jawline is deliberately NOT isolated here — see
``UNSUPPORTED_FEATURE_ROLES``.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from app.services.manual_references import ReferenceRole

logger = logging.getLogger(__name__)

#: Bump on ANY change to the transform or its constants. Recorded per reference
#: in the generation audit, so a past run can be shown to have used this exact
#: pipeline — and re-derived from the original if it ever needs inspecting.
DERIVATION_VERSION = 1

#: Roles isolated in v1.
ISOLATED_ROLES: frozenset[ReferenceRole] = frozenset(
    {
        ReferenceRole.HAIR,
        ReferenceRole.EYES,
        ReferenceRole.EYEBROWS,
        ReferenceRole.NOSE,
        ReferenceRole.MOUTH_LIPS,
        ReferenceRole.SKIN_COMPLEXION,
    }
)

#: Feature roles with NO isolation transform yet.
#:
#: FACE_SHAPE is the one role whose requested information — outer contour,
#: cheek width, jaw, chin — IS its identity, so suppressing identity and
#: preserving the request pull in opposite directions. Three approaches were
#: tried and rejected (2026-08-22): a flat oval fill destroyed the cheeks and
#: jaw it was meant to keep; five per-feature masks kept the geometry but left
#: visible seams; a single union mask over-suppressed into a flat blob. A Canny
#: edge map was explicitly not accepted as the answer.
#:
#: It is listed here rather than quietly passed through because the isolation
#: contract must not be ambiguous: on a board where Hair and Eyes are isolated,
#: a raw donor face arriving as Face Shape would be the ONE unisolated identity
#: in a set the founder believes is isolated. The caller refuses instead.
#: FACIAL_HAIR is here for the same structural reason, not the same technical
#: one. It was simply outside the approved v1 set of six, and no transform was
#: written for it — but it is a FEATURE role, so passing it through raw would
#: create precisely the ambiguity FACE_SHAPE is parked to avoid: one untouched
#: donor face inside a board the founder believes is isolated. It needs a
#: beard/jaw-region transform, which is a smaller problem than face shape.
UNSUPPORTED_FEATURE_ROLES: frozenset[ReferenceRole] = frozenset(
    {ReferenceRole.FACE_SHAPE, ReferenceRole.FACIAL_HAIR}
)

_HAAR = cv2.data.haarcascades
_FACE = cv2.CascadeClassifier(_HAAR + "haarcascade_frontalface_default.xml")
_FACE_ALT = cv2.CascadeClassifier(_HAAR + "haarcascade_frontalface_alt2.xml")
_EYE = cv2.CascadeClassifier(_HAAR + "haarcascade_eye.xml")

#: How far the eye midpoint may sit from the face-box centre, as a fraction of
#: box width, before the head is treated as too turned to isolate reliably.
#: A three-quarter view shifts the eyes off-centre and every region derived from
#: a frontal model then lands off-target — measured on a 3/4 donor during the
#: investigation, where the suppression blobs visibly missed the features.
_MAX_EYE_OFFSET = 0.16
#: Eyes closer together than this (relative to face-box width) mean the detector
#: paired something that is not two eyes.
_MIN_IOD_RATIO = 0.25
#: Beyond this roll the frontal region model no longer holds.
_MAX_ROLL_DEG = 22.0

#: Region geometry in IOD units, relative to the eye midpoint: half-width,
#: top and bottom offsets. Positive vertical is downward. Derived from standard
#: facial proportion and checked against real donors during the investigation.
_REGIONS: dict[ReferenceRole, tuple[float, float, float]] = {
    ReferenceRole.EYES: (1.05, -0.42, 0.55),
    ReferenceRole.EYEBROWS: (1.05, -1.05, -0.15),
    ReferenceRole.NOSE: (0.62, -0.10, 1.25),
    ReferenceRole.MOUTH_LIPS: (0.80, 0.95, 1.75),
    # A cheek swatch, offset sideways off the midline: it carries tone,
    # undertone, texture and freckling and essentially no facial geometry.
    ReferenceRole.SKIN_COMPLEXION: (0.34, 0.30, 1.05),
}


class IsolationError(Exception):
    """A feature reference could not be safely isolated.

    ``status`` is the machine-readable audit value; ``reason`` is founder-facing
    and deliberately free of implementation vocabulary — the founder is choosing
    photographs, not tuning a detector.
    """

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(status)
        self.status = status
        self.reason = reason


class _Frame:
    """The facial coordinate frame a derivation is built on."""

    __slots__ = ("box", "eye_mid", "iod")

    def __init__(self, box, eye_mid, iod) -> None:
        self.box = box
        self.eye_mid = eye_mid
        self.iod = iod


_GENERIC_HINT = "Use a clear front-facing photo with both eyes visible."


def _decode(data: bytes) -> np.ndarray:
    try:
        return np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    except Exception as exc:  # unreadable/corrupt upload
        raise IsolationError("unreadable_image", "That image could not be read.") from exc


def _encode(rgb: np.ndarray) -> bytes:
    buf = io.BytesIO()
    # PNG: lossless and deterministic. A JPEG round-trip would make the derived
    # bytes encoder-dependent, and the audit hash with them.
    Image.fromarray(rgb).save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _detect_frame(rgb: np.ndarray) -> _Frame:
    """Locate the face and build an eye-based frame, or refuse.

    Every refusal below is a case where a derived region would land somewhere
    other than the feature it claims to be — which is worse than no isolation,
    because the founder would believe the wrong pixels were authoritative.
    """
    grey = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
    H, W = grey.shape
    boxes = []
    for cascade in (_FACE, _FACE_ALT):
        found = cascade.detectMultiScale(
            grey, 1.1, 5, minSize=(max(40, W // 14), max(40, H // 14))
        )
        if len(found):
            boxes = found
            break
    if not len(boxes):
        raise IsolationError("no_face_detected", f"No face could be found in it. {_GENERIC_HINT}")

    x, y, w, h = max(boxes, key=lambda r: r[2] * r[3])

    roi = grey[y: y + int(h * 0.6), x: x + w]
    eyes = _EYE.detectMultiScale(roi, 1.1, 6, minSize=(max(12, w // 12),) * 2)
    centres = sorted(
        [(x + ex + ew / 2.0, y + ey + eh / 2.0) for ex, ey, ew, eh in eyes],
        key=lambda p: p[0],
    )
    if len(centres) < 2:
        raise IsolationError(
            "eye_frame_unavailable", f"Both eyes need to be visible. {_GENERIC_HINT}"
        )

    left, right = centres[0], centres[-1]
    iod = float(np.hypot(right[0] - left[0], right[1] - left[1]))
    if iod < w * _MIN_IOD_RATIO:
        raise IsolationError(
            "eye_frame_unavailable", f"Both eyes need to be visible. {_GENERIC_HINT}"
        )

    roll = abs(float(np.degrees(np.arctan2(right[1] - left[1], right[0] - left[0]))))
    if roll > _MAX_ROLL_DEG:
        raise IsolationError(
            "head_tilted", f"The head is tilted too far. {_GENERIC_HINT}"
        )

    mid = ((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0)
    # Frontality: on a turned head the eye midpoint drifts off the box centre,
    # and a frontal region model then misses every feature.
    if abs(mid[0] - (x + w / 2.0)) > w * _MAX_EYE_OFFSET:
        raise IsolationError(
            "not_frontal", f"The face is turned too far to one side. {_GENERIC_HINT}"
        )
    return _Frame((x, y, w, h), mid, iod)


def _soft_mask(shape, cx, cy, rx, ry, feather) -> np.ndarray:
    m = np.zeros(shape[:2], np.float32)
    cv2.ellipse(m, (int(cx), int(cy)), (max(1, int(rx)), max(1, int(ry))), 0, 0, 360, 1.0, -1)
    k = max(3, int(feather) | 1)
    return cv2.GaussianBlur(m, (k, k), 0)[..., None]


def _suppress(rgb: np.ndarray) -> np.ndarray:
    """Destroy identity information while leaving a plausible surface.

    Deliberately NOT a mild blur, which a model can still read through. The
    image is reduced to a handful of pixels, desaturated hard and blurred, so
    what returns carries rough lighting and nothing recoverable.
    """
    H, W = rgb.shape[:2]
    small = cv2.resize(
        rgb, (max(2, W // 40), max(2, H // 40)), interpolation=cv2.INTER_AREA
    )
    back = cv2.resize(small, (W, H), interpolation=cv2.INTER_LINEAR)
    grey = cv2.cvtColor(back, cv2.COLOR_RGB2GRAY)
    back = cv2.addWeighted(back, 0.25, cv2.cvtColor(grey, cv2.COLOR_GRAY2RGB), 0.75, 0)
    k = max(3, int(min(H, W) / 12) | 1)
    return cv2.GaussianBlur(back, (k, k), 0)


def _isolate_region(rgb: np.ndarray, frame: _Frame, role: ReferenceRole) -> np.ndarray:
    """Keep one feature on the ORIGINAL canvas; suppress everything else."""
    half, top, bottom = _REGIONS[role]
    mx, my = frame.eye_mid
    iod = frame.iod
    if role is ReferenceRole.SKIN_COMPLEXION:
        mx = mx + iod * 0.62  # off the midline, onto the cheek
    cy = my + iod * (top + bottom) / 2.0
    mask = _soft_mask(
        rgb.shape, mx, cy, iod * half, iod * (bottom - top) / 2.0, int(iod * 0.22)
    )
    return (rgb * mask + _suppress(rgb) * (1.0 - mask)).astype(np.uint8)


def _isolate_hair(rgb: np.ndarray, frame: _Frame) -> np.ndarray:
    """Mannequin: keep the whole head, neutralise the face.

    The facial oval is filled with a tone sampled from the donor's own forehead
    and given back a trace of the original shading, so the head still reads as
    three-dimensional rather than as a sticker. Hairline, style, length, colour,
    texture, volume and head-relative placement all survive; the face does not.
    """
    mx, my = frame.eye_mid
    iod = frame.iod
    y0, y1 = max(0, int(my - iod * 1.5)), max(1, int(my - iod * 1.0))
    x0, x1 = max(0, int(mx - iod * 0.4)), min(rgb.shape[1], int(mx + iod * 0.4))
    patch = rgb[y0:y1, x0:x1]
    tone = patch.reshape(-1, 3).mean(0) if patch.size else np.array([190.0, 165.0, 150.0])

    mask = _soft_mask(
        rgb.shape, mx, my + iod * 0.55, iod * 1.15, iod * 1.75, int(iod * 0.5)
    )
    grey = cv2.GaussianBlur(
        cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), iod * 0.35
    )
    shade = np.clip((grey - grey.mean()) * 0.30, -26, 26)[..., None]
    flat = np.clip(np.ones_like(rgb, np.float32) * tone + shade, 0, 255)
    return (rgb * (1.0 - mask) + flat * mask).astype(np.uint8)


def isolate(data: bytes, role: ReferenceRole) -> bytes:
    """Derive the provider-only representation for one feature reference.

    Raises :class:`IsolationError` rather than ever returning the input. The
    caller must treat that as a refusal, never as permission to send the
    original.
    """
    if role in UNSUPPORTED_FEATURE_ROLES:
        raise IsolationError(
            "role_not_supported",
            "This reference type cannot be isolated yet, so it cannot be used.",
        )
    if role not in ISOLATED_ROLES:
        raise IsolationError("role_not_isolated", "This reference type is not isolated.")

    rgb = _decode(data)
    frame = _detect_frame(rgb)
    if role is ReferenceRole.HAIR:
        return _encode(_isolate_hair(rgb, frame))
    return _encode(_isolate_region(rgb, frame, role))


def isolation_audit(
    role: ReferenceRole, status: str, *, applied: bool
) -> dict[str, object]:
    """The provenance block recorded against a reference in generation metadata."""
    return {
        "isolation_applied": applied,
        "derivation_version": DERIVATION_VERSION,
        "derivation_status": status,
        "derivation_role": role.value,
    }


def should_isolate(role: Optional[ReferenceRole]) -> bool:
    """True when this role must be isolated before reaching a provider."""
    return role is not None and (role in ISOLATED_ROLES or role in UNSUPPORTED_FEATURE_ROLES)
