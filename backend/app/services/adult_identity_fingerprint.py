"""Canon fingerprinting for Adult Studio (Phase 1, Sprint 2).

A stable, deterministic SHA-256 over the locked canon inputs Adult Studio depends on:
face refs + description, body refs + build/description, and every permanent body mark's
metadata (type/region/side/label/description) and reference URLs.

Purpose: detect staleness. If any of these canon inputs change (e.g. the corrected
Summer mark descriptions), the fingerprint changes, so a trained Adult Identity model
whose stored `canon_fingerprint` no longer matches current canon is flagged stale.

Pure functions. No DB access, no canon writes — canon is read-only.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Canon fields that feed the fingerprint. Kept explicit (not "all fields") so unrelated
# canon churn (e.g. lock flags, timestamps) does not needlessly invalidate models.
FACE_FIELDS = (
    "face_front_image_url",
    "face_left_3q_image_url",
    "face_right_3q_image_url",
    "face_expression_image_url",
    "face_description",
)
BODY_FIELDS = (
    "body_front_image_url",
    "body_left_image_url",
    "body_right_image_url",
    "body_back_image_url",
    "body_map_image_url",
    "build",
    "body_description",
)
MARK_FIELDS = (
    "id",
    "type",
    "body_region",
    "side",
    "label",
    "description",
    "reference_image_url",
    "detail_crop_url",
)


def _as_dict(obj: Any) -> dict:
    """Normalize a pydantic model / dict / None into a plain dict."""
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return dict(obj)
    raise TypeError(f"unsupported canon object: {type(obj)!r}")


def _sha(payload: Any) -> str:
    """Deterministic SHA-256 of a JSON-canonicalized payload.

    sort_keys makes the hash independent of dict key insertion order; compact
    separators keep it whitespace-stable; ensure_ascii=False keeps unicode stable.
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _mark_payload(mark: Any) -> dict:
    d = _as_dict(mark)
    return {k: d.get(k) for k in MARK_FIELDS}


def mark_fingerprint(mark: Any) -> str:
    """Stable fingerprint of a single permanent body mark."""
    return _sha(_mark_payload(mark))


def canon_fingerprint(face: Any, body: Any) -> str:
    """Stable fingerprint of the locked canon inputs Adult Studio depends on.

    `face` / `body` may be FaceCanonData / BodyCanonData pydantic models, plain dicts,
    or None. Marks are read from `body.permanent_body_marks` and sorted, so mark
    ordering does not change the result.
    """
    fd = _as_dict(face)
    bd = _as_dict(body)
    marks = bd.get("permanent_body_marks") or []
    mark_payloads = sorted(
        (_mark_payload(m) for m in marks),
        key=lambda m: ((m.get("id") or ""), (m.get("body_region") or ""), (m.get("label") or "")),
    )
    payload = {
        "face": {k: fd.get(k) for k in FACE_FIELDS},
        "body": {k: bd.get(k) for k in BODY_FIELDS},
        "marks": mark_payloads,
    }
    return _sha(payload)
