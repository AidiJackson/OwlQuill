"""E7 mask-geometry unit tests for the self-hosted Editor pod script.

The pod file is shipped to RunPod and never imported by the backend at
runtime, but its E7 geometry helpers (chest_carve, solid_repaint_core) are
pure functions — import the module with stub env so they can be tested.
"""
import importlib

import numpy as np
import pytest
from PIL import Image

_POD_ENV = {
    "R2_PUBLIC_URL": "https://example.test",
    "SOURCE_URL": "https://example.test/src.png",
    "USER_PROMPT": "test prompt",
    "R2_ACCOUNT_ID": "stub",
    "R2_ACCESS_KEY_ID": "stub",
    "R2_SECRET_ACCESS_KEY": "stub",
    "R2_BUCKET_NAME": "stub",
}


@pytest.fixture(scope="module")
def pod():
    import os

    missing = {k: v for k, v in _POD_ENV.items() if k not in os.environ}
    os.environ.update(missing)
    try:
        yield importlib.import_module("app.services.editor_self_hosted_pod")
    finally:
        for k in missing:
            os.environ.pop(k, None)


@pytest.fixture()
def seg():
    """Synthetic SegFormer map mimicking the E6 source layout.

    face (11) rows 5-24 · hair (2) draping down both chest sides · chest
    skin (11) rows 25-59 · strapless dress (7) rows 60-99 · arms (14/15).
    """
    s = np.zeros((100, 100), dtype=np.int64)
    s[5:25, 40:61] = 11    # face proper
    s[5:81, 30:39] = 2     # hair, left drape
    s[5:81, 62:71] = 2     # hair, right drape
    s[25:60, 39:62] = 11   # exposed neck/chest skin
    s[60:100, 35:66] = 7   # dress, top edge = row 60
    s[40:91, 20:29] = 14   # left arm (tattoos)
    s[40:91, 72:81] = 15   # right arm
    return s


def _dress_b(seg):
    return np.isin(seg, [4, 5, 7, 8])


def test_chest_carve_extends_above_neckline(pod, seg):
    carve = pod.chest_carve(seg, _dress_b(seg), extend_px=20)
    assert carve[45, 50]                      # chest skin above the dress top
    rows = np.where(carve.any(axis=1))[0]
    assert rows.min() == 60 - 20              # climbs exactly extend_px
    assert rows.max() < 60 + pod.CHEST_OVERLAP_PX


def test_chest_carve_never_touches_hair_arms_or_face(pod, seg):
    carve = pod.chest_carve(seg, _dress_b(seg), extend_px=20)
    assert not (carve & np.isin(seg, [2, 14, 15, 16])).any()
    assert not carve[:25].any()               # face rows stay out of the zone
    # protect minus carve still shields every hair/face/arm pixel
    protect = np.isin(seg, [2, 3, 11, 14, 15, 16]) & ~carve
    assert protect[np.isin(seg, [2, 14, 15])].all()
    assert protect[10, 50]                    # face proper still protected


def test_chest_carve_unblocks_protect_at_neckline(pod, seg):
    """The E6 bug: protect reached down to the exact dress top edge."""
    protect = np.isin(seg, [2, 3, 11, 14, 15, 16])
    assert protect[59, 50]                    # before: chest blocked to row 59
    carve = pod.chest_carve(seg, _dress_b(seg), extend_px=20)
    assert not (protect & ~carve)[59, 50]     # after: neckline row repaintable


def test_chest_carve_handles_empty_dress(pod):
    seg = np.zeros((50, 50), dtype=np.int64)
    carve = pod.chest_carve(seg, _dress_b(seg))
    assert carve.shape == (50, 50) and not carve.any()


def test_solid_core_excludes_composite_feather_band(pod):
    mask = Image.new("L", (100, 100), 0)
    mask.paste(255, (20, 20, 80, 80))
    solid = pod.solid_repaint_core(mask)
    assert solid[50, 50]                      # interior is solid
    assert not solid[20, 50] and not solid[50, 20]   # band edge excluded
    assert not solid[28, 50]                  # within one feather radius
    assert 0 < solid.sum() < 60 * 60          # strictly smaller than the mask


def test_remnant_count_ignores_feather_band_pixels(pod):
    """Unchanged source pixels in the feather band are not remnants."""
    mask = Image.new("L", (100, 100), 0)
    mask.paste(255, (20, 20, 80, 80))
    solid = pod.solid_repaint_core(mask)
    dress_b = np.array(mask) > 127
    unchanged = np.zeros((100, 100), dtype=bool)
    unchanged[20:30, 20:80] = True            # survivors only along the top edge
    assert (unchanged & dress_b).sum() > 0    # E5 scan would have flagged these
    assert (unchanged & dress_b & solid).sum() == 0
