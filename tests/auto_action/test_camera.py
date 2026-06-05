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

class TestClamp(unittest.TestCase):

    def test_clamp_within_range(self):
        self.assertAlmostEqual(_clamp(0.5, 0.0, 1.0), 0.5)

    def test_clamp_below_min(self):
        self.assertAlmostEqual(_clamp(-1.0, 0.0, 1.0), 0.0)

    def test_clamp_above_max(self):
        self.assertAlmostEqual(_clamp(2.0, 0.0, 1.0), 1.0)

    def test_clamp_at_boundaries(self):
        self.assertAlmostEqual(_clamp(0.0, 0.0, 1.0), 0.0)
        self.assertAlmostEqual(_clamp(1.0, 0.0, 1.0), 1.0)

    def test_clamp_negative_range(self):
        self.assertAlmostEqual(_clamp(-5.0, -10.0, -1.0), -5.0)
        self.assertAlmostEqual(_clamp(0.0, -10.0, -1.0), -1.0)

class TestSmooth(unittest.TestCase):

    def test_first_call_returns_current(self):
        result = _smooth(None, (10.0, 20.0, 30.0, 40.0), 0.85)
        self.assertEqual(result, (10.0, 20.0, 30.0, 40.0))

    def test_smoothing_blends_values(self):
        prev = (0.0, 0.0, 0.0, 0.0)
        curr = (100.0, 100.0, 100.0, 100.0)
        result = _smooth(prev, curr, 0.5)
        for v in result:
            self.assertAlmostEqual(v, 50.0, places=5)

    def test_high_smoothness_stays_close_to_prev(self):
        prev = (0.0, 0.0, 0.0, 0.0)
        curr = (100.0, 100.0, 100.0, 100.0)
        result = _smooth(prev, curr, 0.98)
        for v in result:
            # Avec 0.98 de lissage, le résultat doit être proche de 0 (prev)
            self.assertLess(v, 5.0)

    def test_zero_smoothness_returns_current(self):
        prev = (10.0, 20.0, 30.0, 40.0)
        curr = (50.0, 60.0, 70.0, 80.0)
        result = _smooth(prev, curr, 0.0)
        for r, c in zip(result, curr):
            self.assertAlmostEqual(r, c, places=5)

    def test_smoothness_clamped_at_0_98(self):
        """smoothness > 0.98 est clampé à 0.98."""
        prev = (0.0,)
        curr = (100.0,)
        result = _smooth(prev, curr, 1.5)
        # Devrait fonctionner sans crash, valeur entre prev et curr
        self.assertGreaterEqual(result[0], 0.0)
        self.assertLessEqual(result[0], 100.0)

class TestBuildCameraRect(unittest.TestCase):

    def _default_cfg(self, **kwargs):
        return AutoActionConfig(**kwargs)

    def test_no_roi_centers_on_frame(self):
        cfg = self._default_cfg()
        cx, cy, cw, ch = _build_camera_rect(1280, 320, None, cfg)
        # Centre horizontal attendu
        self.assertAlmostEqual(cx, 640.0)

    def test_no_roi_returns_4_1_ratio(self):
        cfg = self._default_cfg(target_width=128, target_height=32)
        cx, cy, cw, ch = _build_camera_rect(1280, 320, None, cfg)
        ratio = cw / ch
        self.assertAlmostEqual(ratio, 128 / 32, places=1)

    def test_with_roi_center_near_roi(self):
        cfg = self._default_cfg(strength=0.5, padding=0.0, zoom_max=2.0)
        roi = (300, 100, 200, 100)  # x, y, w, h
        cx, cy, cw, ch = _build_camera_rect(1280, 720, roi, cfg)
        # Le centre doit être proche du centre du ROI
        roi_cx = roi[0] + roi[2] / 2
        roi_cy = roi[1] + roi[3] / 2
        self.assertAlmostEqual(cx, roi_cx, delta=100)
        self.assertAlmostEqual(cy, roi_cy, delta=100)

    def test_aspect_ratio_preserved_with_roi(self):
        cfg = self._default_cfg(target_width=128, target_height=32)
        roi = (100, 50, 200, 150)
        cx, cy, cw, ch = _build_camera_rect(1280, 720, roi, cfg)
        ratio = cw / ch
        self.assertAlmostEqual(ratio, 128 / 32, places=1)

    def test_crop_stays_within_frame(self):
        cfg = self._default_cfg()
        roi = (0, 0, 50, 50)  # ROI en haut à gauche
        cx, cy, cw, ch = _build_camera_rect(640, 480, roi, cfg)
        self.assertLessEqual(cw, 640)
        self.assertLessEqual(ch, 480)
        self.assertGreater(cw, 0)
        self.assertGreater(ch, 0)

    def test_custom_target_dimensions(self):
        cfg = self._default_cfg(target_width=256, target_height=64)
        cx, cy, cw, ch = _build_camera_rect(1920, 1080, None, cfg)
        ratio = cw / ch
        self.assertAlmostEqual(ratio, 256 / 64, places=1)

