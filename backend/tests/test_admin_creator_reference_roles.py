"""Reference role semantics — what each Admin Creator card is authority FOR.

Roles used to be advisory colour on a canon-grounded prompt. Under deliberate
mode they are the only thing telling the provider how to read four images that
can disagree with each other, so each one now has to state what it governs and,
where it has bitten us, what it does not.

The failure that produced this file: on 2026-08-22 a Gemini generation put
Davies in a three-piece suit but cut one sleeve at mid-forearm and painted his
tattoo band over it. Every card was ``unspecified``, the only image showing his
arms had rolled sleeves and visible marks, and the clothing reference was
cropped above the cuffs. Nothing in the request said which image was the outfit.

Two invariants run through everything below:

* **The selector, not the position, decides authority.** A Clothing card in
  slot 1 is clothing authority; an identity card in slot 4 is still identity.
* **/images is untouched.** The augment vocabulary and its four phrases are
  frozen, and an Admin Creator role reaching that path contributes no line —
  proven here rather than assumed.

Pure prompt-compilation tests: no provider, no database, no spend.
"""
import re

import pytest

from app.services.manual_references import (
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    ReferenceRole,
    ResolvedReference,
    build_reference_notes,
    parse_role,
)


class _Image:
    """Minimal CharacterImage stand-in — the audit reads only these."""

    def __init__(self, image_id: int) -> None:
        self.id = image_id
        self.file_path = f"m{image_id}.png"
        self.kind = "uploaded"


def ref(image_id: int, role: str, position: int) -> ResolvedReference:
    return ResolvedReference(_Image(image_id), parse_role(role), position)


def board(*roles: str) -> list[ResolvedReference]:
    """A card board, in card order, as the payload would carry it."""
    return [ref(10 + i, role, i) for i, role in enumerate(roles)]


def _referenced_positions(text: str) -> set[int]:
    """Every payload position the notes actually name.

    Handles both forms the compiler emits: "Reference image 3 is …" and the
    grouped "Reference images 1, 2 and 4 are …".
    """
    found: set[int] = set()
    for head in re.findall(r"Reference images? ([\d,\s]+?(?:and \d+)?) (?:is|are)\b", text):
        found.update(int(n) for n in re.findall(r"\d+", head))
    return found


def notes(*roles: str, mode: str = REFERENCE_MODE_DELIBERATE) -> str:
    return build_reference_notes(
        board(*roles), canon_ref_count=0, canon_grounded=False,
        refs_before_manual=0, mode=mode,
    )


# ── 1. Identity buckets ──────────────────────────────────────────────────────


class TestIdentityGrouping:
    def test_two_character_1_cards_are_one_person(self):
        """The grouping IS the feature: two photos of one face must read as one
        identity seen twice, not as two people."""
        text = notes("character_1", "character_1", "clothing", "environment")
        assert "Reference images 1 and 2 are all the same person, Person A" in text
        assert "treat them as one identity seen more than once" in text
        assert "Person B" not in text, "no second person was supplied"

    def test_three_character_1_cards_group_together(self):
        text = notes("character_1", "character_1", "character_1", "environment")
        assert "Reference images 1, 2 and 3 are all the same person, Person A" in text

    def test_a_single_identity_card_is_named_not_grouped(self):
        text = notes("character_1", "clothing")
        assert "Reference image 1 is Person A: reproduce that person's face" in text
        assert "same person" not in text

    def test_grouping_follows_the_selector_not_the_position(self):
        """Identity in the last slot is still identity; slot 1 being Clothing
        does not make it the character."""
        text = notes("clothing", "environment", "pose_composition", "character_1")
        assert "Reference image 4 is Person A" in text
        assert "Reference image 1 is the clothing and outfit to reproduce" in text

    def test_non_contiguous_cards_group_correctly(self):
        text = notes("character_1", "clothing", "character_1", "environment")
        assert "Reference images 1 and 3 are all the same person, Person A" in text

    def test_character_2_alone_is_person_b(self):
        text = notes("character_2", "character_2", "clothing")
        assert "Reference images 1 and 2 are all the same person, Person B" in text
        assert "Person A" not in text


class TestTwoDistinctPeople:
    ROLES = ("character_1", "character_2", "environment", "clothing")

    def test_both_buckets_name_two_separate_people(self):
        text = notes(*self.ROLES)
        assert "Reference image 1 is Person A" in text
        assert "Reference image 2 is Person B" in text

    def test_provider_is_told_they_are_different_people_in_one_scene(self):
        text = notes(*self.ROLES)
        assert "Person A and Person B are two DIFFERENT people" in text
        assert "both appear in this scene" in text

    def test_provider_is_forbidden_from_blending_them(self):
        """The named failure mode: averaging two supplied faces into one, or
        giving the second person the first one's features."""
        text = notes(*self.ROLES)
        assert "Keep their identities completely separate" in text
        for verb in ("blend", "average", "morph", "merge", "swap"):
            assert verb in text, f"identity separation must forbid {verb!r}"
        assert "faces, features or likenesses between them" in text

    def test_the_separation_clause_is_absent_with_only_one_person(self):
        """Asserting a second person who was never supplied would invite the
        model to invent one."""
        assert "DIFFERENT people" not in notes("character_1", "character_1", "clothing")
        assert "DIFFERENT people" not in notes("character_2", "environment")
        assert "DIFFERENT people" not in notes("clothing", "environment")

    def test_groups_survive_being_interleaved(self):
        text = notes("character_1", "character_2", "character_1", "character_2")
        assert "Reference images 1 and 3 are all the same person, Person A" in text
        assert "Reference images 2 and 4 are all the same person, Person B" in text
        assert "two DIFFERENT people" in text


