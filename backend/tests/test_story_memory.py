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
