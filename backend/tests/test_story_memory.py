"""Unit tests for StoryLab Canon Engine v2 — Hard Truth Enforcement.

Covers the six requirements from the task spec:
  (a) alive hard truth is injected into the prompt canon block
  (b) "Angelo is dead" is detected as a contradiction
  (c) "the late Angelo Baptiste" is detected
  (d) pronoun death pattern is detected when Angelo is stored as father in relationships
  (e) current_status cannot be downgraded from alive to dead by memory merge
  (f) contradiction detection fires from characters[name]["current_status"] too
"""
import pytest


# ── fixture helpers ───────────────────────────────────────────────────────────

def _make_memory_with_alive_char(name: str = "Angelo Baptiste") -> dict:
    """Return a minimal memory dict with a single living character."""
    return {
        "canon": {
            "hard_truths": [f"{name} is alive at story start."],
            "world_rules": [],
            "forbidden_contradictions": [f'Never write: "{name} is dead"'],
        },
        "characters": {
            name: {
                "identity": ["Role: Father"],
                "current_status": ["alive"],
                "abilities_or_traits": [],
                "goals": [],
                "growth": [],
                "secrets": [],
            }
        },
        "relationships": [],
        "open_threads": [],
        "recent_events": [],
    }


def _make_memory_with_status_only(name: str = "Angelo Baptiste") -> dict:
    """Memory with alive status in characters but NOT in hard_truths (tests surface 2)."""
    return {
        "canon": {
            "hard_truths": ["Story premise: A family drama."],
            "world_rules": [],
            "forbidden_contradictions": [],
        },
        "characters": {
            name: {
                "identity": [],
                "current_status": ["alive"],
                "abilities_or_traits": [],
                "goals": [],
                "growth": [],
                "secrets": [],
            }
        },
        "relationships": [],
        "open_threads": [],
        "recent_events": [],
    }


# ── (a) alive hard truth appears in the canon injection block ─────────────────

class TestCanonInjectionBlock:
    def test_alive_hard_truth_in_injection_block(self):
        """Alive hard truth for a character is present in the built injection block."""
        from app.services.story_memory import build_canon_injection_block

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        block = build_canon_injection_block(memory)

        assert "Angelo Baptiste is alive" in block

    def test_injection_block_contains_absolute_authority_header(self):
        """The injection block now contains the absolute-authority instruction."""
        from app.services.story_memory import build_canon_injection_block

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        block = build_canon_injection_block(memory)

        assert "Hard canon is absolute" in block

    def test_injection_block_contains_explicit_forbidden_phrases(self):
        """Seeded memory generates explicit forbidden phrases in the injection block."""
        from app.services.story_memory import (
            build_canon_injection_block,
            seed_memory_from_story_creation,
        )

        memory = seed_memory_from_story_creation(
            title="Test Story",
            characters=[{"name": "Angelo Baptiste"}],
        )
        block = build_canon_injection_block(memory)

        assert 'Never write: "Angelo Baptiste is dead"' in block


# ── (b) "Angelo is dead" / death phrases detected via hard_truths ─────────────

class TestDeathPhraseDetection:
    def test_basic_is_dead_detected(self):
        """'Angelo Baptiste is dead' triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "Angelo walked into the room. But Angelo Baptiste is dead, Leo thought."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0
        assert any("Angelo Baptiste" in r for r in result)

    def test_died_detected(self):
        """'Angelo Baptiste died' triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "She remembered how Angelo Baptiste died in the summer."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_had_died_detected(self):
        """'Angelo Baptiste had died' (new pattern) triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "Everyone knew Angelo Baptiste had died long ago."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_was_dead_detected(self):
        """'Angelo Baptiste was dead' (new pattern) triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "It was clear that Angelo Baptiste was dead."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_no_contradiction_on_clean_text(self):
        """Clean text with no death phrases returns empty list."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "Angelo Baptiste smiled at his son. They spoke for an hour."
        result = check_for_contradictions(text, memory)
        assert result == []


# ── (c) "the late Angelo Baptiste" detected ───────────────────────────────────

class TestLateTitlePhrases:
    def test_the_late_name_detected(self):
        """'the late Angelo Baptiste' triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "Leo stood before the portrait of the late Angelo Baptiste."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0
        assert any("Angelo Baptiste" in r for r in result)

    def test_late_name_without_the_detected(self):
        """'late Angelo Baptiste' (without 'the') also triggers."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "They gathered to honour late Angelo Baptiste."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_deceased_name_detected(self):
        """'deceased Angelo Baptiste' triggers a contradiction."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "The estate of deceased Angelo Baptiste was disputed."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0


