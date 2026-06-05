#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for dmd_led_sim.apply_led_grid.

Covers:
  - Correct output size and RGB mode
  - Gap pixels (cell borders) are black
  - Cell centres preserve their original colour
  - Invariance with gap=0 (no effect)
  - Black input image stays black
  - Theoretical gap coverage fraction verified
  - Fallback without NumPy
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

from dmd_led_sim import apply_led_grid, LED_SIM_SCALE, LED_SIM_GAP


@unittest.skipUnless(_PIL_AVAILABLE and _NUMPY_AVAILABLE,
                     "PIL and NumPy required for the LED sim filter")
class TestApplyLedGrid(unittest.TestCase):

    def _white_img(self, w, h):
        return Image.new("RGB", (w, h), (255, 255, 255))

    def _color_img(self, w, h, color=(200, 100, 50)):
        return Image.new("RGB", (w, h), color)

    # ── Dimensions & mode ──────────────────────────────────────────────────────

    def test_output_size_unchanged(self):
        scale = 4
        img = self._white_img(128 * scale, 32 * scale)
        out = apply_led_grid(img, scale)
        self.assertEqual(out.size, img.size)

    def test_output_is_rgb(self):
        img = self._white_img(32, 8)
        out = apply_led_grid(img, 4)
        self.assertEqual(out.mode, "RGB")

    # ── Gap pixels = black ────────────────────────────────────────────────────

    def test_first_column_of_each_cell_is_black(self):
        scale, gap = 4, 1
        img = self._white_img(16, 4)
        out = apply_led_grid(img, scale, gap)
        arr = np.array(out)
        for col in range(0, 16, scale):
            self.assertTrue(np.all(arr[:, col] == 0),
                            f"Column {col} should be black")

    def test_last_column_of_each_cell_is_black(self):
        scale, gap = 4, 1
        img = self._white_img(16, 4)
        out = apply_led_grid(img, scale, gap)
        arr = np.array(out)
        for col in range(scale - gap, 16, scale):
            self.assertTrue(np.all(arr[:, col] == 0),
                            f"Column {col} should be black")

    def test_first_row_of_each_cell_is_black(self):
        scale, gap = 4, 1
        img = self._white_img(4, 16)
        out = apply_led_grid(img, scale, gap)
        arr = np.array(out)
        for row in range(0, 16, scale):
            self.assertTrue(np.all(arr[row, :] == 0),
                            f"Row {row} should be black")

    def test_last_row_of_each_cell_is_black(self):
        scale, gap = 4, 1
        img = self._white_img(4, 16)
        out = apply_led_grid(img, scale, gap)
        arr = np.array(out)
        for row in range(scale - gap, 16, scale):
            self.assertTrue(np.all(arr[row, :] == 0),
                            f"Row {row} should be black")

    # ── Cell centres = colour preserved ──────────────────────────────────────

    def test_cell_centers_preserve_color(self):
        scale = 4
        color = (180, 90, 30)
        img = self._color_img(scale * 4, scale, color)
        out = apply_led_grid(img, scale, gap=1)
        arr = np.array(out)
        pix = tuple(arr[scale // 2, scale // 2])
        self.assertEqual(pix, color, f"Center should be {color}, got {pix}")

    # ── gap=0 : no effect ─────────────────────────────────────────────────────

    def test_gap_zero_no_change(self):
        img = self._white_img(16, 4)
        out = apply_led_grid(img, 4, gap=0)
        self.assertEqual(list(img.getdata()), list(out.getdata()))

    # ── Black input stays black ───────────────────────────────────────────────

    def test_black_input_stays_black(self):
        img = Image.new("RGB", (16, 4), (0, 0, 0))
        out = apply_led_grid(img, 4)
        self.assertTrue(np.all(np.array(out) == 0))

    # ── Theoretical gap coverage fraction ────────────────────────────────────

    def test_gap_coverage_fraction(self):
        """scale=4, gap=1 → lit area = (2/4)^2 = 0.25, gap fraction = 0.75."""
        scale, gap = 4, 1
        w, h = scale * 10, scale * 10
        out = apply_led_grid(self._white_img(w, h), scale, gap)
        arr = np.array(out)
        frac_black = int(np.sum(np.all(arr == 0, axis=2))) / (w * h)
        expected = 1 - ((scale - 2 * gap) / scale) ** 2
        self.assertAlmostEqual(frac_black, expected, delta=0.02,
                               msg=f"Expected black fraction ≈ {expected:.2f}, got {frac_black:.2f}")

    def test_larger_scale_fewer_gap_pixels(self):
        """scale=8 has proportionally fewer black pixels than scale=4."""
        img = self._white_img(40, 40)
        out_4 = apply_led_grid(img, 4, gap=1)
        out_8 = apply_led_grid(img, 8, gap=1)
        black_4 = int(np.sum(np.all(np.array(out_4) == 0, axis=2)))
        black_8 = int(np.sum(np.all(np.array(out_8) == 0, axis=2)))
        self.assertGreater(black_4, black_8,
                           "scale=4 must have more black pixels than scale=8")


@unittest.skipUnless(_PIL_AVAILABLE, "PIL required")
class TestApplyLedGridFallback(unittest.TestCase):
    """Verifies graceful fallback when NumPy is unavailable."""

    def test_no_crash_when_numpy_missing(self):
        img = Image.new("RGB", (16, 4), (100, 150, 200))
        import unittest.mock, builtins
        real_import = builtins.__import__

        def _no_numpy(name, *args, **kwargs):
            if name == "numpy":
                raise ImportError("numpy mocked unavailable")
            return real_import(name, *args, **kwargs)

        with unittest.mock.patch("builtins.__import__", side_effect=_no_numpy):
            result = apply_led_grid(img, sim_scale=4)

        self.assertIsNotNone(result)
        self.assertEqual(result.size, img.size)


if __name__ == "__main__":
    unittest.main()