# ── 2. Non-identity roles carry no identity authority ────────────────────────


class TestNoIdentityLeak:
    def test_clothing_is_outfit_authority_only(self):
        text = notes("character_1", "clothing")
        assert "Reference image 2 is the clothing and outfit to reproduce" in text
        assert "it is not identity evidence" in text

    def test_clothing_governs_sleeve_and_hem_length(self):
        """The Davies failure was a sleeve length question that no reference
        answered. The clothing role now answers it explicitly."""
        assert "how far the sleeves and hems extend" in notes("clothing")

    def test_environment_is_setting_authority_only(self):
        text = notes("environment")
        assert "the environment, setting, atmosphere and lighting to reproduce" in text
        assert "it is not identity evidence" in text
        assert "any person visible in it is not a character in this scene" in text

    def test_pose_is_composition_authority_only(self):
        """A person in a pose reference is staging, not a character — otherwise
        a stock couple photo becomes identity evidence."""
        text = notes("pose_composition")
        assert "the pose, framing and composition to follow" in text
        assert "it is not identity evidence" in text
        assert "any person visible in it is not a character in this scene" in text

    def test_other_claims_nothing_in_particular(self):
        assert "an additional visual reference for this scene" in notes("other")

    def test_unspecified_still_says_nothing(self):
        """Backwards compatible: the image is sent, the model is told nothing
        about it rather than something invented."""
        assert notes("unspecified") == ""
        text = notes("unspecified", "clothing")
        assert "Reference image 1" not in text
        assert "Reference image 2 is the clothing" in text


# ── 3. Permanent marks: design authority, NOT a visibility demand ────────────


class TestTattooRole:
    def test_it_carries_mark_design_and_placement_authority(self):
        text = notes("tattoo_mark")
        assert "permanent-mark evidence" in text
        assert "how the marks look and where on the body they sit" in text

    def test_it_does_not_require_a_covered_mark_to_be_shown(self):
        """The whole point. A mark reference must never argue with the outfit —
        that is the exposed-forearm failure in a different costume."""
        text = notes("tattoo_mark")
        assert "does NOT mean any mark must be visible" in text
        assert "a mark the clothing in this scene covers stays covered" in text

    def test_it_coexists_with_clothing_without_contradiction(self):
        text = notes("character_1", "clothing", "tattoo_mark")
        assert "how far the sleeves and hems extend" in text
        assert "stays covered" in text


# ── 4. Boards: duplicates and four-card combinations ─────────────────────────


class TestBoardCombinations:
    @pytest.mark.parametrize(
        "roles",
        [
            ("character_1", "character_1", "environment", "clothing"),
            ("character_1", "character_2", "environment", "clothing"),
            ("character_1", "character_2", "character_2", "environment"),
            ("character_1", "clothing", "tattoo_mark", "pose_composition"),
            ("character_1", "character_1", "character_1", "character_1"),
            ("clothing", "clothing", "environment", "environment"),
            ("unspecified", "unspecified", "unspecified", "unspecified"),
        ],
    )
    def test_every_combination_compiles(self, roles):
        """Duplicate roles are valid; no combination may raise or drop a card."""
        text = notes(*roles)
        if set(roles) == {"unspecified"}:
            assert text == ""
            return
        assert text.startswith(" SUPPLIED REFERENCES — ")
        # Every card that claims something is named, and nothing else is.
        expected = {i for i, role in enumerate(roles, start=1) if role != "unspecified"}
        assert _referenced_positions(text) == expected

    def test_four_identical_identity_cards_are_one_person(self):
        text = notes("character_1", "character_1", "character_1", "character_1")
        assert "Reference images 1, 2, 3 and 4 are all the same person, Person A" in text
        assert "DIFFERENT people" not in text

    def test_duplicate_attribute_roles_each_get_their_own_line(self):
        text = notes("clothing", "clothing")
        assert text.count("is the clothing and outfit to reproduce") == 2
        assert "Reference image 1 is the clothing" in text
        assert "Reference image 2 is the clothing" in text

    def test_identity_lines_lead_the_block(self):
        """Identity is the strongest claim and the one the rest are qualified
        against, so it must not arrive after three attribute sentences."""
        text = notes("clothing", "environment", "pose_composition", "character_1")
        assert text.index("Person A") < text.index("the clothing and outfit")

    def test_numbering_follows_payload_position(self):
        text = notes("environment", "clothing")
        assert "Reference image 1 is the environment" in text
        assert "Reference image 2 is the clothing" in text