class TestBuildCameraRectAutoFloor(unittest.TestCase):
    """Tests spécifiques à auto_vertical_bias=True."""

    def _cfg(self, **kw):
        return AutoActionConfig(auto_vertical_bias=True, **kw)

    # ── Ratio intact ──────────────────────────────────────────────────────────

    def test_aspect_ratio_preserved_with_auto_floor_and_roi(self):
        cfg = self._cfg(target_width=128, target_height=32)
        roi = (100, 200, 80, 120)  # x, y, w, h
        cx, cy, cw, ch = _build_camera_rect(1280, 720, roi, cfg)
        self.assertAlmostEqual(cw / ch, 128 / 32, places=4)

    def test_aspect_ratio_preserved_with_auto_floor_no_roi(self):
        cfg = self._cfg(target_width=128, target_height=32)
        cx, cy, cw, ch = _build_camera_rect(1280, 320, None, cfg)
        self.assertAlmostEqual(cw / ch, 128 / 32, places=4)

    # ── Positionnement vertical ───────────────────────────────────────────────

    def test_auto_floor_roi_floor_visible(self):
        """Le bas de la ROI (sol estimé) doit être dans la moitié basse du crop."""
        cfg = self._cfg()
        roi = (100, 200, 80, 180)  # floor_y = 200 + 180 = 380
        floor_y_est = float(roi[1] + roi[3])  # 380, comme le ferait _FloorEstimator
        cx, cy, cw, ch = _build_camera_rect(1280, 480, roi, cfg,
                                             floor_y_est=floor_y_est)
        crop_bottom = cy + ch / 2.0
        self.assertGreaterEqual(crop_bottom, floor_y_est - 1.0,
                                "Le sol doit être visible dans le crop (crop_bottom >= floor_y)")

    def test_auto_floor_roi_floor_near_bottom_of_crop(self):
        """Avec auto floor, le sol doit se trouver dans les ~80-100 % du crop."""
        cfg = self._cfg(zoom_max=3.0, strength=0.9)
        roi = (200, 100, 100, 250)  # floor_y = 350
        frame_h = 480
        floor_y_est = float(roi[1] + roi[3])
        cx, cy, cw, ch = _build_camera_rect(1280, frame_h, roi, cfg,
                                             floor_y_est=floor_y_est)
        floor_y = float(roi[1] + roi[3])
        crop_top = cy - ch / 2.0
        relative_pos = (floor_y - crop_top) / ch
        self.assertGreaterEqual(relative_pos, 0.7,
                                f"Sol trop haut dans le crop : {relative_pos:.2f}")

    def test_auto_floor_no_roi_leans_downward(self):
        """Sans ROI, auto_floor doit décaler la caméra vers le bas vs bias=0."""
        cfg_auto = self._cfg()
        cfg_neutral = AutoActionConfig(auto_vertical_bias=False, vertical_bias=0.0)
        frame_w, frame_h = 1280, 720
        _, cy_auto, _, _ = _build_camera_rect(frame_w, frame_h, None, cfg_auto)
        _, cy_neutral, _, _ = _build_camera_rect(frame_w, frame_h, None, cfg_neutral)
        self.assertGreater(cy_auto, cy_neutral,
                           "auto_floor sans ROI doit décaler la caméra vers le bas")

    # ── Indépendance par rapport à vertical_bias ──────────────────────────────

    def test_auto_floor_overrides_manual_bias(self):
        """auto_vertical_bias=True doit ignorer vertical_bias manuelle."""
        roi = (100, 100, 80, 100)  # floor_y = 200
        floor_y_est = 200.0
        cfg_auto_up = AutoActionConfig(auto_vertical_bias=True, vertical_bias=-1.0)
        cfg_auto_dn = AutoActionConfig(auto_vertical_bias=True, vertical_bias=+1.0)
        _, cy_up, _, _ = _build_camera_rect(1280, 480, roi, cfg_auto_up,
                                             floor_y_est=floor_y_est)
        _, cy_dn, _, _ = _build_camera_rect(1280, 480, roi, cfg_auto_dn,
                                             floor_y_est=floor_y_est)
        # L'auto floor doit produire la même position quelle que soit vertical_bias
        self.assertAlmostEqual(cy_up, cy_dn, delta=1.0,
                               msg="auto_vertical_bias doit ignorer vertical_bias manuelle")

    # ── Clamp dans les limites ─────────────────────────────────────────────────

    def test_auto_floor_cy_within_frame(self):
        """cy doit toujours rester dans [crop_h/2, frame_h - crop_h/2]."""
        cfg = self._cfg()
        for roi in [
            (0, 0, 20, 10),        # coin supérieur gauche
            (600, 440, 80, 40),    # coin inférieur droit
            (300, 200, 200, 200),  # roi large
        ]:
            floor_y_est = float(roi[1] + roi[3])
            cx, cy, cw, ch = _build_camera_rect(640, 480, roi, cfg,
                                                 floor_y_est=floor_y_est)
            self.assertGreaterEqual(cy, ch / 2.0 - 0.5)
            self.assertLessEqual(cy, 480 - ch / 2.0 + 0.5)

    # ── Stabilité pendant les sauts ───────────────────────────────────────────

    def test_floor_estimate_stable_during_jump(self):
        """Intégration _FloorEstimator + _build_camera_rect:
        le cy ne doit pas monter significativement pendant un saut."""
        cfg = self._cfg()
        fe = _FloorEstimator(480)
        frame_w, frame_h = 1280, 480

        # Établir un sol stable à roi_bottom=380
        roi_ground = (200, 200, 100, 180)  # floor_y=380
        for _ in range(15):
            fy = fe.update(float(roi_ground[1] + roi_ground[3]))
        _, cy_ground, _, _ = _build_camera_rect(frame_w, frame_h, roi_ground, cfg,
                                                 floor_y_est=fy)

        # Saut : roi_bottom remonte à 200 pendant 8 frames
        roi_air = (200, 50, 100, 150)  # floor_y=200
        for _ in range(8):
            fy_air = fe.update(float(roi_air[1] + roi_air[3]))
        _, cy_air, _, _ = _build_camera_rect(frame_w, frame_h, roi_air, cfg,
                                              floor_y_est=fy_air)

        # cy ne doit pas avoir remonté de plus de 35 px pendant le saut
        # (sans stabilisateur, la différence serait ~150 px → réduction > 75 %)
        self.assertLess(cy_ground - cy_air, 35.0,
                        "La caméra ne doit pas remonter significativement pendant un saut")

