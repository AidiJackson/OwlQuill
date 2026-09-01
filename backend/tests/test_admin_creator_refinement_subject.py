"""A feature change needs ONE starting image.

The identity buckets group on purpose: several CHARACTER_1 cards compile to
"Reference images 1, 3 and 4 are all the same person … reproduce that person's
face and likeness exactly". That is right for two photographs of one person and
incoherent as the subject of "replace Person A's hair" — the referent becomes a
set, and the model must guess whose hair is being replaced.

It reached production through the reuse button rather than through the compiler:
`Use as Character 1` filled the next EMPTY card, so three sequential Hair
refinements left the original photograph and two generated results all marked
Character 1, and the original hairstyle returned (2026-08-22).

The precedence clause cannot arbitrate this. It is scoped to attributes that are
NOT required changes — deliberately, so identity cannot veto an explicit feature
replacement — so it says nothing about hair here at all.

Pure and route-level; no provider, no spend.
"""
import pytest

from app.services.manual_references import (
    REFERENCE_MODE_DELIBERATE,
    ReferenceRole,
    ResolvedReference,
    build_reference_notes,
    has_ambiguous_refinement_subject,
    parse_role,
)


def roles(*values):
    return [parse_role(v) for v in values]


def ambiguous(*values) -> bool:
    return has_ambiguous_refinement_subject(roles(*values))


class _Image:
    def __init__(self, image_id: int) -> None:
        self.id = image_id
        self.file_path = f"m{image_id}.png"
        self.kind = "uploaded"


def notes(*values) -> str:
    refs = [ResolvedReference(_Image(10 + i), parse_role(v), i) for i, v in enumerate(values)]
    return build_reference_notes(
        refs, canon_ref_count=0, canon_grounded=False,
        refs_before_manual=0, mode=REFERENCE_MODE_DELIBERATE,
    )


# ── The rule ─────────────────────────────────────────────────────────────────


class TestAmbiguousRefinementSubject:
    @pytest.mark.parametrize(
        "board",
        [
            ("character_1", "character_1", "hair"),
            ("character_1", "hair", "character_1"),          # the real board's order
            ("character_1", "hair", "character_1", "character_1"),
            ("character_1", "character_1", "eyes", "nose"),
            ("character_1", "character_1", "skin_complexion"),
        ],
    )
    def test_several_person_a_cards_with_a_feature_change_are_ambiguous(self, board):
        assert ambiguous(*board)

    def test_the_board_that_actually_ran_is_caught(self):
        """1=Grace, 2=hair donor, 3=result1, 4=result2 — the 2026-08-22 board."""
        assert ambiguous("character_1", "hair", "character_1", "character_1")

    @pytest.mark.parametrize(
        "board",
        [
            ("character_1", "hair"),                          # the correct shape
            ("character_1", "eyes", "nose", "mouth_lips"),
            ("hair", "eyes"),                                 # construction, no identity
            ("character_2", "hair"),
        ],
    )
    def test_a_single_person_a_is_unambiguous(self, board):
        assert not ambiguous(*board)

    @pytest.mark.parametrize(
        "board",
        [
            ("character_1", "character_1"),                   # two views of one person
            ("character_1", "character_1", "clothing"),
            ("character_1", "character_1", "environment", "pose_composition"),
            ("character_1", "character_1", "character_1"),
            ("character_1", "character_1", "tattoo_mark"),
        ],
    )
    def test_multiple_person_a_cards_are_fine_without_a_feature_change(self, board):
        """Grouping is a FEATURE for scenes and canon cards: two photographs of
        one person must read as one identity seen twice. Nothing here is being
        edited, so there is no starting image to be ambiguous about."""
        assert not ambiguous(*board)

    def test_two_person_scenes_are_untouched(self):
        assert not ambiguous("character_1", "character_2")
        assert not ambiguous("character_1", "character_2", "environment")

    def test_character_2_duplicates_do_not_trigger_it(self):
        """Person B is never the subject of a refinement."""
        assert not ambiguous("character_2", "character_2", "hair")

    def test_an_empty_board_is_not_ambiguous(self):
        assert not has_ambiguous_refinement_subject([])


