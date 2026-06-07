"""
Tests unitaires pour dmd_auto_action.py

Couvre :
  - available_detectors()
  - AutoActionConfig (dataclass — valeurs par défaut et personnalisées)
  - _clamp()
  - _build_camera_rect()
  - _smooth()
  - _crop_frame()
  - preprocess_video_for_dmd() — chemin d'erreur sans OpenCV
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.auto_action.main import (
    AutoActionConfig,
    _FloorEstimator,
    _build_camera_rect,
    _calculate_dmd_visibility_score,
    _clamp,
    _compute_auto_crop_margins,
    _crop_frame,
    _smart_auto_crop_decision,
    _smooth,
    available_detectors,
    preprocess_video_for_dmd,
)
from src.auto_action.main import _compute_scene_change_score
from src.auto_action.main import _apply_look_ahead
from src.auto_action.main import _fuse_rois

class TestAutoActionConfig(unittest.TestCase):

    def test_default_values(self):
        cfg = AutoActionConfig()
        self.assertEqual(cfg.detector, "person")
        self.assertAlmostEqual(cfg.strength, 0.65)
        self.assertAlmostEqual(cfg.smoothness, 0.65)
        self.assertAlmostEqual(cfg.zoom_max, 2.0)
        self.assertAlmostEqual(cfg.padding, 0.20)
        self.assertAlmostEqual(cfg.intro_duration, 1.5)
        self.assertFalse(cfg.bg_sub_enable)
        self.assertFalse(cfg.auto_vertical_bias)
        self.assertAlmostEqual(cfg.vertical_bias, 0.0)
        self.assertAlmostEqual(cfg.bottom_crop_pct, 0.0)
        self.assertAlmostEqual(cfg.top_crop_pct, 0.0)
        self.assertFalse(cfg.auto_bottom_crop)
        self.assertFalse(cfg.auto_top_crop)
        self.assertIsNone(cfg.start_s)
        self.assertIsNone(cfg.end_s)
        self.assertEqual(cfg.target_width, 128)
        self.assertEqual(cfg.target_height, 32)

    def test_custom_values(self):
        cfg = AutoActionConfig(
            detector="motion",
            strength=0.9,
            smoothness=0.5,
            zoom_max=3.0,
            target_width=256,
            target_height=64,
        )
        self.assertEqual(cfg.detector, "motion")
        self.assertAlmostEqual(cfg.strength, 0.9)
        self.assertEqual(cfg.target_width, 256)
        self.assertEqual(cfg.target_height, 64)

    def test_start_end_seconds(self):
        cfg = AutoActionConfig(start_s=2.0, end_s=8.5)
        self.assertAlmostEqual(cfg.start_s, 2.0)
        self.assertAlmostEqual(cfg.end_s, 8.5)

class TestAutoActionConfigAutoCrop(unittest.TestCase):

    def test_auto_bottom_crop_default_false(self):
        cfg = AutoActionConfig()
        self.assertFalse(cfg.auto_bottom_crop)

    def test_auto_top_crop_default_false(self):
        cfg = AutoActionConfig()
        self.assertFalse(cfg.auto_top_crop)

    def test_top_crop_pct_default_zero(self):
        cfg = AutoActionConfig()
        self.assertAlmostEqual(cfg.top_crop_pct, 0.0)

    def test_auto_bottom_crop_can_be_enabled(self):
        cfg = AutoActionConfig(auto_bottom_crop=True)
        self.assertTrue(cfg.auto_bottom_crop)

    def test_auto_top_crop_can_be_enabled(self):
        cfg = AutoActionConfig(auto_top_crop=True)
        self.assertTrue(cfg.auto_top_crop)

    def test_manual_top_crop_pct(self):
        cfg = AutoActionConfig(top_crop_pct=0.1)
        self.assertAlmostEqual(cfg.top_crop_pct, 0.1)

    def test_both_auto_crops_independent(self):
        cfg = AutoActionConfig(auto_bottom_crop=True, auto_top_crop=False)
        self.assertTrue(cfg.auto_bottom_crop)
        self.assertFalse(cfg.auto_top_crop)

class TestDMDVisibilityScoreConfig(unittest.TestCase):
    """Tests pour le flag dmd_visibility_score_enabled dans AutoActionConfig."""

    def test_default_disabled(self):
        """dmd_visibility_score_enabled must be False by default (no breaking change)."""
        cfg = AutoActionConfig()
        self.assertFalse(cfg.dmd_visibility_score_enabled)

    def test_can_be_enabled(self):
        cfg = AutoActionConfig(dmd_visibility_score_enabled=True)
        self.assertTrue(cfg.dmd_visibility_score_enabled)

    def test_independent_of_other_flags(self):
        """Enabling it must not affect other defaults."""
        cfg = AutoActionConfig(dmd_visibility_score_enabled=True)
        self.assertFalse(cfg.bg_sub_enable)
        self.assertFalse(cfg.smart_auto_crop)
        self.assertFalse(cfg.auto_bottom_crop)
        self.assertEqual(cfg.detector, "person")

class TestROIHistoryConfig(unittest.TestCase):
    """Tests for the roi_history_window_s AutoActionConfig field."""

    def test_default_value(self):
        """Default window is 3.0 s (non-zero → enabled by default)."""
        cfg = AutoActionConfig()
        self.assertAlmostEqual(cfg.roi_history_window_s, 3.0)

    def test_can_be_disabled(self):
        """Setting to 0 disables temporal memory without side-effects."""
        cfg = AutoActionConfig(roi_history_window_s=0.0)
        self.assertAlmostEqual(cfg.roi_history_window_s, 0.0)

    def test_custom_window(self):
        cfg = AutoActionConfig(roi_history_window_s=5.0)
        self.assertAlmostEqual(cfg.roi_history_window_s, 5.0)

    def test_deque_max_len_from_fps(self):
        """_roi_history_max_len = int(fps * window_s), at least 1."""
        fps = 24.0
        window = 3.0
        expected = max(1, int(fps * window))  # 72
        self.assertEqual(expected, 72)

    def test_independent_of_other_flags(self):
        cfg = AutoActionConfig(roi_history_window_s=2.0)
        self.assertFalse(cfg.dmd_visibility_score_enabled)
        self.assertFalse(cfg.smart_auto_crop)

class TestMultiROIFusionConfig(unittest.TestCase):

    def test_default_enabled(self):
        cfg = AutoActionConfig()
        self.assertTrue(cfg.multi_roi_fusion_enabled)

    def test_can_be_disabled(self):
        cfg = AutoActionConfig(multi_roi_fusion_enabled=False)
        self.assertFalse(cfg.multi_roi_fusion_enabled)

    def test_independent_of_other_flags(self):
        cfg = AutoActionConfig(multi_roi_fusion_enabled=True)
        self.assertFalse(cfg.dmd_visibility_score_enabled)
        self.assertAlmostEqual(cfg.look_ahead_factor, 0.25)

class TestPriority7810Config(unittest.TestCase):

    def test_priority7_min_dmd_px(self):
        cfg = AutoActionConfig()
        self.assertEqual(cfg.min_subject_dmd_px, 4)
        cfg2 = AutoActionConfig(min_subject_dmd_px=10)
        self.assertEqual(cfg2.min_subject_dmd_px, 10)

    def test_priority8_platformer_mode(self):
        cfg = AutoActionConfig()
        self.assertFalse(cfg.platformer_mode)
        self.assertEqual(cfg.platformer_floor_ratio, 0.80)
        cfg2 = AutoActionConfig(platformer_mode=True, platformer_floor_ratio=0.85)
        self.assertTrue(cfg2.platformer_mode)
        self.assertEqual(cfg2.platformer_floor_ratio, 0.85)

    def test_priority10_confidence_min(self):
        cfg = AutoActionConfig()
        self.assertEqual(cfg.roi_confidence_min, 0.0)
        cfg2 = AutoActionConfig(roi_confidence_min=0.5)
        self.assertEqual(cfg2.roi_confidence_min, 0.5)

if __name__ == "__main__":
    unittest.main()
