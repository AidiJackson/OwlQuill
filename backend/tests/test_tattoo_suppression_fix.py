"""Tests for Task #16 — fix tattoo suppression when no exposure keyword present.

When a scene prompt contains no body-exposure keyword (e.g. "shirtless"), the
visibility-detection step returns an empty region set and the per-marking text was
previously filtered to nothing — the model received zero instruction about the
character's tattoos and drew bare, unmarked arms. The fix injects ALL markings as
passive context via build_passive_body_canon_string so the model always knows the
markings exist, while the clothing safety invariant keeps covered markings hidden.
"""
from app.schemas.body_canon import BodyMarking
from app.services.body_canon import (
    build_body_canon_lock_string,
    build_passive_body_canon_string,
)


def _wolf() -> BodyMarking:
    return BodyMarking(
        type="tattoo",
        placement="right_full_arm",
        style="tribal wolf",
        size="large",
        description="large tribal wolf tattoo on the right arm",
    )


def _script() -> BodyMarking:
    return BodyMarking(
        type="tattoo",
        placement="left_full_arm",
        style="gothic script sleeve",
        size="full_sleeve",
        description="full sleeve gothic script tattoo on the left arm",
    )


class TestPassiveBodyCanonString:
    """build_passive_body_canon_string frames markings as context, not a command."""

    def test_empty_when_no_markings(self):
        assert build_passive_body_canon_string([]) == ""

    def test_lists_all_markings(self):
        out = build_passive_body_canon_string([_wolf(), _script()])
        assert out, "passive string must be non-empty when markings exist"
        assert "tribal wolf" in out
        assert "gothic script sleeve" in out

    def test_framed_as_passive_context(self):
        out = build_passive_body_canon_string([_wolf()]).lower()
        # Passive context, not a forced-visibility command.
        assert "permanent body markings" in out
        assert "skin is naturally exposed" in out

    def test_not_a_forced_visibility_command(self):
        # Must not read as the hard "BODY MARKINGS:" visibility lock string.
        out = build_passive_body_canon_string([_wolf()])
        assert not out.startswith("BODY MARKINGS:")


class TestPassivePathInjectsAllMarkings:
    """The no-exposure-keyword path must inject all markings, not an empty filter.

    Reproduces the root cause: _bc_text_markings was empty (filtered by visibility),
    so the old call build_body_canon_lock_string(_bc_text_markings) produced "".
    The fix uses build_passive_body_canon_string(_bc_markings) instead.
    """

    def test_old_filtered_path_produced_empty(self):
        # Visibility filter yields [] when no exposure keyword → old behavior empty.
        assert build_body_canon_lock_string([]) == ""

    def test_new_passive_path_is_non_empty(self):
        markings = [_wolf(), _script()]
        # All markings are injected regardless of visibility filtering.
        assert build_passive_body_canon_string(markings) != ""