# ── What the compiler still produces for the allowed shapes ──────────────────


class TestCompiledSemanticsUnchanged:
    def test_grouping_still_works_for_a_two_photo_scene(self):
        text = notes("character_1", "character_1", "clothing")
        assert "Reference images 1 and 2 are all the same person, Person A" in text

    def test_the_single_subject_refinement_still_compiles(self):
        text = notes("character_1", "hair")
        assert "Reference image 1 is Person A" in text
        assert "replace Person A's hair with the hair from reference image 2" in text

    def test_two_person_semantics_are_unchanged(self):
        text = notes("character_1", "character_2")
        assert "two DIFFERENT people and both appear in this scene" in text
        assert "do not blend, average, morph, merge or swap faces" in text


# ── The route enforces it ────────────────────────────────────────────────────


from contextlib import contextmanager  # noqa: E402
from unittest.mock import patch  # noqa: E402

from tests.test_admin_creator_reference_mode import (  # noqa: E402
    _generate,
    _upload,
    founder,  # noqa: F401 — pytest fixture
)


@contextmanager
def _isolation_stubbed():
    """Feature isolation neutralised — the guard, not the transform, is on trial.

    The uploaded fixtures are flat stub PNGs with no face, so isolation would
    refuse them first and every assertion below would pass for the wrong reason.
    """
    with patch(
        "app.services.image_generation_pipeline.isolate_reference",
        side_effect=lambda data, role: data + b"-derived",
    ):
        yield


def _body(role_list, ids, mode="deliberate"):
    body = {
        "prompt": "A portrait.",
        "include_character": False,
        "provider_option": "option2",
        "reference_image_ids": ids,
        "reference_roles": role_list,
    }
    if mode:
        body["reference_mode"] = mode
    return body


def _uploads(client, token, cid, n):
    return [_upload(client, token, cid).json()["id"] for _ in range(n)]


class TestRouteRefusesAnAmbiguousSubject:
    def test_the_contaminated_board_is_refused(self, client, founder):
        token, cid = founder
        ids = _uploads(client, token, cid, 4)
        with _isolation_stubbed():
            r = _generate(client, token, cid,
                          _body(["character_1", "hair", "character_1", "character_1"], ids))
        assert r.status_code == 422, r.text

    def test_the_refusal_explains_what_is_wrong_and_what_to_do(self, client, founder):
        token, cid = founder
        ids = _uploads(client, token, cid, 3)
        with _isolation_stubbed():
            r = _generate(client, token, cid,
                          _body(["character_1", "character_1", "hair"], ids))
        detail = r.json()["detail"]
        assert "single current Person A image" in detail
        assert "Character 1" in detail
        assert "remove" in detail.lower()

    def test_a_single_person_a_refinement_is_allowed(self, client, founder):
        token, cid = founder
        ids = _uploads(client, token, cid, 2)
        with _isolation_stubbed():
            r = _generate(client, token, cid, _body(["character_1", "hair"], ids))
        assert r.status_code == 200, r.text


class TestRouteLeavesEverythingElseAlone:
    @pytest.mark.parametrize(
        "role_list",
        [
            ["character_1", "character_1"],
            ["character_1", "character_1", "clothing"],
            ["character_1", "character_1", "pose_composition"],
            ["character_1", "character_2"],
            ["character_1", "character_2", "environment"],
        ],
    )
    def test_multi_reference_scene_and_canon_boards_still_generate(
        self, client, founder, role_list
    ):
        """No feature role means nothing is being edited — the grouping stays a
        feature, exactly as before."""
        token, cid = founder
        ids = _uploads(client, token, cid, len(role_list))
        r = _generate(client, token, cid, _body(role_list, ids))
        assert r.status_code == 200, r.text

    def test_images_is_unchanged_by_the_guard(self, client, founder):
        """/images submits under augment, where the feature roles compile to
        nothing — so the same board it always accepted is still accepted."""
        token, cid = founder
        ids = _uploads(client, token, cid, 3)
        r = _generate(client, token, cid,
                      _body(["character_1", "character_1", "hair"], ids, mode=None))
        assert r.status_code == 200, r.text
