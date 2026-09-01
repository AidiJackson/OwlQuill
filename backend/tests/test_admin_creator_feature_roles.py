"""Attribute-authority roles — Phase 2 visual character construction.

The eight facial/attribute roles exist to answer one question the board could
not previously ask: "take the eyes from THIS person and nothing else". Every
model we send references to treats a supplied face as a whole face by default,
so each role has to state the feature it governs AND deny the rest of the person
in the same breath. Both halves are pinned here, per role.

Above the per-image lines sit the three construction clauses, and they are what
make a staged build different from a scene:

* features with no Person A  → construct ONE new coherent person;
* features WITH Person A     → preserve Person A, change only the named
  attributes;
* no features at all         → nothing is added, and the compiled text is
  byte-identical to what the board produced before these roles existed.

That last one is the compatibility guarantee, and it is tested against a string
captured from a real production generation rather than against a
reimplementation of the rule.

Nothing here knows how many cards the board has. The derivation reads role
MEMBERSHIP only, so these tests deliberately include boards larger than the
current four-reference budget: the cap is an external constraint on what reaches
the provider, not part of the construction model.

Pure prompt-compilation tests: no provider, no database, no spend.
"""
import pytest

from app.services.manual_references import (
    REFERENCE_MODE_AUGMENT,
    REFERENCE_MODE_DELIBERATE,
    ReferenceRole,
    ResolvedReference,
    build_reference_notes,
    is_feature_role,
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
    return [ref(10 + i, role, i) for i, role in enumerate(roles)]


def notes(*roles: str, mode: str = REFERENCE_MODE_DELIBERATE) -> str:
    return build_reference_notes(
        board(*roles), canon_ref_count=0, canon_grounded=False,
        refs_before_manual=0, mode=mode,
    )


#: The eight attribute roles, each with a word that must appear in its line and
#: could not plausibly come from any other role's phrasing.
FEATURE_ROLES = [
    ("eyes", "eye shape"),
    ("nose", "bridge"),
    ("mouth_lips", "resting mouth line"),
    ("face_shape", "cheekbones"),
    ("eyebrows", "arch"),
    ("hair", "hairline"),
    ("facial_hair", "stubble"),
    ("skin_complexion", "freckles"),
]

FEATURE_ROLE_VALUES = [value for value, _ in FEATURE_ROLES]


# ── 1. Each role carries its own, specific authority ─────────────────────────


class TestFeatureAuthority:
    @pytest.mark.parametrize("role,marker", FEATURE_ROLES)
    def test_each_role_states_what_it_governs(self, role, marker):
        """Naming the feature is not enough — "the eyes" leaves the model to
        decide whether that includes the brow, the socket and the face around
        it, and it decides generously. Each line enumerates the specifics."""
        text = notes(role)
        assert marker in text, f"{role} did not carry its distinguishing evidence"

    @pytest.mark.parametrize("role,_marker", FEATURE_ROLES)
    def test_each_role_names_only_its_own_feature(self, role, _marker):
        """A feature line says "X only", so no card can be read as general
        appearance evidence."""
        assert " only:" in notes(role)

    def test_the_eight_roles_are_the_feature_set(self):
        """The test list and the module's own set cannot drift apart."""
        assert {parse_role(v) for v in FEATURE_ROLE_VALUES} == {
            r for r in ReferenceRole if is_feature_role(r)
        }


# ── 2. Attribute evidence is never identity evidence ─────────────────────────


class TestNoIdentityFromFeatures:
    @pytest.mark.parametrize("role,_marker", FEATURE_ROLES)
    def test_every_feature_denies_the_source_identity(self, role, _marker):
        """The whole point of the role. Without this clause a photo supplied as
        eye evidence arrives as a face."""
        text = notes(role)
        assert "is not this character" in text
        assert "do not copy" in text

    @pytest.mark.parametrize("role,_marker", FEATURE_ROLES)
    def test_no_feature_is_given_a_person_label(self, role, _marker):
        """Person A/Person B are identity buckets. A feature card must never
        acquire one, or the model gains a character nobody asked for."""
        text = notes(role)
        assert "Person A" not in text
        assert "Person B" not in text

    @pytest.mark.parametrize("role,_marker", FEATURE_ROLES)
    def test_features_record_no_identity_group(self, role, _marker):
        """Provenance side of the same rule: the audit must not show a feature
        card as having been grouped as a person."""
        entry = ref(1, role, 0).describe(sent=True)
        assert "identity_group" not in entry
        assert entry["role"] == role

    def test_a_feature_never_becomes_character_2(self):
        """Four feature cards are four evidence sources, not a second person."""
        text = notes("eyes", "nose", "mouth_lips", "face_shape")
        assert "Person B" not in text
        assert "two DIFFERENT people" not in text

    def test_features_are_declared_non_characters_collectively(self):
        text = notes("eyes", "hair")
        assert "They are not characters in this image" in text
        assert "not additional people in the scene" in text
        assert "must not be merged, averaged or carried across" in text


# ── 3. Pass 1 — construction ─────────────────────────────────────────────────


class TestConstructionPass:
    def test_features_without_person_a_build_one_new_person(self):
        text = notes("eyes", "nose", "mouth_lips", "face_shape")
        assert "ONE single coherent photorealistic person" in text
        assert "person who appears in none of the references" in text

    def test_construction_does_not_claim_to_refine_anyone(self):
        text = notes("eyes", "nose")
        assert "Person A is the identity of this image" not in text

    def test_a_single_feature_still_constructs(self):
        """No minimum card count — one feature and no identity is still a build."""
        assert "ONE single coherent photorealistic person" in notes("hair")

    def test_character_2_does_not_trigger_refinement(self):
        """Person B is a second person in a scene, not the subject being built.
        Treating features as edits to them would silently retarget the pass."""
        text = notes("character_2", "eyes")
        assert "ONE single coherent photorealistic person" in text
        assert "Person A is the identity of this image" not in text


# ── 4. Pass 2 — refinement ───────────────────────────────────────────────────


class TestRefinementPass:
    def test_person_a_plus_eyes_preserves_identity(self):
        """The headline Phase 2 case: take eye evidence, keep the face."""
        text = notes("character_1", "eyes")
        assert "Person A is the identity of this image and must be preserved exactly" in text
        assert "face, bone structure and likeness of Person A stay the same" in text
        assert "eye shape" in text

    def test_person_a_plus_hair_changes_hair_only(self):
        text = notes("character_1", "hair")
        assert "hairstyle, length, colour, texture and hairline" in text
        assert "replace Person A's hair with the hair from reference image 2" in text
        assert "Every attribute not in that list stays exactly as it is in Person A" in text
        assert "face, bone structure and likeness of Person A stay the same" in text

    def test_refinement_does_not_ask_for_a_new_person(self):
        """The two clauses are mutually exclusive. Emitting both would tell the
        model to preserve an identity and invent one in the same breath."""
        text = notes("character_1", "eyes", "hair")
        assert "ONE single coherent photorealistic person" not in text

    def test_person_a_identity_line_survives_refinement(self):
        text = notes("character_1", "eyes")
        assert "Reference image 1 is Person A" in text

    def test_multiple_person_a_cards_still_group_under_refinement(self):
        text = notes("character_1", "character_1", "hair")
        assert "Reference images 1 and 2 are all the same person, Person A" in text
        assert "Person A is the identity of this image" in text


# ── 4b. The selection IS the instruction ─────────────────────────────────────


#: Each role and the noun it is named by in a required-change list. Distinct
#: from the evidence markers above: these are the operative nouns an imperative
#: reads naturally with.
EDIT_NOUNS = [
    ("eyes", "eyes"),
    ("nose", "nose"),
    ("mouth_lips", "mouth and lips"),
    ("face_shape", "face shape and jawline"),
    ("eyebrows", "eyebrows"),
    ("hair", "hair"),
    ("facial_hair", "facial hair"),
    ("skin_complexion", "skin tone and complexion"),
]


class TestSelectionIsSufficient:
    """The structured cards must demand the operation on their own.

    Observed on Gemini 2026-08-22: a Hair + Eyebrows board changed the eyebrows
    and kept the original hair, because every sentence described what an image
    WAS and none required an outcome. The founder had to restate each card in
    prose for it to take effect — which made the selector decorative. These
    tests pin the sentences that removed that dependency.
    """

    @pytest.mark.parametrize("role,noun", EDIT_NOUNS)
    def test_each_feature_becomes_a_required_change_when_refining(self, role, noun):
        text = notes("character_1", role)
        assert f"replace Person A's {noun} with the {noun} from reference image 2" in text

    @pytest.mark.parametrize("role,noun", EDIT_NOUNS)
    def test_each_feature_becomes_a_required_source_when_constructing(self, role, noun):
        text = notes(role)
        assert f"take the {noun} from reference image 1" in text

    def test_refinement_lists_every_selected_change(self):
        """The Holly case: hair AND eyebrows, both demanded."""
        text = notes("character_1", "hair", "eyebrows")
        assert "Required changes to Person A:" in text
        assert "replace Person A's hair with the hair from reference image 2" in text
        assert "replace Person A's eyebrows with the eyebrows from reference image 3" in text

    def test_construction_lists_every_selected_source(self):
        text = notes("eyes", "nose", "mouth_lips", "face_shape")
        assert "Required sources:" in text
        assert "take the eyes from reference image 1" in text
        assert "take the nose from reference image 2" in text
        assert "take the mouth and lips from reference image 3" in text
        assert "take the face shape and jawline from reference image 4" in text

    @pytest.mark.parametrize(
        "roles", [("character_1", "hair"), ("eyes", "nose")]
    )
    def test_the_change_does_not_depend_on_the_free_text_prompt(self, roles):
        """The sentence that makes the selector self-sufficient."""
        assert "whether or not the scene description mentions it" in notes(*roles)

    def test_unselected_attributes_are_explicitly_preserved(self):
        text = notes("character_1", "hair")
        assert "Every attribute not in that list stays exactly as it is in Person A" in text

    def test_only_feature_roles_appear_in_the_list(self):
        """A required-change list naming clothing or pose would turn a scene
        instruction into an edit to the person."""
        text = notes("character_1", "hair", "clothing", "environment", "pose_composition")
        head = text.split("Required changes to Person A:", 1)[1]
        listed = head.split(". Make every change", 1)[0]
        assert "hair" in listed
        for absent in ("clothing", "outfit", "environment", "setting", "pose", "framing"):
            assert absent not in listed, f"{absent!r} leaked into the required-change list"

    def test_repeated_roles_are_grouped_not_contradicted(self):
        """Two Hair cards are two views of one hairstyle. Listing the same
        attribute twice would instruct the model to replace it with two
        different things."""
        text = notes("character_1", "hair", "hair")
        assert "replace Person A's hair with the hair from reference images 2 and 3" in text
        assert text.count("replace Person A's hair") == 1

    def test_list_numbering_follows_payload_position(self):
        text = notes("character_1", "clothing", "hair")
        assert "replace Person A's hair with the hair from reference image 3" in text

    def test_list_numbering_survives_a_canon_offset(self):
        """Under a payload where something precedes the manual block, the list
        must name the images the provider actually received."""
        text = build_reference_notes(
            board("character_1", "hair"), canon_ref_count=2, canon_grounded=False,
            refs_before_manual=2, mode=REFERENCE_MODE_DELIBERATE,
        )
        assert "replace Person A's hair with the hair from reference image 4" in text

    def test_character_2_plus_features_lists_sources_not_edits(self):
        text = notes("character_2", "hair")
        assert "Required sources:" in text
        assert "Required changes to Person A:" not in text


# ── 5. Precedence ────────────────────────────────────────────────────────────


class TestPrecedence:
    def test_the_order_is_stated_in_full(self):
        text = notes("character_1", "eyes", "clothing", "environment")
        assert (
            "the identity of the person comes first, then the feature references "
            "for the attribute each is named for, then pose and framing, then "
            "clothing, then environment" in text
        )

    def test_clothing_cannot_outrank_identity(self):
        text = notes("character_1", "eyes", "clothing")
        assert "the identity of the person comes first" in text
        assert "it is not identity evidence" in text  # the clothing line itself

    def test_environment_cannot_outrank_identity(self):
        text = notes("character_1", "hair", "environment")
        assert "the identity of the person comes first" in text

    def test_pose_ranks_below_features(self):
        text = notes("character_1", "face_shape", "pose_composition")
        assert "then pose and framing, then clothing, then environment" in text

    def test_identity_precedence_cannot_veto_a_required_change(self):
        """The interaction that needed the reword. Placed after a
        required-change list, an unqualified "the identity of the person comes
        first" is readable as permission to refuse the hair change in order to
        protect Person A — which is exactly the bug the list exists to fix."""
        text = notes("character_1", "hair", "clothing")
        assert "Where these references disagree on anything not listed as a required change" in text
        assert "If these references disagree, resolve" not in text
        # The hierarchy itself is unchanged for everything else.
        assert "the identity of the person comes first" in text

    def test_the_required_change_list_precedes_the_tie_break(self):
        text = notes("character_1", "hair", "clothing")
        assert text.index("Required changes to Person A:") < text.index(
            "Where these references disagree"
        )

    def test_features_alone_need_no_tie_break(self):
        """Nothing can contend, so the clause is not worth its length."""
        text = notes("eyes", "nose", "mouth_lips")
        assert "Where these references disagree" not in text

    def test_a_lone_contender_with_a_feature_does_get_one(self):
        assert "Where these references disagree" in notes("eyes", "clothing")


# ── 6. Backwards compatibility ───────────────────────────────────────────────


#: Captured verbatim from production image 2116 (job
#: 4ad2b2b773e34d82a11eb1513d35f398, 2026-08-22, compiled_prompt_sha8=2059c510).
#: A real four-card deliberate board that generated successfully BEFORE the
#: attribute roles existed. If Phase 2 changes this string, it changed a
#: workflow that was already working.
PRODUCTION_DELIBERATE_NOTES = (
    " SUPPLIED REFERENCES — "
    "Reference image 1 is Person A: reproduce that person's face and likeness "
    "exactly. "
    "Reference image 2 is Person B: reproduce that person's face and likeness "
    "exactly. "
    "Person A and Person B are two DIFFERENT people and both appear in this "
    "scene. Keep their identities completely separate: do not blend, average, "
    "morph, merge or swap faces, features or likenesses between them. "
    "Reference image 3 is the environment, setting, atmosphere and lighting to "
    "reproduce; it is not identity evidence, and any person visible in it is "
    "not a character in this scene. "
    "Reference image 4 is the clothing and outfit to reproduce, including how "
    "the garments are worn and how far the sleeves and hems extend; it is not "
    "identity evidence."
)


class TestFeatureFreeBoardsAreUnchanged:
    def test_the_captured_production_board_is_byte_identical(self):
        """The strongest guard available: a string a paid generation actually
        received, replayed through the current compiler."""
        assert (
            notes("character_1", "character_2", "environment", "clothing")
            == PRODUCTION_DELIBERATE_NOTES
        )

    @pytest.mark.parametrize(
        "roles",
        [
            ("character_1", "pose_composition"),
            ("character_1", "character_2"),
            ("character_1", "clothing", "environment"),
            ("character_1", "tattoo_mark", "clothing"),
            ("pose_composition", "environment"),
            ("unspecified", "unspecified"),
            ("other",),
            ("character_appearance", "clothing"),
        ],
    )
    def test_no_construction_clause_without_a_feature_role(self, roles):
        """Every pre-Phase-2 board shape. None may acquire new text."""
        text = notes(*roles)
        for clause in (
            "They are not characters in this image",
            "ONE single coherent photorealistic person",
            "Person A is the identity of this image",
            "Where these references disagree",
        ):
            assert clause not in text, f"{roles} gained {clause!r}"

    def test_character_1_plus_pose_keeps_existing_posing_behaviour(self):
        text = notes("character_1", "pose_composition")
        assert text == (
            " SUPPLIED REFERENCES — "
            "Reference image 1 is Person A: reproduce that person's face and "
            "likeness exactly. "
            "Reference image 2 is the pose, framing and composition to follow; "
            "it is not identity evidence, and any person visible in it is not a "
            "character in this scene."
        )

    def test_two_person_semantics_are_untouched(self):
        text = notes("character_1", "character_2")
        assert "two DIFFERENT people and both appear in this scene" in text
        assert "do not blend, average, morph, merge or swap faces" in text
        assert "ONE single coherent photorealistic person" not in text


class TestImagesSurfaceUntouched:
    @pytest.mark.parametrize("role", FEATURE_ROLE_VALUES)
    def test_feature_roles_say_nothing_under_augment(self, role):
        """/images never offers these. If one arrives there it must compile to
        nothing, exactly like the other Admin Creator roles — that fall-through
        is the entire compatibility mechanism."""
        assert notes(role, mode=REFERENCE_MODE_AUGMENT) == ""

    def test_a_feature_role_cannot_alter_an_augment_board(self):
        with_feature = notes("clothing", "eyes", mode=REFERENCE_MODE_AUGMENT)
        without = notes("clothing", mode=REFERENCE_MODE_AUGMENT)
        assert with_feature == without

    def test_the_frozen_augment_phrases_are_unchanged(self):
        assert notes("character_appearance", "clothing", "environment", "other",
                     mode=REFERENCE_MODE_AUGMENT) == (
            " SUPPLIED REFERENCES — "
            "Reference image 1 is supporting appearance reference for this character. "
            "Reference image 2 is the clothing and outfit to reproduce. "
            "Reference image 3 is the environment, setting and lighting to reproduce. "
            "Reference image 4 is an additional visual reference for this scene."
        )


# ── 7. The board size is not part of the model ───────────────────────────────


class TestIndependentOfBoardSize:
    """The four-card cap is a reference-BUDGET constraint enforced elsewhere
    (MAX_MANUAL_REFERENCES, the merge policy, the provider's own limit). None of
    the construction logic may assume it, so that raising the budget later is a
    change to budgeting alone.
    """

    def test_eight_features_still_build_one_person(self):
        text = notes(*FEATURE_ROLE_VALUES)
        assert "ONE single coherent photorealistic person" in text
        assert text.count("They are not characters in this image") == 1

    def test_every_feature_is_described_in_a_nine_card_board(self):
        text = notes("character_1", *FEATURE_ROLE_VALUES)
        for _role, marker in FEATURE_ROLES:
            assert marker in text
        assert "Person A is the identity of this image" in text

    def test_numbering_follows_payload_position_beyond_four(self):
        text = notes("character_1", "eyes", "nose", "hair", "clothing", "environment")
        assert "Reference image 5 is the clothing" in text
        assert "Reference image 6 is the environment" in text

    def test_clauses_appear_once_regardless_of_feature_count(self):
        text = notes("character_1", "eyes", "nose", "hair", "eyebrows")
        assert text.count("Person A is the identity of this image") == 1
        assert text.count("Where these references disagree") == 1


# ── 8. Clause ordering ───────────────────────────────────────────────────────


class TestClauseOrder:
    def test_identity_leads_and_the_contract_trails(self):
        """Identity first because it is the strongest claim in the set; the
        construction clauses last because they instruct on the set as a whole
        and image models weight trailing instructions well."""
        text = notes("character_1", "eyes", "clothing")
        assert (
            text.index("Reference image 1 is Person A")
            < text.index("Reference image 2 is the eyes only")
            < text.index("They are not characters in this image")
            < text.index("Person A is the identity of this image")
            < text.index("Where these references disagree")
        )
