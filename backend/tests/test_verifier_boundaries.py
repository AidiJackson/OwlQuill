"""Verifier correctness — anatomical boundaries and face scorability.

The first soak reported 33/42 and the figure was invalid: several "failures"
were the VERIFIER being wrong, not the generator. Two reproducible
misclassifications, both at region borders:

  * a sleeve over the deltoid/shoulder cap was reported as TORSO ink, so a
    demonstrably clean chest scored as a canon violation;
  * a sleeve ending at the wrist was reported as HAND ink, inventing a hand
    violation on a character with no hand marks.

Plus back-facing images were scored on face similarity, turning "the face is
not visible" into "wrong character".

These tests pin the corrected boundaries and the three-state face rule. The
vision call itself is mocked: what is under test is the region contract and
the classification logic, which must be deterministic.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.mark_verifier import (
    _CHECK_REGIONS,
    _REGION_DEFINITIONS,
    _CHECK_PROMPT,
    verify_mark_regions,
)


def _mock_vision(payload: dict):
    """Patch the OpenAI client so the verifier sees `payload` as the model reply."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = json.dumps(payload)
    client = MagicMock()
    client.chat.completions.create.return_value = response
    mod = MagicMock()
    mod.OpenAI.return_value = client
    return patch.dict("sys.modules", {"openai": mod})


@pytest.fixture(autouse=True)
def _api_key():
    with patch("app.services.mark_verifier.settings") as s:
        s.OPENAI_API_KEY = "test-key"
        s.OPENAI_VISION_MODEL = "test-model"
        yield


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


# ── Region contract ───────────────────────────────────────────────────

class TestRegionDefinitions:
    def test_every_reported_region_is_defined(self):
        # An undefined region is exactly how the original prompt failed: it
        # named the regions and defined none of them.
        for region in _CHECK_REGIONS:
            if region == "on_clothing":
                continue
            assert region in _REGION_DEFINITIONS
            assert len(_REGION_DEFINITIONS[region]) > 20

    def test_torso_definition_excludes_the_shoulder(self):
        torso = _REGION_DEFINITIONS["torso"].lower()
        assert "deltoid" in torso and "shoulder" in torso
        assert "not torso" in torso

    def test_hands_definition_excludes_the_wrist(self):
        hands = _REGION_DEFINITIONS["hands"].lower()
        assert "wrist" in hands
        assert "not hands" in hands

    def test_arm_segments_stay_separate(self):
        assert "elbow" in _REGION_DEFINITIONS["upper_arms"].lower()
        assert "elbow" in _REGION_DEFINITIONS["forearms"].lower()
        assert "wrist" in _REGION_DEFINITIONS["forearms"].lower()

    def test_prompt_carries_the_definitions(self):
        for region, desc in _REGION_DEFINITIONS.items():
            assert region in _CHECK_PROMPT
            assert desc[:40] in _CHECK_PROMPT

    def test_prompt_requests_uncertain_bucket(self):
        assert "uncertain" in _CHECK_PROMPT


# ── Boundary classification ───────────────────────────────────────────
# Each case states the ground truth a correct verifier must produce for a
# character whose canon authorises ARM marks only.

ARMS_ONLY = frozenset({"upper_arms", "forearms"})