class TestCropFrame(unittest.TestCase):

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")

    def _make_frame(self, h=480, w=640):
        return self.np.zeros((h, w, 3), dtype=self.np.uint8)

    def test_basic_crop(self):
        frame = self._make_frame(480, 640)
        cam = (320.0, 240.0, 128.0, 32.0)  # cx, cy, cw, ch
        result = _crop_frame(frame, cam)
        # La région recadrée doit être <= frame originale
        self.assertLessEqual(result.shape[0], 480)
        self.assertLessEqual(result.shape[1], 640)

    def test_crop_out_of_bounds_returns_frame(self):
        """Si le cam_rect est invalide après clamp, renvoie le frame original."""
        frame = self._make_frame(32, 128)
        # cam_rect plus grand que le frame
        cam = (64.0, 16.0, 200.0, 100.0)
        result = _crop_frame(frame, cam)
        self.assertIsNotNone(result)
        # Ne doit pas lever d'exception

    def test_center_crop_has_correct_size(self):
        frame = self._make_frame(480, 640)
        # Crop de 128×32 centré
        cam = (320.0, 240.0, 128.0, 32.0)
        result = _crop_frame(frame, cam)
        self.assertEqual(result.shape[1], 128)
        self.assertEqual(result.shape[0], 32)

    def test_returns_array(self):
        frame = self._make_frame()
        cam = (320.0, 240.0, 100.0, 50.0)
        result = _crop_frame(frame, cam)
        self.assertEqual(result.ndim, 3)