# ── (d) pronoun death pattern when Angelo is father in relationships ───────────

class TestPronounDeathPatterns:
    def _make_memory_with_parent_rel(self, parent_name: str = "Angelo Baptiste") -> dict:
        memory = _make_memory_with_alive_char(parent_name)
        memory["relationships"] = [
            {
                "a": parent_name,
                "b": "Leo Baptiste",
                "status": "father-son",
                "tension": "moderate",
                "recent_change": "",
            }
        ]
        return memory

    def test_his_dead_father_detected(self):
        """'his dead father' triggers when Angelo is stored as a father in relationships."""
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory_with_parent_rel("Angelo Baptiste")
        text = "Leo thought of his dead father as he walked through the house."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0
        assert any("Angelo Baptiste" in r for r in result)

    def test_her_dead_father_detected(self):
        """'her dead father' also triggers the pronoun pattern check."""
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory_with_parent_rel("Angelo Baptiste")
        text = "She grieved for her dead father every night."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_his_late_father_detected(self):
        """'his late father' triggers the pronoun pattern check."""
        from app.services.story_memory import check_for_contradictions

        memory = self._make_memory_with_parent_rel("Angelo Baptiste")
        text = "He inherited everything from his late father."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_pronoun_pattern_no_false_positive_without_relationship(self):
        """'his dead father' does not trigger when no father relationship is stored."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_alive_char("Angelo Baptiste")
        # No relationships — pronoun pattern should not match
        text = "He thought of his dead father from some other family."
        result = check_for_contradictions(text, memory)
        # May still get a death phrase hit from hard_truths if name appears — but
        # Angelo Baptiste's name is not in this text at all, so result should be empty.
        assert result == []


# ── (e) current_status cannot be downgraded alive → dead by memory merge ──────

class TestCurrentStatusProtection:
    def test_alive_status_not_overwritten_by_dead(self):
        """_apply_memory_updates must not downgrade 'alive' to 'dead'."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty, _merge_existing_into

        base = _deep_copy_empty()
        _merge_existing_into(base, _make_memory_with_alive_char("Angelo Baptiste"))

        # Simulate LLM trying to set status to dead
        updates = {
            "character_updates": {
                "Angelo Baptiste": {
                    "current_status": ["dead"],
                }
            }
        }
        _apply_memory_updates(base, updates)

        # Status must still contain "alive"
        status = base["characters"]["Angelo Baptiste"]["current_status"]
        assert any("alive" in str(s).lower() for s in status), (
            f"Expected 'alive' to be preserved, got: {status}"
        )

    def test_deceased_status_not_overwritten(self):
        """'deceased' in new_status is also rejected when character is alive."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty, _merge_existing_into

        base = _deep_copy_empty()
        _merge_existing_into(base, _make_memory_with_alive_char("Angelo Baptiste"))

        updates = {
            "character_updates": {
                "Angelo Baptiste": {
                    "current_status": ["deceased"],
                }
            }
        }
        _apply_memory_updates(base, updates)

        status = base["characters"]["Angelo Baptiste"]["current_status"]
        assert any("alive" in str(s).lower() for s in status)

    def test_status_downgrade_allowed_when_death_in_hard_truths(self):
        """Status CAN be set to dead when a death hard truth already exists."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty, _merge_existing_into

        base = _deep_copy_empty()
        memory_with_death_truth = _make_memory_with_alive_char("Angelo Baptiste")
        memory_with_death_truth["canon"]["hard_truths"].append(
            "Angelo Baptiste died in Chapter 5."
        )
        _merge_existing_into(base, memory_with_death_truth)

        updates = {
            "character_updates": {
                "Angelo Baptiste": {
                    "current_status": ["dead"],
                }
            }
        }
        _apply_memory_updates(base, updates)

        status = base["characters"]["Angelo Baptiste"]["current_status"]
        assert any("dead" in str(s).lower() for s in status)

    def test_non_alive_to_dead_is_allowed(self):
        """Characters without an alive status CAN have their status set to dead."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        base = _deep_copy_empty()
        base["characters"]["Minor Character"] = {
            "identity": [],
            "current_status": ["present"],
            "abilities_or_traits": [],
            "goals": [],
            "growth": [],
            "secrets": [],
        }

        updates = {
            "character_updates": {
                "Minor Character": {
                    "current_status": ["dead"],
                }
            }
        }
        _apply_memory_updates(base, updates)

        status = base["characters"]["Minor Character"]["current_status"]
        assert any("dead" in str(s).lower() for s in status)


# ── (f) contradiction detection from characters[name]["current_status"] ────────

class TestStatusSurfaceDetection:
    def test_death_detected_via_character_status_not_hard_truths(self):
        """check_for_contradictions fires from current_status="alive" even if
        the character is NOT listed in hard_truths as 'X is alive'."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_status_only("Angelo Baptiste")
        # Verify hard_truths does NOT contain "is alive" for this character
        hard_truths_lower = " ".join(memory["canon"]["hard_truths"]).lower()
        assert "angelo baptiste is alive" not in hard_truths_lower

        text = "Angelo Baptiste was dead before the winter came."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0
        assert any("Angelo Baptiste" in r for r in result)

    def test_late_title_detected_via_character_status(self):
        """Late-title phrase detected via character_status surface."""
        from app.services.story_memory import check_for_contradictions

        memory = _make_memory_with_status_only("Angelo Baptiste")
        text = "The house once belonged to the late Angelo Baptiste."
        result = check_for_contradictions(text, memory)
        assert len(result) > 0

    def test_no_duplicate_contradictions_when_both_surfaces_match(self):
        """When character is in BOTH hard_truths and character_status, no duplicate
        contradiction entry is added for the same violation."""
        from app.services.story_memory import check_for_contradictions

        # This memory has character in BOTH surfaces
        memory = _make_memory_with_alive_char("Angelo Baptiste")
        text = "Angelo Baptiste is dead."
        result = check_for_contradictions(text, memory)
        # Should have exactly 1 contradiction, not 2
        assert len(result) == 1