class TestBoundaryClassification:
    def test_shoulder_ink_is_not_a_torso_violation(self):
        # The Pan false positive, as a contract: sleeve over the deltoid.
        with _mock_vision({"marked_regions": ["upper_arms"], "uncertain": [],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == []
        assert "torso" not in v["observed"]

    def test_chest_ink_is_a_torso_violation(self):
        # The inverse must still fire, or the fix has blinded the verifier.
        with _mock_vision({"marked_regions": ["torso"], "uncertain": [],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["torso"]

    def test_wrist_ink_is_not_a_hand_violation(self):
        with _mock_vision({"marked_regions": ["forearms"], "uncertain": [],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == []

    def test_hand_dorsum_ink_is_a_hand_violation(self):
        with _mock_vision({"marked_regions": ["hands"], "uncertain": [],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["hands"]

    def test_hand_ink_is_allowed_when_canon_authorises_hands(self):
        with _mock_vision({"marked_regions": ["hands"], "uncertain": [],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY | {"hands"})
        assert v["violations"] == []

    def test_uncertain_border_reading_is_not_a_violation(self):
        with _mock_vision({"marked_regions": ["upper_arms"], "uncertain": ["torso"],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == []
        assert v["uncertain"] == ["torso"]
        # ...but it is still surfaced for manual audit rather than discarded.
        assert v["uncertain_violations"] == ["torso"]

    def test_uncertain_never_shadows_a_confident_reading(self):
        with _mock_vision({"marked_regions": ["torso"], "uncertain": ["torso"],
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["torso"]
        assert v["uncertain"] == []

    def test_on_clothing_is_reported_independently(self):
        with _mock_vision({"marked_regions": ["upper_arms"], "uncertain": [],
                           "on_clothing": True}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["on_clothing"] is True
        assert v["violations"] == []

    def test_unknown_region_names_are_ignored(self):
        with _mock_vision({"marked_regions": ["torso", "elbow", "nonsense"],
                           "uncertain": [], "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["observed"] == ["torso"]

    def test_parse_failure_is_not_scorable_not_a_violation(self):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "not json"
        client = MagicMock()
        client.chat.completions.create.return_value = response
        mod = MagicMock()
        mod.OpenAI.return_value = client
        with patch.dict("sys.modules", {"openai": mod}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["ok"] is False
        assert v["violations"] == []
        assert v["skip_reason"] == "parse_error"


# ── Face scorability ──────────────────────────────────────────────────

class TestFaceScorability:
    def test_back_facing_prompts_detected(self):
        from app.services.face_verifier import prompt_is_face_away
        for p in ("Davies from behind, shirtless", "seen from behind at the bar",
                  "back view of the character", "walking away down the corridor"):
            assert prompt_is_face_away(p) is True

    def test_normal_prompts_are_not_face_away(self):
        from app.services.face_verifier import prompt_is_face_away
        for p in ("Davies in his office", "Summer at her desk",
                  "close-up portrait", "shirtless in the gym"):
            assert prompt_is_face_away(p) is False

    def test_production_prompt_unchanged_by_default(self):
        # The generation path must not shift because the harness needed a new
        # field: visibility assessment is strictly opt-in.
        from app.services import face_verifier as fv
        assert "face_visible" not in fv._COMPARE_PROMPT
        assert "face_visible" in fv._VISIBILITY_CLAUSE

    def test_passes_treats_unverifiable_as_pass(self):
        from app.services.face_verifier import passes
        assert passes({"ok": False, "skip_reason": "api_error"}, 0.6) is True

    def test_passes_threshold_not_weakened(self):
        from app.services.face_verifier import passes
        assert passes({"ok": True, "match": True, "similarity": 0.59}, 0.6) is False
        assert passes({"ok": True, "match": True, "similarity": 0.61}, 0.6) is True


# ── Harness scoring logic ─────────────────────────────────────────────

class TestHarnessScoring:
    def _score(self, mv, authority, expect):
        sys_path_setup()
        from mark_soak import score_marks
        return score_marks(mv, authority, expect)

    def test_missing_expected_mark_fails_when_skin_is_bare(self):
        v = self._score({"ok": True, "observed": [], "violations": [],
                         "on_clothing": False, "bare_regions": ["forearms"]},
                        ARMS_ONLY, ["forearms"])
        assert v["state"] == "FAIL"
        assert v["missing"] == ["forearms"]

    def test_covered_region_is_not_a_missing_mark(self):
        # A gym scene that dresses the character in hand wraps hides the hands.
        # Absent ink there is correct behaviour, not a canon breach — counting
        # it measures the harness, not the generator.
        v = self._score({"ok": True, "observed": [], "violations": [],
                         "on_clothing": False, "bare_regions": ["forearms"]},
                        ARMS_ONLY | {"hands"}, ["hands"])
        assert v["state"] == "PASS"
        assert v["missing"] == []
        assert v["covered_not_scorable"] == ["hands"]

    def test_expectation_intersected_with_authority(self):
        # A character without hand marks is never failed for lacking hand ink.
        v = self._score({"ok": True, "observed": ["forearms"], "violations": [],
                         "on_clothing": False, "bare_regions": ["forearms", "hands"]},
                        ARMS_ONLY, ["hands"])
        assert v["state"] == "PASS"
        assert v["missing"] == []

    def test_unverifiable_is_not_scorable(self):
        v = self._score({"ok": False, "skip_reason": "api_error"}, ARMS_ONLY, ["forearms"])
        assert v["state"] == "NOT_SCORABLE"

    def test_clean_run_passes(self):
        v = self._score({"ok": True, "observed": ["forearms"], "violations": [],
                         "on_clothing": False, "bare_regions": ["forearms"]},
                        ARMS_ONLY, ["forearms"])
        assert v["state"] == "PASS"

    def test_on_clothing_alone_fails(self):
        v = self._score({"ok": True, "observed": ["forearms"], "violations": [],
                         "on_clothing": True, "bare_regions": ["forearms"]},
                        ARMS_ONLY, ["forearms"])
        assert v["state"] == "FAIL"


# ── Border guards ─────────────────────────────────────────────────────
# Prompt-level definitions alone did NOT stop the vision model calling
# wrist-adjacent ink "hands": it recurred six times in the corrected run. The
# discriminating binary question overrides the loose list.

class TestBorderGuards:
    def test_wrist_ink_demoted_when_border_question_denies_hand_ink(self):
        with _mock_vision({"marked_regions": ["forearms", "hands"], "uncertain": [],
                           "bare_regions": ["forearms", "hands"],
                           "hand_or_finger_ink": False, "chest_or_abdomen_ink": False,
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert "hands" not in v["observed"]
        assert v["violations"] == []
        assert "hands" in v["demoted"]

    def test_genuine_hand_ink_survives_the_guard(self):
        with _mock_vision({"marked_regions": ["hands"], "uncertain": [],
                           "bare_regions": ["hands"],
                           "hand_or_finger_ink": True, "chest_or_abdomen_ink": False,
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["hands"]
        assert v["demoted"] == []

    def test_deltoid_ink_demoted_when_chest_question_denies(self):
        with _mock_vision({"marked_regions": ["upper_arms", "torso"], "uncertain": [],
                           "bare_regions": ["upper_arms", "torso"],
                           "hand_or_finger_ink": False, "chest_or_abdomen_ink": False,
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert "torso" not in v["observed"]
        assert v["violations"] == []

    def test_genuine_chest_ink_survives_the_guard(self):
        with _mock_vision({"marked_regions": ["torso"], "uncertain": [],
                           "bare_regions": ["torso"],
                           "hand_or_finger_ink": False, "chest_or_abdomen_ink": True,
                           "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["torso"]

    def test_absent_border_answer_does_not_demote(self):
        # A model that omits the key must not silently blind the verifier.
        with _mock_vision({"marked_regions": ["hands"], "uncertain": [],
                           "bare_regions": ["hands"], "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert v["violations"] == ["hands"]

    def test_missing_bare_regions_key_assumes_all_bare(self):
        # Never invent coverage — that would hide genuine missing marks.
        with _mock_vision({"marked_regions": [], "uncertain": [], "on_clothing": False}):
            v = verify_mark_regions(PNG, ARMS_ONLY)
        assert set(v["bare_regions"]) >= {"forearms", "hands", "torso"}


def sys_path_setup():
    import sys
    from pathlib import Path
    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