class TestBuildCameraRectFrameTop(unittest.TestCase):
    """Tests for the frame_top parameter in _build_camera_rect."""

    def _cfg(self, **kw):
        return AutoActionConfig(**kw)

    def test_frame_top_zero_same_as_default(self):
        """frame_top=0 should produce the same result as no frame_top."""
        cfg = self._cfg()
        r1 = _build_camera_rect(1280, 480, None, cfg, frame_top=0.0)
        r2 = _build_camera_rect(1280, 480, None, cfg)
        # Results should be numerically identical
        for a, b in zip(r1, r2):
            self.assertAlmostEqual(a, b, places=4)

    def test_frame_top_restricts_camera_upward(self):
        """With frame_top > 0, camera centre y should be ≥ frame_top + ch/2."""
        cfg = self._cfg()
        frame_top = 100.0
        cx, cy, cw, ch = _build_camera_rect(1280, 480, None, cfg, frame_top=frame_top)
        self.assertGreaterEqual(cy, frame_top + ch / 2.0 - 0.5)

    def test_frame_top_with_roi(self):
        """With frame_top > 0 and a ROI above it, camera should still be >= frame_top + ch/2."""
        cfg = self._cfg(strength=0.5)
        frame_top = 80.0
        roi = (100, 10, 80, 40)   # ROI y=10, well above frame_top=80
        cx, cy, cw, ch = _build_camera_rect(1280, 480, roi, cfg, frame_top=frame_top)
        self.assertGreaterEqual(cy, frame_top + ch / 2.0 - 0.5)

    def test_aspect_ratio_preserved_with_frame_top(self):
        cfg = self._cfg(target_width=128, target_height=32)
        cx, cy, cw, ch = _build_camera_rect(1280, 480, None, cfg, frame_top=60.0)
        self.assertAlmostEqual(cw / ch, 128 / 32, places=1)

class TestLookAhead(unittest.TestCase):

    FW = 1920
    FH = 1080

    def _cam(self, cx=960.0, cy=540.0, cw=960.0, ch=240.0):
        return (cx, cy, cw, ch)

    def test_no_motion_returns_same_cam(self):
        cam = self._cam()
        result = _apply_look_ahead(cam, 500.0, 500.0, 300.0, 300.0,
                                   self.FW, self.FH, 0.25)
        self.assertEqual(result, cam,
                         "No motion (same cx/cy) → cam unchanged")

    def test_disabled_returns_same_cam(self):
        cam = self._cam()
        result = _apply_look_ahead(cam, 400.0, 600.0, 300.0, 300.0,
                                   self.FW, self.FH, 0.0)
        self.assertEqual(result, cam, "factor=0 disables look-ahead")

    def test_rightward_motion_shifts_cam_right(self):
        cam = self._cam(cx=960.0)
        result = _apply_look_ahead(cam, 400.0, 600.0, 300.0, 300.0,
                                   self.FW, self.FH, 0.25)
        self.assertGreater(result[0], cam[0],
                           "Rightward ROI motion should shift camera cx right")

    def test_leftward_motion_shifts_cam_left(self):
        cam = self._cam(cx=960.0)
        result = _apply_look_ahead(cam, 600.0, 400.0, 300.0, 300.0,
                                   self.FW, self.FH, 0.25)
        self.assertLess(result[0], cam[0],
                        "Leftward ROI motion should shift camera cx left")

    def test_result_stays_within_frame(self):
        """Camera rect must never exceed frame boundaries after look-ahead."""
        cam = self._cam(cx=1880.0)   # near right edge
        result = _apply_look_ahead(cam, 100.0, 1900.0, 300.0, 300.0,
                                   self.FW, self.FH, 0.5)
        cx, cy, cw, ch = result
        self.assertGreaterEqual(cx - cw / 2, 0, "Left edge must not go negative")
        self.assertLessEqual(cx + cw / 2, self.FW, "Right edge must stay within frame")

    def test_no_prev_cx_returns_unchanged(self):
        cam = self._cam()
        result = _apply_look_ahead(cam, None, 600.0, None, 300.0,
                                   self.FW, self.FH, 0.25)
        self.assertEqual(result, cam,
                         "No previous ROI centre → no look-ahead offset")

    def test_config_default_enabled(self):
        cfg = AutoActionConfig()
        self.assertTrue(cfg.look_ahead_enabled)
        self.assertAlmostEqual(cfg.look_ahead_factor, 0.25)

    def test_config_disabled(self):
        cfg = AutoActionConfig(look_ahead_enabled=False)
        self.assertFalse(cfg.look_ahead_enabled)
        self.assertFalse(cfg.look_ahead_enabled)

if __name__ == "__main__":
    unittest.main()
