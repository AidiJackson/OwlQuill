"""Regression tests for t-shirt / short-sleeve tattoo visibility.

Runtime root cause confirmed:
  _detect_visible_body_regions returned set() for prompts containing "t-shirt"
  because "t-shirt" was absent from _BOTH_ARMS_SIGNALS.

  Cascade: visible_regions={} → tattoo_visibility_requested=False → body_canon_str=""
           → sleeve_enforcement_str="" → tattoo_layout suppressed → zero tattoo signal.

Fix: added "t-shirt", "tshirt", "tee shirt", "tee-shirt",
     "short sleeve", "short-sleeve", "short sleeved", "short-sleeved"
     to _BOTH_ARMS_SIGNALS.
"""
import pytest

from app.api.routes.image_generator import _detect_visible_body_regions


class TestShortSleeveVisibility:
    """Short-sleeve garments must expose both arms."""

    def test_fitted_charcoal_tshirt(self):
        """Original failing prompt — fitted charcoal t-shirt must expose both arms."""
        vis = _detect_visible_body_regions(
            "leonardo sitting in a garden wearing a fitted charcoal t-shirt and shorts"
        )
        assert "right_arm" in vis, f"right_arm missing from {vis}"
        assert "left_arm" in vis, f"left_arm missing from {vis}"

    def test_tshirt_no_hyphen(self):
        """'tshirt' (no hyphen) must expose both arms."""
        vis = _detect_visible_body_regions("black tshirt")
        assert "right_arm" in vis
        assert "left_arm" in vis

    def test_tee_shirt_two_words(self):
        """'tee shirt' must expose both arms."""
        vis = _detect_visible_body_regions("grey tee shirt")
        assert "right_arm" in vis
        assert "left_arm" in vis

    def test_short_sleeve_tshirt_compound(self):
        """'short-sleeve t-shirt' must expose both arms."""
        vis = _detect_visible_body_regions("short-sleeve t-shirt")
        assert "right_arm" in vis
        assert "left_arm" in vis


class TestCoveredGarmentsNotVisible:
    """Covering garments must NOT expose arms."""

    def test_hoodie_not_visible(self):
        vis = _detect_visible_body_regions("wearing a hoodie")
        assert "right_arm" not in vis
        assert "left_arm" not in vis

    def test_leather_jacket_not_visible(self):
        vis = _detect_visible_body_regions("wearing a leather jacket")
        assert "right_arm" not in vis
        assert "left_arm" not in vis

    def test_suit_jacket_not_visible(self):
        vis = _detect_visible_body_regions("wearing a suit jacket")
        assert "right_arm" not in vis
        assert "left_arm" not in vis
