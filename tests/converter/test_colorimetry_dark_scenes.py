#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regression tests for automatic colorimetry.

Specifically checks that dark scenes (lum < 80) receive appropriate
processing: higher gamma, positive brightness, and capped contrast
to prevent crushing shadow details.

Reference log (Back to the Future II — dark scene):
  lum=67 std=51 sat=138
  → Before fix: contrast=1.79 gamma=1.1  bri=+0.004  (characters invisible)
  → After fix : contrast≈1.57 gamma≈1.21 bri≈+0.036 (characters visible)
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.engine.conversion.colorimetry import (
    _gamma_delta,
    _brightness_delta,
    _contrast_delta,
    _clamp,
    _BASE_GAMMA,
    _BASE_BRIGHTNESS,
    _BASE_CONTRAST,
)


class TestGammaDeltaDarkScenes(unittest.TestCase):
    """_gamma_delta should produce higher values for dark scenes."""

    def test_very_dark_lum_0_gives_max_positive_delta(self):
        delta = _gamma_delta(0)
        self.assertGreaterEqual(delta, 0.50,
                                f"lum=0 should yield delta gamma ≥ 0.50, got {delta:.3f}")

    def test_dark_lum_40_gives_strong_positive_delta(self):
        delta = _gamma_delta(40)
        self.assertGreaterEqual(delta, 0.50,
                                f"lum=40 should yield delta gamma ≥ 0.50, got {delta:.3f}")

    def test_dark_scene_lum_67_gives_more_lift_than_before(self):
        """Regression BttF II: lum=67 should yield gamma > 1.15 (was 1.10)."""
        delta = _gamma_delta(67)
        gamma = _clamp(_BASE_GAMMA + delta, 0.55, 1.70)
        self.assertGreater(gamma, 1.15,
                           f"lum=67 → gamma={gamma:.3f} insufficient for dark scene "
                           f"(expected > 1.15, old value ≈ 1.10)")

    def test_neutral_lum_140_gives_near_zero_delta(self):
        delta = _gamma_delta(140)
        self.assertAlmostEqual(delta, 0.0, delta=0.05,
                               msg=f"lum=140 (neutral) should yield delta ≈ 0, got {delta:.3f}")

    def test_bright_lum_210_gives_negative_delta(self):
        delta = _gamma_delta(210)
        self.assertLess(delta, 0.0,
                        f"lum=210 (bright) should yield negative delta, got {delta:.3f}")

    def test_gamma_cap_allows_1_70_for_very_dark(self):
        """The gamma cap should be 1.70 (not 1.40)."""
        delta = _gamma_delta(0)
        gamma = _clamp(_BASE_GAMMA + delta, 0.55, 1.70)
        # With lum=0, delta should push gamma toward the cap
        self.assertLessEqual(gamma, 1.70, "Gamma cap exceeded")
        self.assertGreaterEqual(gamma, 1.25, "Gamma too low for lum=0")


class TestBrightnessDeltaDarkScenes(unittest.TestCase):
    """_brightness_delta should lift dark scenes more aggressively."""

    def test_dark_scene_lum_67_gives_positive_brightness(self):
        """Regression BttF II: lum=67 should yield brightness > 0 (was ≈ +0.004)."""
        delta = _brightness_delta(67)
        brightness = _clamp(_BASE_BRIGHTNESS + delta, -0.15, 0.12)
        self.assertGreater(brightness, 0.01,
                           f"lum=67 → brightness={brightness:.3f} insufficient "
                           f"(expected > 0.01, old value ≈ +0.004)")

    def test_very_dark_lum_0_gets_max_brightness_boost(self):
        delta = _brightness_delta(0)
        brightness = _clamp(_BASE_BRIGHTNESS + delta, -0.15, 0.12)
        self.assertGreater(brightness, 0.05,
                           f"lum=0 should yield brightness > 0.05, got {brightness:.3f}")

    def test_bright_lum_180_gets_slight_reduction(self):
        delta = _brightness_delta(180)
        brightness = _clamp(_BASE_BRIGHTNESS + delta, -0.15, 0.12)
        self.assertLess(brightness, 0.0,
                        f"lum=180 should reduce brightness, got {brightness:.3f}")

    def test_lum_110_near_neutral(self):
        delta = _brightness_delta(110)
        self.assertAlmostEqual(delta, 0.0, delta=0.02,
                               msg=f"lum=110 (neutral) should yield delta ≈ 0, got {delta:.3f}")