# ── seed function generates explicit forbidden phrases ────────────────────────

class TestSeedMemory:
    def test_seed_generates_explicit_forbidden_phrases(self):
        """seed_memory_from_story_creation adds explicit death-phrase forbidden entries."""
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(
            title="Test Story",
            characters=[{"name": "Angelo Baptiste"}],
        )
        forbidden = memory["canon"]["forbidden_contradictions"]
        assert any('Never write: "Angelo Baptiste is dead"' in f for f in forbidden)
        assert any('Never write: "Angelo Baptiste died"' in f for f in forbidden)
        assert any('Never write: "the late Angelo Baptiste"' in f for f in forbidden)

    def test_seed_sets_character_current_status_alive(self):
        """Seeded character starts with current_status=['alive']."""
        from app.services.story_memory import seed_memory_from_story_creation

        memory = seed_memory_from_story_creation(
            characters=[{"name": "Angelo Baptiste"}],
        )
        assert memory["characters"]["Angelo Baptiste"]["current_status"] == ["alive"]

    def test_apply_memory_updates_auto_appends_forbidden_phrases_when_alive(self):
        """_apply_memory_updates auto-appends forbidden death phrases when status is set to alive."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        base = _deep_copy_empty()
        # Start with no forbidden contradictions
        assert base["canon"]["forbidden_contradictions"] == []

        updates = {
            "character_updates": {
                "Marco Rossi": {
                    "current_status": ["alive"],
                }
            }
        }
        _apply_memory_updates(base, updates)

        forbidden = base["canon"]["forbidden_contradictions"]
        assert any('Never write: "Marco Rossi is dead"' in f for f in forbidden)
        assert any('Never write: "Marco Rossi died"' in f for f in forbidden)
        assert any('Never write: "the late Marco Rossi"' in f for f in forbidden)

    def test_apply_memory_updates_forbidden_phrases_are_deduplicated(self):
        """Calling _apply_memory_updates twice does not duplicate forbidden phrases."""
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty

        base = _deep_copy_empty()
        updates = {
            "character_updates": {
                "Marco Rossi": {"current_status": ["alive"]}
            }
        }
        _apply_memory_updates(base, updates)
        count_before = len(base["canon"]["forbidden_contradictions"])
        _apply_memory_updates(base, updates)
        count_after = len(base["canon"]["forbidden_contradictions"])
        assert count_after == count_before, (
            f"Duplicate entries added: before={count_before}, after={count_after}"
        )


# ── Canon Engine v3: forbidden inference tests ────────────────────────────────

def _make_family_memory() -> dict:
    """Memory fixture: Angelo alive, Demon Wolf trait, father-son relationship with Leo."""
    return {
        "canon": {
            "hard_truths": ["Angelo Baptiste is alive at story start."],
            "world_rules": [],
            "forbidden_contradictions": ['Never write: "Angelo Baptiste is dead"'],
            "forbidden_inferences": [],
        },
        "characters": {
            "Angelo Baptiste": {
                "identity": ["Role: Father"],
                "current_status": ["alive"],
                "abilities_or_traits": ["Demon Wolf supernatural nature"],
                "goals": [],
                "growth": [],
                "secrets": [],
            }
        },
        "relationships": [
            {
                "a": "Angelo Baptiste",
                "b": "Leo Baptiste",
                "status": "father-son",
                "tension": "moderate",
                "recent_change": "",
            }
        ],
        "open_threads": [],
        "recent_events": [],
    }


class TestDisappearanceInferences:
    """Surface 3 / _check_alive_name: disappearance phrases blocked for living characters."""

    def test_disappeared_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Angelo Baptiste disappeared fifteen years ago and was never found.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("disappear" in r.lower() for r in result)

    def test_vanished_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Angelo Baptiste vanished without a trace the night everything changed.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("disappear" in r.lower() or "vanish" in r.lower() for r in result)

    def test_presumed_dead_name_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Angelo Baptiste was presumed dead after the incident at the docks.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("presumed dead" in r.lower() or "fake" in r.lower() for r in result)

    def test_faked_death_name_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Angelo Baptiste faked his death to protect his family from the council.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_no_false_positive_clean_text(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Angelo Baptiste greeted his son with a firm nod. Leo was grateful.",
            _make_family_memory(),
        )
        assert result == []


class TestGeneralInferencePhrases:
    """Surface 3: general phrases fired when any alive character is in memory."""

    def test_letting_world_believe_dead_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "He had spent fifteen years letting the world believe him dead.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("letting the world believe him dead" in r.lower() for r in result)

    def test_fake_death_general_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "The whole arrangement had been an elaborate fake death.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("fake death" in r.lower() or "faked" in r.lower() for r in result)

    def test_faked_his_death_general_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "He had faked his death to escape the pack.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_general_phrases_no_fire_when_no_living_chars(self):
        """General inference phrases must NOT fire when memory has no alive characters."""
        from app.services.story_memory import check_for_contradictions
        dead_memory = {
            "canon": {
                "hard_truths": ["Story premise: A ghost story."],
                "world_rules": [],
                "forbidden_contradictions": [],
                "forbidden_inferences": [],
            },
            "characters": {
                "Ghost": {
                    "identity": [],
                    "current_status": ["deceased"],
                    "abilities_or_traits": [],
                    "goals": [], "growth": [], "secrets": [],
                }
            },
            "relationships": [],
            "open_threads": [],
            "recent_events": [],
        }
        result = check_for_contradictions(
            "He had faked his death to escape the pack.",
            dead_memory,
        )
        assert result == []


class TestIdentityTransferInferences:
    """Surface 4: identity-transfer inferences blocked when family relationships exist."""

    def test_becoming_what_father_is_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Leo was becoming what his father is — ruthless, unstoppable.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("father" in r.lower() or "identity transfer" in r.lower() for r in result)

    def test_becoming_what_your_father_is_detected(self):
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "You are becoming what your father is, Leo. Accept it.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_becoming_what_name_is_detected(self):
        """'becoming what Angelo Baptiste is' triggers a name-based identity transfer check."""
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Step by step, Leo was becoming what Angelo Baptiste is.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("identity transfer" in r.lower() or "angelo baptiste" in r.lower() for r in result)

    def test_becoming_demon_wolf_detected(self):
        """'becoming the Demon Wolf' triggers trait-noun identity transfer check."""
        from app.services.story_memory import check_for_contradictions
        result = check_for_contradictions(
            "Leo stood at the threshold of becoming the Demon Wolf himself.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("demon wolf" in r.lower() for r in result)

    def test_identity_transfer_no_fire_without_family_rel(self):
        """Role-based phrases do NOT fire when memory has no family relationships."""
        from app.services.story_memory import check_for_contradictions
        no_rel_memory = {
            "canon": {
                "hard_truths": ["Angelo Baptiste is alive at story start."],
                "world_rules": [],
                "forbidden_contradictions": [],
                "forbidden_inferences": [],
            },
            "characters": {
                "Angelo Baptiste": {
                    "identity": [],
                    "current_status": ["alive"],
                    "abilities_or_traits": [],
                    "goals": [], "growth": [], "secrets": [],
                }
            },
            "relationships": [],  # no family relationship
            "open_threads": [],
            "recent_events": [],
        }
        result = check_for_contradictions(
            "You are becoming what your father is.",
            no_rel_memory,
        )
        # Role-based check requires a family relationship — should be empty
        assert result == []


class TestForbiddenInferencesSeeding:
    """seed_memory and injection block include forbidden inferences for living characters."""

    def test_seed_generates_disappearance_inferences(self):
        from app.services.story_memory import seed_memory_from_story_creation
        memory = seed_memory_from_story_creation(
            characters=[{"name": "Angelo Baptiste"}]
        )
        inferences = memory["canon"]["forbidden_inferences"]
        assert any("disappeared" in fi.lower() or "vanish" in fi.lower() for fi in inferences)
        assert any("estrangement" in fi.lower() or "distance" in fi.lower() for fi in inferences)

    def test_seed_inferences_are_deduplicated(self):
        from app.services.story_memory import seed_memory_from_story_creation
        memory = seed_memory_from_story_creation(
            characters=[{"name": "Angelo Baptiste"}, {"name": "Angelo Baptiste"}]
        )
        inferences = memory["canon"]["forbidden_inferences"]
        disappeared_entries = [fi for fi in inferences if "disappeared" in fi.lower()]
        unique = set(disappeared_entries)
        assert len(disappeared_entries) == len(unique), "Inference entries were duplicated"

    def test_injection_block_contains_forbidden_inferences_section(self):
        from app.services.story_memory import build_canon_injection_block, seed_memory_from_story_creation
        memory = seed_memory_from_story_creation(
            characters=[{"name": "Angelo Baptiste"}]
        )
        block = build_canon_injection_block(memory)
        assert "FORBIDDEN INFERENCES" in block
        assert "Angelo Baptiste" in block

    def test_apply_memory_updates_auto_appends_inferences_when_alive(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty
        base = _deep_copy_empty()
        updates = {
            "character_updates": {
                "Marco Rossi": {"current_status": ["alive"]}
            }
        }
        _apply_memory_updates(base, updates)
        inferences = base["canon"]["forbidden_inferences"]
        assert any("marco rossi" in fi.lower() for fi in inferences)
        assert any("disappeared" in fi.lower() or "vanish" in fi.lower() for fi in inferences)

    def test_forbidden_inferences_merged_by_merge_existing_into(self):
        from app.services.story_memory import _deep_copy_empty, _merge_existing_into
        source = _deep_copy_empty()
        source["canon"]["forbidden_inferences"] = ["Do not imply Angelo disappeared."]
        dest = _deep_copy_empty()
        _merge_existing_into(dest, source)
        assert "Do not imply Angelo disappeared." in dest["canon"]["forbidden_inferences"]

    def test_apply_memory_updates_new_forbidden_inferences(self):
        from app.services.story_memory import _apply_memory_updates, _deep_copy_empty
        base = _deep_copy_empty()
        updates = {"new_forbidden_inferences": ["Do not imply X faked their death."]}
        _apply_memory_updates(base, updates)
        assert "Do not imply X faked their death." in base["canon"]["forbidden_inferences"]


# ── Canon Engine v4: co-occurrence / substring detection ─────────────────────


class TestCooccurrenceDetection:
    """v4: sentence-level co-occurrence catches first-name-only disappearance references.

    Root cause of the original failure:
      text = "Angelo disappeared to protect you"
      stored name = "Angelo Baptiste"
      Full-name exact match "angelo baptiste disappeared" ← NOT in text → missed.
      Co-occurrence: "angelo" + "disappear" in same sentence → CAUGHT.
    """

    def test_first_name_disappear_to_protect_detected(self):
        """Core failing case: 'Angelo disappeared to protect you' must trigger detection."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "Angelo disappeared to protect you from what was coming.",
            _make_family_memory(),
        )
        assert len(result) > 0, (
            "Expected at least one violation for 'Angelo disappeared to protect you'"
        )
        assert any("disappear" in r.lower() for r in result)

    def test_first_name_only_vanished_detected(self):
        """'Angelo vanished' (first name only) must trigger detection."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "Angelo vanished the night everything changed.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("disappear" in r.lower() or "vanish" in r.lower() for r in result)

    def test_first_name_disappeared_because_detected(self):
        """'Angelo disappeared because he had to' must trigger."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "Angelo disappeared because he had no other choice.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_first_name_seemed_to_disappear_detected(self):
        """'Angelo seemed to disappear' (indirect phrasing) must trigger."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "To everyone around him, Angelo seemed to disappear overnight.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_disappeared_to_protect_general_pattern_detected(self):
        """'disappeared to protect' without a name triggers the general inference check."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "He had disappeared to protect the ones he loved.",
            _make_family_memory(),
        )
        assert len(result) > 0
        assert any("disappeared to protect" in r.lower() for r in result)

    def test_vanished_to_save_general_pattern_detected(self):
        """'vanished to save' without a name triggers the general inference check."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "She said he vanished to save the family from danger.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_full_name_still_detected(self):
        """Full name 'Angelo Baptiste disappeared' remains caught by exact phrase check."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "Angelo Baptiste disappeared fifteen years ago.",
            _make_family_memory(),
        )
        assert len(result) > 0

    def test_no_false_positive_no_disappear_verb(self):
        """First name in text without any disappearance verb → no violation."""
        from app.services.story_memory import check_for_contradictions

        result = check_for_contradictions(
            "Angelo stepped back into the shadows, watching from a distance.",
            _make_family_memory(),
        )
        assert result == []

    def test_no_false_positive_different_first_name(self):
        """Disappear verb in text but no matching first name → no co-occurrence violation."""
        from app.services.story_memory import check_for_contradictions

        # Memory has "Angelo Baptiste" — text uses "Marco disappeared"
        result = check_for_contradictions(
            "Marco disappeared into the crowd.",
            _make_family_memory(),
        )
        # "marco" does not match first name "angelo" → no co-occurrence hit
        # Also no full-name match. General pattern fires ("disappeared to"?) — no, just "disappeared"
        # General inference phrases don't include bare "disappeared"; alive chars are present
        # so Surface 3 fires only for specific general phrases. "marco disappeared" → only
        # co-occurrence check for "angelo" which fails. Result: empty.
        assert result == []

    def test_sentence_cooccur_helper_direct(self):
        """_sentence_cooccur_disappearance returns a snippet on match, None on miss."""
        from app.services.story_memory import _sentence_cooccur_disappearance

        snippet = _sentence_cooccur_disappearance("angelo", "Angelo disappeared to protect you.")
        assert snippet is not None
        assert "disappear" in snippet

        assert _sentence_cooccur_disappearance("angelo", "Angelo smiled and nodded.") is None
        assert _sentence_cooccur_disappearance("leo", "Angelo disappeared.") is None

    def test_short_fragment_not_checked(self):
        """Fragments shorter than 3 chars are skipped to avoid false positives."""
        from app.services.story_memory import _sentence_cooccur_disappearance

        assert _sentence_cooccur_disappearance("al", "Al disappeared.") is None


