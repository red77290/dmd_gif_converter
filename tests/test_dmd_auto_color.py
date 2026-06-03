#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests unitaires pour dmd_auto_color.py

Couvre :
  - _clamp()
  - _gamma_delta()
  - _contrast_delta()
  - _saturation_delta()
  - _average_metrics()  (avec numpy)
  - analyze_and_compensate() — chemin sans OpenCV et vérifications de structure
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from dmd_auto_color import (
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

    def test_very_dark(self):
        # mean_lum < 40 → +0.40
        self.assertAlmostEqual(_gamma_delta(20.0), +0.40)
        self.assertAlmostEqual(_gamma_delta(0.0),  +0.40)

    def test_dark(self):
        # 40 ≤ mean_lum < 75 → +0.20
        self.assertAlmostEqual(_gamma_delta(50.0), +0.20)

    def test_slightly_dark(self):
        # 75 ≤ mean_lum < 100 → +0.08
        self.assertAlmostEqual(_gamma_delta(90.0), +0.08)

    def test_normal(self):
        # 100 ≤ mean_lum < 140 → 0.00
        self.assertAlmostEqual(_gamma_delta(120.0), 0.00)

    def test_slightly_bright(self):
        # 140 ≤ mean_lum < 175 → -0.10
        self.assertAlmostEqual(_gamma_delta(160.0), -0.10)

    def test_bright(self):
        # 175 ≤ mean_lum < 210 → -0.20
        self.assertAlmostEqual(_gamma_delta(190.0), -0.20)

    def test_very_bright(self):
        # mean_lum ≥ 210 → -0.30
        self.assertAlmostEqual(_gamma_delta(220.0), -0.30)
        self.assertAlmostEqual(_gamma_delta(255.0), -0.30)


# ─────────────────────────────────────────────────────────────────────────────
# _contrast_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestContrastDelta(unittest.TestCase):

    def test_very_flat(self):
        # std_lum < 20 → +0.70
        self.assertAlmostEqual(_contrast_delta(10.0), +0.70)

    def test_dull(self):
        # 20 ≤ std_lum < 35 → +0.45
        self.assertAlmostEqual(_contrast_delta(25.0), +0.45)

    def test_slightly_below_average(self):
        # 35 ≤ std_lum < 50 → +0.20
        self.assertAlmostEqual(_contrast_delta(40.0), +0.20)

    def test_good(self):
        # 50 ≤ std_lum < 70 → 0.00
        self.assertAlmostEqual(_contrast_delta(60.0), 0.00)

    def test_high_contrast(self):
        # std_lum ≥ 70 → -0.15
        self.assertAlmostEqual(_contrast_delta(80.0), -0.15)
        self.assertAlmostEqual(_contrast_delta(100.0), -0.15)


# ─────────────────────────────────────────────────────────────────────────────
# _saturation_delta
# ─────────────────────────────────────────────────────────────────────────────

class TestSaturationDelta(unittest.TestCase):

    def test_near_greyscale(self):
        # mean_sat < 10 → +1.10
        self.assertAlmostEqual(_saturation_delta(5.0),  +1.10)
        self.assertAlmostEqual(_saturation_delta(0.0),  +1.10)

    def test_low_sat(self):
        # 10 ≤ mean_sat < 40 → +0.70
        self.assertAlmostEqual(_saturation_delta(20.0), +0.70)

    def test_slightly_muted(self):
        # 40 ≤ mean_sat < 80 → +0.30
        self.assertAlmostEqual(_saturation_delta(60.0), +0.30)

    def test_normal_colour(self):
        # 80 ≤ mean_sat < 130 → 0.00
        self.assertAlmostEqual(_saturation_delta(100.0), 0.00)

    def test_vivid(self):
        # 130 ≤ mean_sat < 180 → -0.30
        self.assertAlmostEqual(_saturation_delta(150.0), -0.30)

    def test_very_saturated(self):
        # mean_sat ≥ 180 → -0.60
        self.assertAlmostEqual(_saturation_delta(200.0), -0.60)
        self.assertAlmostEqual(_saturation_delta(255.0), -0.60)


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
            self.skipTest("numpy ou opencv non disponible")

    def test_uniform_black_frame(self):
        from dmd_auto_color import _average_metrics
        frame = self.np.zeros((64, 128, 3), dtype=self.np.uint8)  # BGR noir
        mean_lum, std_lum, mean_sat = _average_metrics([frame], self.cv2, self.np)
        self.assertAlmostEqual(mean_lum, 0.0, delta=1.0)
        self.assertAlmostEqual(std_lum, 0.0, delta=1.0)
        self.assertAlmostEqual(mean_sat, 0.0, delta=1.0)

    def test_uniform_white_frame(self):
        from dmd_auto_color import _average_metrics
        frame = self.np.full((64, 128, 3), 255, dtype=self.np.uint8)
        mean_lum, std_lum, mean_sat = _average_metrics([frame], self.cv2, self.np)
        self.assertGreater(mean_lum, 200.0)

    def test_multiple_frames_averages(self):
        from dmd_auto_color import _average_metrics
        dark  = self.np.zeros((64, 128, 3), dtype=self.np.uint8)
        light = self.np.full((64, 128, 3), 200, dtype=self.np.uint8)
        mean_lum, _, _ = _average_metrics([dark, light], self.cv2, self.np)
        # La moyenne doit être entre les deux extrêmes
        self.assertGreater(mean_lum, 0.0)
        self.assertLess(mean_lum, 200.0)


# ─────────────────────────────────────────────────────────────────────────────
# analyze_and_compensate
# ─────────────────────────────────────────────────────────────────────────────

class TestAnalyzeAndCompensate(unittest.TestCase):

    def test_returns_false_without_opencv(self):
        """Sans OpenCV, doit renvoyer (False, {}, message)."""
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
        """Si analyze_and_compensate réussit, les clés attendues doivent être présentes."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("opencv/numpy non disponible")

        # Construire un mock de VideoCapture retournant un frame synthétique
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
                self.assertIn(key, params, f"Clé manquante : {key}")

    def test_output_values_are_within_valid_ranges(self):
        """Les paramètres résultants doivent être dans leurs plages valides."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("opencv/numpy non disponible")

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
        """Le message de retour doit toujours être une chaîne."""
        ok, params, msg = analyze_and_compensate("nonexistent_file.mp4")
        self.assertIsInstance(msg, str)

    def test_baseline_constants_are_reasonable(self):
        """Les constantes de base doivent être dans des plages sensées."""
        self.assertGreater(_BASE_CONTRAST,   1.0)
        self.assertGreater(_BASE_SATURATION, 1.0)
        self.assertGreater(_BASE_GAMMA,      0.5)
        self.assertLess(_BASE_GAMMA,         1.0)
        self.assertLess(abs(_BASE_BRIGHTNESS), 0.1)


if __name__ == "__main__":
    unittest.main()