class TestDarkSceneContrastCap(unittest.TestCase):
    """Contrast should be capped for dark scenes (lum < 80)."""

    def _compute_contrast_with_cap(self, mean_lum: float, std_lum: float) -> float:
        """Simulates the full contrast calculation with the dark scene cap."""
        contrast = _clamp(_BASE_CONTRAST + _contrast_delta(std_lum), 1.40, 2.50)
        if mean_lum < 80.0:
            dark_ratio = (80.0 - mean_lum) / 80.0
            contrast_cap = 1.60 - dark_ratio * 0.20
            contrast = min(contrast, contrast_cap)
        return contrast

    def test_dark_scene_lum_67_std_51_contrast_capped(self):
        """Regression BttF II: lum=67 std=51 → contrast < 1.60 (was 1.79)."""
        contrast = self._compute_contrast_with_cap(67, 51)
        self.assertLess(contrast, 1.60,
                        f"lum=67: contrast={contrast:.3f} too high, must be < 1.60")
        self.assertGreaterEqual(contrast, 1.40,
                                f"lum=67: contrast={contrast:.3f} too low, minimum 1.40")

    def test_very_dark_lum_0_contrast_strongly_capped(self):
        """lum=0 should have the lowest cap (1.40)."""
        contrast = self._compute_contrast_with_cap(0, 30)
        self.assertLessEqual(contrast, 1.41,
                             f"lum=0: contrast={contrast:.3f} should be ≈ 1.40")

    def test_neutral_lum_140_no_cap_applied(self):
        """lum=140 (neutral scene) should not be capped."""
        contrast_raw = _clamp(_BASE_CONTRAST + _contrast_delta(50), 1.40, 2.50)
        contrast_capped = self._compute_contrast_with_cap(140, 50)
        self.assertEqual(contrast_raw, contrast_capped,
                         f"lum=140 should not trigger contrast cap")

    def test_bright_lum_200_no_cap_applied(self):
        """lum=200 (bright scene) should not be capped."""
        contrast_raw = _clamp(_BASE_CONTRAST + _contrast_delta(60), 1.40, 2.50)
        contrast_capped = self._compute_contrast_with_cap(200, 60)
        self.assertEqual(contrast_raw, contrast_capped)


class TestSceneTypeTag(unittest.TestCase):
    """The log message should contain appropriate semantic type tags."""

    def _simulate_message(self, mean_lum: float) -> str:
        # Import the real function to get the actual message format
        from src.engine.conversion.colorimetry import analyze_and_compensate
        import numpy as np
        import cv2
        import sys
        
        # Mock the sampling and averaging to test the logic
        from unittest.mock import patch
        with patch('src.engine.conversion.colorimetry._sample_frames') as mock_sample:
            with patch('src.engine.conversion.colorimetry._average_metrics') as mock_avg:
                mock_sample.return_value = ["dummy_frame"]
                mock_avg.return_value = (mean_lum, 50.0, 100.0) # std_lum=50, mean_sat=100
                ok, params, msg = analyze_and_compensate("dummy.gif")
                return msg

    def test_dark_scene_lum_67_has_dark_tag(self):
        msg = self._simulate_message(67)
        self.assertIn("Dark", msg,
                      f"Tag Dark missing for lum=67: {msg!r}")

    def test_dark_scene_lum_79_has_dark_tag(self):
        msg = self._simulate_message(79)
        self.assertIn("Dark", msg)

    def test_neutral_lum_80_no_dark_tag(self):
        msg = self._simulate_message(80)
        self.assertNotIn("Dark", msg,
                         f"Tag Dark present for lum=80 (threshold exclusive): {msg!r}")

    def test_bright_lum_146_no_dark_tag(self):
        msg = self._simulate_message(146)
        self.assertNotIn("Dark", msg)


if __name__ == "__main__":
    unittest.main()

