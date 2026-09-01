"""Free text is optional only when the board already states the operation.

Admin Creator's cards compile to an explicit instruction — "Required changes to
Person A: replace Person A's hair with the hair from reference image 2" — so
demanding that the founder also type "change the hair" made the prompt a place
to repeat the selector rather than to add anything.

The permission is narrow on purpose. A board qualifies only if BOTH hold:

* its ROLES describe a complete operation (a feature role in play, or Person A
  with a pose), and
* compiling it actually produces reference instructions.

The second condition is what makes an empty provider prompt unreachable rather
than merely unlikely — it re-runs the real compiler rather than trusting the
shape rule to imply the outcome.

Everything else stays prompt-required, and /images is untouched: it submits
under ``augment``, where every Admin Creator role compiles to nothing at all.
"""
import pytest

from app.services.manual_references import (
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    ReferenceRole,
    ResolvedReference,
    board_is_self_describing,
    build_reference_notes,
    describe_board_operation,
    parse_role,
)


class _Image:
    def __init__(self, image_id: int) -> None:
        self.id = image_id
        self.file_path = f"m{image_id}.png"
        self.kind = "uploaded"


def board(*roles: str) -> list[ResolvedReference]:
    return [ResolvedReference(_Image(10 + i), parse_role(r), i) for i, r in enumerate(roles)]


def self_describing(*roles: str) -> bool:
    return board_is_self_describing([parse_role(r) for r in roles])


def notes(*roles: str) -> str:
    return build_reference_notes(
        board(*roles), canon_ref_count=0, canon_grounded=False,
        refs_before_manual=0, mode=REFERENCE_MODE_DELIBERATE,
    )


# ── Boards that may omit the prompt ──────────────────────────────────────────


class TestSelfDescribingBoards:
    @pytest.mark.parametrize(
        "roles",
        [
            ("character_1", "hair"),                       # refine, one feature
            ("character_1", "hair", "eyebrows"),            # refine, several
            ("character_1", "character_2", "hair"),         # refine wins
            ("eyes", "nose", "mouth_lips", "face_shape"),   # construct
            ("hair",),                                      # construct, minimal
            ("character_2", "eyes"),                        # construct
            ("character_1", "pose_composition"),            # canon card
            ("character_1", "pose_composition", "clothing"),
        ],
    )
    def test_these_boards_state_their_own_operation(self, roles):
        assert self_describing(*roles)

    @pytest.mark.parametrize(
        "roles",
        [
            ("character_1", "hair"),
            ("eyes", "nose"),
            ("character_1", "pose_composition"),
        ],
    )
    def test_and_all_of_them_compile_to_real_instructions(self, roles):
        """The second condition. A shape that qualifies must also produce
        text — otherwise an empty prompt would reach the provider empty."""
        assert notes(*roles).strip()


# ── Boards that must still carry a prompt ────────────────────────────────────


class TestPromptStillRequired:
    @pytest.mark.parametrize(
        "roles",
        [
            ("character_1", "character_2"),        # two people, no event
            ("character_1",),                      # a person, no operation
            ("character_1", "clothing"),
            ("clothing", "environment"),
            ("tattoo_mark",),
            ("pose_composition",),                 # framing with no subject
            ("environment", "environment"),
            ("unspecified", "unspecified"),
            ("other",),
            ("character_appearance", "clothing"),
        ],
    )
    def test_these_boards_do_not_describe_a_generation(self, roles):
        assert not self_describing(*roles)

    def test_an_empty_board_describes_nothing(self):
        assert not board_is_self_describing([])

    def test_two_identity_buckets_are_who_not_what(self):
        """Person A and Person B name the cast, never the scene."""
        assert not self_describing("character_1", "character_2")

    def test_an_unspecified_board_compiles_to_nothing_at_all(self):
        """The case the second condition exists for: this shape is already
        rejected, and if it ever were not, the notes are empty."""
        assert not self_describing("unspecified", "unspecified")
        assert notes("unspecified", "unspecified") == ""

    def test_pose_without_an_identity_is_not_enough(self):
        """Framing with nobody in it says nothing about who to render."""
        assert not self_describing("pose_composition", "environment")


# ── The library row still gets a name ────────────────────────────────────────


class TestBoardSummary:
    def test_a_refinement_names_the_attributes_changed(self):
        assert describe_board_operation(
            [ReferenceRole.CHARACTER_1, ReferenceRole.HAIR, ReferenceRole.EYEBROWS]
        ) == "Refine Person A — hair, eyebrows"

    def test_a_construction_names_its_sources(self):
        assert describe_board_operation(
            [ReferenceRole.EYES, ReferenceRole.NOSE]
        ) == "Construct a face — eyes, nose"

    def test_a_pose_pass_says_so(self):
        assert describe_board_operation(
            [ReferenceRole.CHARACTER_1, ReferenceRole.POSE_COMPOSITION]
        ) == "Pose Person A"

    def test_repeated_features_are_not_repeated_in_the_summary(self):
        assert describe_board_operation(
            [ReferenceRole.CHARACTER_1, ReferenceRole.HAIR, ReferenceRole.HAIR]
        ) == "Refine Person A — hair"

    def test_it_never_returns_an_empty_summary(self):
        """A blank prompt_summary would leave an unidentifiable library row."""
        for roles in ([], [ReferenceRole.CLOTHING], [ReferenceRole.CHARACTER_1]):
            assert describe_board_operation(roles).strip()


# ── Roles only: never counts, positions or board size ────────────────────────


class TestIndependentOfBoardSize:
    def test_order_does_not_change_the_verdict(self):
        assert self_describing("hair", "character_1") == self_describing("character_1", "hair")

    def test_a_board_larger_than_the_current_budget_still_resolves(self):
        assert self_describing(
            "character_1", "eyes", "nose", "mouth_lips", "hair", "eyebrows", "clothing"
        )

    def test_duplicates_do_not_change_the_verdict(self):
        assert self_describing("character_1", "hair", "hair")
        assert not self_describing("clothing", "clothing", "clothing")


# ── /images is untouched ─────────────────────────────────────────────────────


class TestImagesSurfaceUnaffected:
    @pytest.mark.parametrize(
        "roles",
        [("character_1", "hair"), ("eyes", "nose"), ("character_1", "pose_composition")],
    )
    def test_a_self_describing_board_compiles_to_nothing_under_augment(self, roles):
        """The safety property behind the route's deliberate-only gate: even a
        qualifying board carries no instructions on /images, so a blank prompt
        there could only ever produce an empty provider prompt."""
        assert build_reference_notes(
            board(*roles), canon_ref_count=0, canon_grounded=False,
            mode=REFERENCE_MODE_AUGMENT,
        ) == ""
