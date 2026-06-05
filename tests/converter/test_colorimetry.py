#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for dmd_auto_color.py

Covers:
  - _clamp()
  - _gamma_delta()       — continuous piecewise-linear interpolation
  - _contrast_delta()    — continuous piecewise-linear interpolation
  - _saturation_delta()  — continuous piecewise-linear interpolation
  - _average_metrics()   (with numpy)
  - analyze_and_compensate() — no-OpenCV path and structure checks
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.converter.colorimetry import (
    _BASE_BRIGHTNESS,
    _BASE_CONTRAST,
    _BASE_GAMMA,
    _BASE_SATURATION,
    _clamp,
    _contrast_delta,
    _gamma_delta,
    _saturation_delta,
    analyze_and_compensate,
)


# ─────────────────────────────────────────────────────────────────────────────
# _clamp
# ─────────────────────────────────────────────────────────────────────────────

class TestClampAutoColor(unittest.TestCase):

    def test_within_range(self):
        self.assertAlmostEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_below_min(self):
        self.assertAlmostEqual(_clamp(-5.0, 0.0, 10.0), 0.0)

    def test_above_max(self):
        self.assertAlmostEqual(_clamp(15.0, 0.0, 10.0), 10.0)

    def test_at_boundary(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 1.0), 0.0)
        self.assertAlmostEqual(_clamp(1.0, 0.0, 1.0), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# _gamma_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestGammaDelta(unittest.TestCase):
    """_gamma_delta now uses continuous piecewise-linear interpolation.

    Tests verify:
      - Exact values at knot boundaries (xp points in _linear_interp)
      - Clamping at the extremes (x=0 and x=255)
      - Monotonically non-increasing across the [0, 255] range
      - Continuity: adjacent inputs produce close outputs (no step jumps)
    """

    # ── Knot boundary values ──────────────────────────────────────────────────

    def test_knot_x0(self):
        self.assertAlmostEqual(_gamma_delta(0.0),   +0.40)

    def test_knot_x40(self):
        self.assertAlmostEqual(_gamma_delta(40.0),  +0.40)

    def test_knot_x75(self):
        self.assertAlmostEqual(_gamma_delta(75.0),  +0.20)

    def test_knot_x100(self):
        self.assertAlmostEqual(_gamma_delta(100.0), +0.08)

    def test_knot_x140(self):
        self.assertAlmostEqual(_gamma_delta(140.0),  0.00)

    def test_knot_x175(self):
        self.assertAlmostEqual(_gamma_delta(175.0), -0.10)

    def test_knot_x210(self):
        self.assertAlmostEqual(_gamma_delta(210.0), -0.20)

    def test_knot_x255(self):
        self.assertAlmostEqual(_gamma_delta(255.0), -0.30)

    # ── Clamping at extremes ──────────────────────────────────────────────────

    def test_below_minimum_clamped(self):
        # Values at or below the first knot (0) return the first fp value.
        self.assertAlmostEqual(_gamma_delta(-10.0), +0.40)

    def test_above_maximum_clamped(self):
        # Values at or above the last knot (255) return the last fp value.
        self.assertAlmostEqual(_gamma_delta(300.0), -0.30)

    # ── Monotonicity ──────────────────────────────────────────────────────────

    def test_monotonically_non_increasing(self):
        """gamma_delta must never increase as luminance increases."""
        prev = _gamma_delta(0.0)
        for lum in range(1, 256):
            curr = _gamma_delta(float(lum))
            self.assertLessEqual(
                curr, prev + 1e-9,
                f"Non-monotonic at lum={lum}: {prev:.4f} → {curr:.4f}"
            )
            prev = curr

    # ── Continuity / no step jumps ────────────────────────────────────────────

    def test_no_step_jump_at_175(self):
        """Old step boundary at 175 — difference must be tiny, not a full step."""
        diff = abs(_gamma_delta(176.0) - _gamma_delta(174.0))
        self.assertLess(diff, 0.02, f"Unexpected jump at lum≈175: {diff:.4f}")

    # ── Intermediate values are bounded ──────────────────────────────────────

    def test_intermediate_values_bounded(self):
        """Any x between two knots must produce a value between those knots' fp."""
        # Between knot 40 (+0.40) and knot 75 (+0.20)
        v = _gamma_delta(57.0)
        self.assertGreaterEqual(v, +0.20)
        self.assertLessEqual(v,   +0.40)


# ─────────────────────────────────────────────────────────────────────────────
# _contrast_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestContrastDelta(unittest.TestCase):
    """Continuous interpolation tests for _contrast_delta."""

    def test_knot_x0(self):
        self.assertAlmostEqual(_contrast_delta(0.0),  +0.70)

    def test_knot_x20(self):
        self.assertAlmostEqual(_contrast_delta(20.0), +0.70)

    def test_knot_x35(self):
        self.assertAlmostEqual(_contrast_delta(35.0), +0.45)

    def test_knot_x50(self):
        self.assertAlmostEqual(_contrast_delta(50.0), +0.20)

    def test_knot_x70(self):
        self.assertAlmostEqual(_contrast_delta(70.0),  0.00)

    def test_knot_x255(self):
        self.assertAlmostEqual(_contrast_delta(255.0), -0.15)

    def test_below_minimum_clamped(self):
        self.assertAlmostEqual(_contrast_delta(-5.0), +0.70)

    def test_above_maximum_clamped(self):
        self.assertAlmostEqual(_contrast_delta(300.0), -0.15)

    def test_monotonically_non_increasing(self):
        prev = _contrast_delta(0.0)
        for std in range(1, 256):
            curr = _contrast_delta(float(std))
            self.assertLessEqual(
                curr, prev + 1e-9,
                f"Non-monotonic at std={std}: {prev:.4f} → {curr:.4f}"
            )
            prev = curr

    def test_no_step_jump_at_70(self):
        diff = abs(_contrast_delta(71.0) - _contrast_delta(69.0))
        self.assertLess(diff, 0.05)


# ─────────────────────────────────────────────────────────────────────────────
# _saturation_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestSaturationDelta(unittest.TestCase):
    """Continuous interpolation tests for _saturation_delta."""

    def test_knot_x0(self):
        self.assertAlmostEqual(_saturation_delta(0.0),   +1.10)

    def test_knot_x10(self):
        self.assertAlmostEqual(_saturation_delta(10.0),  +1.10)

    def test_knot_x40(self):
        self.assertAlmostEqual(_saturation_delta(40.0),  +0.70)

    def test_knot_x80(self):
        self.assertAlmostEqual(_saturation_delta(80.0),  +0.30)

    def test_knot_x130(self):
        self.assertAlmostEqual(_saturation_delta(130.0),  0.00)

    def test_knot_x180(self):
        self.assertAlmostEqual(_saturation_delta(180.0), -0.30)

    def test_knot_x255(self):
        self.assertAlmostEqual(_saturation_delta(255.0), -0.60)

    def test_below_minimum_clamped(self):
        self.assertAlmostEqual(_saturation_delta(-5.0), +1.10)

    def test_above_maximum_clamped(self):
        self.assertAlmostEqual(_saturation_delta(300.0), -0.60)

    def test_monotonically_non_increasing(self):
        prev = _saturation_delta(0.0)
        for sat in range(1, 256):
            curr = _saturation_delta(float(sat))
            self.assertLessEqual(
                curr, prev + 1e-9,
                f"Non-monotonic at sat={sat}: {prev:.4f} → {curr:.4f}"
            )
            prev = curr

    def test_no_step_jump_at_130(self):
        diff = abs(_saturation_delta(131.0) - _saturation_delta(129.0))
        self.assertLess(diff, 0.05)


# ─────────────────────────────────────────────────────────────────────────────
# _average_metrics  (avec numpy)
# ─────────────────────────────────────────────────────────────────────────────

class TestAverageMetrics(unittest.TestCase):

    def setUp(self):
        try:
            import numpy as np
            import cv2
            self.np = np
            self.cv2 = cv2
        except ImportError:
            self.skipTest("numpy or opencv not available")

    def test_uniform_black_frame(self):
        from src.converter.colorimetry import _average_metrics
        frame = self.np.zeros((64, 128, 3), dtype=self.np.uint8)  # black BGR frame
        mean_lum, std_lum, mean_sat = _average_metrics([frame], self.cv2, self.np)
        self.assertAlmostEqual(mean_lum, 0.0, delta=1.0)
        self.assertAlmostEqual(std_lum, 0.0, delta=1.0)
        self.assertAlmostEqual(mean_sat, 0.0, delta=1.0)

    def test_uniform_white_frame(self):
        from src.converter.colorimetry import _average_metrics
        frame = self.np.full((64, 128, 3), 255, dtype=self.np.uint8)
        mean_lum, std_lum, mean_sat = _average_metrics([frame], self.cv2, self.np)
        self.assertGreater(mean_lum, 200.0)

    def test_multiple_frames_averages(self):
        from src.converter.colorimetry import _average_metrics
        dark  = self.np.zeros((64, 128, 3), dtype=self.np.uint8)
        light = self.np.full((64, 128, 3), 200, dtype=self.np.uint8)
        mean_lum, _, _ = _average_metrics([dark, light], self.cv2, self.np)
        # The average must be between the two extremes
        self.assertGreater(mean_lum, 0.0)
        self.assertLess(mean_lum, 200.0)


# ─────────────────────────────────────────────────────────────────────────────
# analyze_and_compensate
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeAndCompensate(unittest.TestCase):

    def test_returns_false_without_opencv(self):
        """Without OpenCV, must return (False, {}, message)."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("cv2", "numpy"):
                raise ImportError("not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            ok, params, msg = analyze_and_compensate("any.mp4")

        self.assertFalse(ok)
        self.assertEqual(params, {})
        self.assertIsInstance(msg, str)

    def test_result_params_keys_when_ok(self):
        """If analyze_and_compensate succeeds, all expected keys must be present."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("opencv/numpy not available")

        # Build a mock VideoCapture returning a synthetic frame
        frame = np.full((64, 128, 3), 100, dtype=np.uint8)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            cv2.CAP_PROP_FRAME_COUNT: 100,
            cv2.CAP_PROP_FPS:         25.0,
        }.get(prop, 0)
        mock_cap.read.return_value = (True, frame)
        mock_cap.set.return_value = None
        mock_cap.release.return_value = None

        with patch("cv2.VideoCapture", return_value=mock_cap):
            ok, params, msg = analyze_and_compensate("fake.mp4")

        if ok:
            expected_keys = [
                "contrast", "saturation", "brightness", "gamma",
                "sharpen_lum", "sharpen_chr", "dither"
            ]
            for key in expected_keys:
                self.assertIn(key, params, f"Missing key: {key}")

    def test_output_values_are_within_valid_ranges(self):
        """Result parameters must fall within their valid ranges."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("opencv/numpy not available")

        frame = np.full((64, 128, 3), 128, dtype=np.uint8)

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            cv2.CAP_PROP_FRAME_COUNT: 100,
            cv2.CAP_PROP_FPS:         25.0,
        }.get(prop, 0)
        mock_cap.read.return_value = (True, frame)
        mock_cap.set.return_value = None
        mock_cap.release.return_value = None

        with patch("cv2.VideoCapture", return_value=mock_cap):
            ok, params, msg = analyze_and_compensate("fake.mp4")

        if ok:
            self.assertGreaterEqual(params["contrast"],   1.40)
            self.assertLessEqual(params["contrast"],      2.50)
            self.assertGreaterEqual(params["saturation"], 0.90)
            self.assertLessEqual(params["saturation"],    3.50)
            self.assertGreaterEqual(params["gamma"],      0.55)
            self.assertLessEqual(params["gamma"],         1.40)
            self.assertGreaterEqual(params["brightness"], -0.15)
            self.assertLessEqual(params["brightness"],     0.10)

    def test_message_is_string(self):
        """The return message must always be a string."""
        ok, params, msg = analyze_and_compensate("nonexistent_file.mp4")
        self.assertIsInstance(msg, str)

    def test_baseline_constants_are_reasonable(self):
        """Baseline constants must fall within sensible ranges."""
        self.assertGreater(_BASE_CONTRAST,   1.0)
        self.assertGreater(_BASE_SATURATION, 1.0)
        self.assertGreater(_BASE_GAMMA,      0.5)
        self.assertLess(_BASE_GAMMA,         1.0)
        self.assertLess(abs(_BASE_BRIGHTNESS), 0.1)


if __name__ == "__main__":
    unittest.main()