class TestCorrectionNoteBuilder:
    """_build_canon_correction_note generates targeted, character-specific instructions."""

    def test_note_names_alive_characters(self):
        from app.api.routes.storylab import _build_canon_correction_note

        note = _build_canon_correction_note(
            ["Forbidden inference: 'Angelo Baptiste is alive' — disappearance implied"],
            _make_family_memory(),
        )
        assert "Angelo Baptiste" in note

    def test_note_includes_disappearance_correction_when_relevant(self):
        from app.api.routes.storylab import _build_canon_correction_note

        note = _build_canon_correction_note(
            ["Forbidden inference: disappear detected"],
            _make_family_memory(),
        )
        assert "estrangement" in note.lower() or "distance" in note.lower()
        assert "NOT disappeared" in note or "have NOT disappeared" in note

    def test_note_does_not_include_disappearance_section_when_irrelevant(self):
        from app.api.routes.storylab import _build_canon_correction_note

        note = _build_canon_correction_note(
            ["Hard canon violated (hard_truths): 'Angelo Baptiste is alive' — matched: 'angelo is dead'"],
            _make_family_memory(),
        )
        # No disappearance keywords → disappearance-specific paragraph omitted
        assert "NOT disappeared" not in note

    def test_note_includes_rewrite_instruction(self):
        from app.api.routes.storylab import _build_canon_correction_note

        note = _build_canon_correction_note(
            ["some violation"],
            _make_family_memory(),
        )
        assert "rewrite" in note.lower()
