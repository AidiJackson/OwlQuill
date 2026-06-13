"""Guard the deterministic source-image priority for the Replicate test (Sprint E9.2).

Critical: the img2img seed must ALWAYS be chosen by a fixed priority, never randomly.
Priority: body_front → body_final → face_front → first available ref.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes.adult_studio_admin import _pick_source_ref


def _m(*roles):
    return {"refs": [{"role": r, "url": f"https://img/{r}.png"} for r in roles]}


def test_body_front_wins():
    role, url = _pick_source_ref(_m("face_front", "body_back", "body_front", "body_final"))
    assert role == "body_front"
    assert url == "https://img/body_front.png"


def test_body_final_when_no_body_front():
    role, _ = _pick_source_ref(_m("face_front", "body_final", "body_left"))
    assert role == "body_final"


def test_face_front_when_no_body():
    role, _ = _pick_source_ref(_m("face_left_3q", "face_front", "mark:arm"))
    assert role == "face_front"


def test_first_available_fallback_is_deterministic():
    # No prioritized role present → the FIRST ref (manifest order), not a random one.
    role, _ = _pick_source_ref(_m("body_left", "body_right", "mark:arm"))
    assert role == "body_left"


def test_no_refs_raises_409():
    with pytest.raises(HTTPException) as exc:
        _pick_source_ref({"refs": []})
    assert exc.value.status_code == 409