# ── 5. Provenance ────────────────────────────────────────────────────────────


class TestAuditProvenance:
    def test_identity_cards_record_their_group(self):
        """So a past generation can be shown to have grouped two cards as one
        person rather than as two."""
        a1, a2, b1, cl = board("character_1", "character_1", "character_2", "clothing")
        assert a1.describe(sent=True)["identity_group"] == "person_a"
        assert a2.describe(sent=True)["identity_group"] == "person_a"
        assert b1.describe(sent=True)["identity_group"] == "person_b"
        assert "identity_group" not in cl.describe(sent=True)

    def test_the_role_itself_is_always_recorded(self):
        for role in ("character_1", "character_2", "clothing", "environment",
                     "tattoo_mark", "pose_composition", "other", "unspecified"):
            entry = ref(1, role, 0).describe(sent=True)
            assert entry["role"] == role
            assert entry["position"] == 0
            assert entry["sent"] is True

    def test_a_dropped_card_still_records_its_role_and_group(self):
        entry = ref(1, "character_2", 3).describe(sent=False, reason="reference_budget_exceeded")
        assert entry["sent"] is False
        assert entry["role"] == "character_2"
        assert entry["identity_group"] == "person_b"
        assert entry["reason"] == "reference_budget_exceeded"


# ── 6. /images is untouched ──────────────────────────────────────────────────


class TestAugmentUnchanged:
    def test_the_four_frozen_phrases_are_byte_identical(self):
        """These strings are what every canon-grounded generation has sent."""
        text = build_reference_notes(
            board("character_appearance", "clothing", "environment", "other"),
            canon_ref_count=2, canon_grounded=True,
        )
        assert text == (
            " SUPPLIED REFERENCES — "
            "Reference image 3 is supporting appearance reference for this character. "
            "Reference image 4 is the clothing and outfit to reproduce. "
            "Reference image 5 is the environment, setting and lighting to reproduce. "
            "Reference image 6 is an additional visual reference for this scene. "
            "The character's identity is defined by the locked description and character "
            "reference images above; the supplied references below inform this scene only "
            "and never override that identity."
        )

    def test_omitting_the_mode_is_augment(self):
        with_default = build_reference_notes(
            board("clothing"), canon_ref_count=1, canon_grounded=True
        )
        explicit = build_reference_notes(
            board("clothing"), canon_ref_count=1, canon_grounded=True,
            mode=REFERENCE_MODE_AUGMENT,
        )
        assert with_default == explicit

    def test_admin_creator_roles_say_nothing_under_augment(self):
        """A surface that never offered these roles cannot be changed by them.
        They fall through to no line, exactly like UNSPECIFIED.

        Enumerated from the enum rather than hand-listed, so a role added to the
        Admin Creator vocabulary in future cannot quietly skip this guard by not
        being written down here.
        """
        for role in ReferenceRole:
            if role in (
                ReferenceRole.CHARACTER_APPEARANCE,
                ReferenceRole.CLOTHING,
                ReferenceRole.ENVIRONMENT,
                ReferenceRole.OTHER,
            ):
                continue  # the four frozen /images phrases, asserted above
            assert build_reference_notes(
                board(role.value), canon_ref_count=0, canon_grounded=False,
                mode=REFERENCE_MODE_AUGMENT,
            ) == "", f"{role.value} acquired meaning on /images"

    def test_the_canon_precedence_clause_is_augment_only(self):
        """Deliberate bypasses canon, so there is no locked description for a
        reference to defer to — claiming otherwise would be a lie to the model."""
        deliberate = notes("character_1", "clothing")
        assert "never override that identity" not in deliberate

    def test_augment_still_ignores_an_unspecified_only_board(self):
        assert build_reference_notes(
            board("unspecified", "unspecified"), canon_ref_count=3, canon_grounded=True
        ) == ""


# ── 7. Role parsing ──────────────────────────────────────────────────────────


class TestRoleParsing:
    def test_every_offered_role_round_trips(self):
        for role in ("character_appearance", "character_1", "character_2", "clothing",
                     "environment", "tattoo_mark", "pose_composition", "other",
                     "unspecified"):
            assert parse_role(role) == ReferenceRole(role)

    def test_absent_role_is_unspecified(self):
        assert parse_role(None) == ReferenceRole.UNSPECIFIED
        assert parse_role("") == ReferenceRole.UNSPECIFIED

    def test_an_invented_role_is_still_refused(self):
        """A typo'd role would otherwise change what the model is told without
        anyone noticing — unchanged behaviour, re-pinned against the new enum."""
        from app.services.manual_references import ManualReferenceError

        with pytest.raises(ManualReferenceError) as exc:
            parse_role("character_3")
        assert "character_1" in exc.value.detail
