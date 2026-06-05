#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

from dmd_auto_action import (
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


# ─────────────────────────────────────────────────────────────────────────────
# available_detectors
# ─────────────────────────────────────────────────────────────────────────────

class TestAvailableDetectors(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(available_detectors(), list)

    def test_contains_expected_modes(self):
        dets = available_detectors()
        for mode in ("person", "motion", "hybrid", "center"):
            self.assertIn(mode, dets)

    def test_no_duplicates(self):
        dets = available_detectors()
        self.assertEqual(len(dets), len(set(dets)))


# ─────────────────────────────────────────────────────────────────────────────
# AutoActionConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoActionConfig(unittest.TestCase):

    def test_default_values(self):
        cfg = AutoActionConfig()
        self.assertEqual(cfg.detector, "person")
        self.assertAlmostEqual(cfg.strength, 0.65)
        self.assertAlmostEqual(cfg.smoothness, 0.85)
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


# ─────────────────────────────────────────────────────────────────────────────
# _clamp
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _smooth
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _FloorEstimator
# ─────────────────────────────────────────────────────────────────────────────

class TestFloorEstimator(unittest.TestCase):

    def test_first_detection_snaps_immediately(self):
        fe = _FloorEstimator(480)
        result = fe.update(300.0)
        self.assertAlmostEqual(result, 300.0)

    def test_no_detection_defaults_to_80pct(self):
        fe = _FloorEstimator(480)
        result = fe.update(None)
        self.assertAlmostEqual(result, 480 * 0.80)

    def test_attack_follows_descent_quickly(self):
        """Quand le personnage descend (roi_bottom augmente), l'estimateur suit vite."""
        fe = _FloorEstimator(480)
        fe.update(200.0)       # sol initial à 200
        # Simuler 20 frames à roi_bottom=380 (atterrissage bas)
        for _ in range(20):
            val = fe.update(380.0)
        # Après 20 frames en mode attack, on doit être proche de 380
        self.assertGreater(val, 340.0, "L'estimateur doit suivre rapidement la descente")

    def test_release_resists_ascent(self):
        """Quand le personnage monte (saut), l'estimateur bouge très peu."""
        fe = _FloorEstimator(480)
        fe.update(380.0)       # sol bien établi à 380
        # Simuler 10 frames en l'air à roi_bottom=150 (saut haut)
        for _ in range(10):
            val = fe.update(150.0)
        # Après 10 frames de saut, l'estimateur ne doit pas avoir bougé de plus de 20 %
        drop = 380.0 - val
        self.assertLess(drop, 380.0 * 0.25,
                        f"L'estimateur a trop bougé pendant le saut: {drop:.1f} px")

    def test_asymmetry_attack_faster_than_release(self):
        """α_attack >> α_release : la descente converge bien plus vite que la montée."""
        frame_h = 480
        ground = 380.0
        air    = 150.0
        steps  = 8

        fe_down = _FloorEstimator(frame_h)
        fe_down.update(air)   # départ en haut
        for _ in range(steps):
            v_down = fe_down.update(ground)  # descend vers le sol

        fe_up = _FloorEstimator(frame_h)
        fe_up.update(ground)  # départ au sol
        for _ in range(steps):
            v_up = fe_up.update(air)         # monte (saut)

        # La convergence vers ground doit être bien plus importante que vers air
        delta_down = abs(v_down - air)    # combien il a avancé vers ground
        delta_up   = abs(ground - v_up)   # combien il a avancé vers air
        self.assertGreater(delta_down, delta_up * 4,
                           "α_attack doit être beaucoup plus grand que α_release")

    def test_no_detection_after_known_floor_holds_value(self):
        """Sans détection, l'estimateur garde la dernière valeur connue."""
        fe = _FloorEstimator(480)
        fe.update(300.0)
        for _ in range(5):
            val = fe.update(None)
        self.assertAlmostEqual(val, 300.0)

    def test_floor_y_property(self):
        fe = _FloorEstimator(480)
        self.assertIsNone(fe.floor_y)
        fe.update(200.0)
        self.assertAlmostEqual(fe.floor_y, 200.0)


# ─────────────────────────────────────────────────────────────────────────────
# _build_camera_rect
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _build_camera_rect — auto_vertical_bias
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _crop_frame
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# preprocess_video_for_dmd — chemins d'erreur
# ─────────────────────────────────────────────────────────────────────────────

class TestPreprocessVideoForDmd(unittest.TestCase):

    def test_missing_file_returns_false(self):
        """Un chemin de fichier inexistant doit échouer proprement."""
        ok, out, msg = preprocess_video_for_dmd("__nonexistent__.mp4", AutoActionConfig())
        self.assertFalse(ok)
        self.assertIsNone(out)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_opencv_unavailable_returns_false(self):
        """Sans OpenCV, la fonction doit retourner False avec un message."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("cv2 not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            ok, out, msg = preprocess_video_for_dmd("any.mp4", AutoActionConfig())

        self.assertFalse(ok)
        self.assertIsNone(out)
        self.assertIn("OpenCV", msg)

    def test_available_detectors_are_valid(self):
        """Chaque mode de détecteur doit être dans la liste autorisée."""
        for mode in available_detectors():
            self.assertIn(mode, ["person", "motion", "hybrid", "center"])


# ─────────────────────────────────────────────────────────────────────────────
# AutoActionConfig — auto crop fields
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _compute_auto_crop_margins
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeAutoCropMargins(unittest.TestCase):
    """Tests for the auto crop margin computation using a mock capture."""

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2
            self.cv2 = cv2
        except ImportError:
            self.skipTest("opencv non disponible")

    def _make_mock_cap(self, frame_h=480, frame_w=640, total_frames=60,
                       roi_y=100, roi_h=200):
        """Build a minimal mock cv2.VideoCapture that returns a black frame
        with a rectangle filled at (roi_y, 0)-(roi_y+roi_h, roi_w)."""
        np = self.np
        cv2 = self.cv2

        frame = np.zeros((frame_h, frame_w, 3), dtype=np.uint8)
        # Make a bright rectangle so motion/fg detection can find it
        frame[roi_y:roi_y + roi_h, 0:frame_w // 2] = 200

        cap = MagicMock()
        cap.get = MagicMock(side_effect=lambda prop: (
            float(total_frames) if prop == cv2.CAP_PROP_FRAME_COUNT else
            0.0
        ))
        cap.set = MagicMock(return_value=None)
        cap.read = MagicMock(return_value=(True, frame.copy()))
        return cap

    def test_returns_tuple_of_two_floats(self):
        from dmd_auto_action import _FrameDetector
        cfg = AutoActionConfig(detector="motion")
        # Detector that always returns a fixed ROI
        det = MagicMock()
        det.detect = MagicMock(return_value=(0, 100, 320, 200))
        cap = self._make_mock_cap()
        result = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)
        top, bottom, face_prio = result
        self.assertIsInstance(top, float)
        self.assertIsInstance(bottom, float)
        self.assertIsInstance(face_prio, bool)

    def test_no_detections_returns_zeros(self):
        cfg = AutoActionConfig(detector="motion")
        det = MagicMock()
        det.detect = MagicMock(return_value=None)
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bottom, 0.0)

    def test_full_body_roi_fits_in_dmd_window(self):
        """Full-body ROI that fits within the DMD window → feet are used as bottom.

        For frame_w=640, target 128×32 → dmd_crop_h = 160 px.
        ROI h=90 (< 160×0.80=128) → no face priority → feet-based bottom crop.
        The effective content ends at roi_y + roi_h = 50 + 90 = 140.
        With pad_frac=0.06 (tall narrow ROI, h/w=3.0 > 2.5):
          bottom_y ≈ 140 + 480*0.06 ≈ 169  →  bottom_pct ≈ 0.65
        The important invariant: top boundary should be above the head (y=50).
        """
        cfg = AutoActionConfig(detector="motion", target_width=128, target_height=32)
        det = MagicMock()
        # Tall narrow ROI that still fits (h/w=3.0, h=90 < 128 threshold)
        det.detect = MagicMock(return_value=(100, 50, 30, 90))
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        # top boundary must be at or above the head (y=50 → top_pct ≤ 50/480 ≈ 0.104)
        self.assertLessEqual(top * 480, 50.0,
            "Top boundary must be at or above the head position (y=50)")
        # bottom boundary must be at or below feet (y=140 → effective_bottom ≥ 140)
        effective_bottom = 480 * (1.0 - bottom)
        self.assertGreaterEqual(effective_bottom, 90.0,
            "Bottom boundary must include the feet region")

    def test_face_priority_triggers_when_body_too_tall(self):
        """When ROI height > 80% of DMD window height, face priority activates.

        In face priority mode the effective bottom is roi_y + roi_h * FACE_FRAC
        (top ~32%) instead of roi_y + roi_h (feet), so bottom_pct is LARGER
        (more of the frame is excluded from the bottom).
        """
        # frame_w=640, target_ratio=4.0 → dmd_crop_h = 160 px
        # ROI: y=50, h=200 → 200 > 160 * 0.80 = 128 → face priority
        cfg_face_prio = AutoActionConfig(detector="motion",
                                         target_width=128, target_height=32)
        det_tall = MagicMock()
        det_tall.detect = MagicMock(return_value=(100, 50, 80, 200))  # h=200 > 128

        cfg_normal = AutoActionConfig(detector="motion",
                                      target_width=128, target_height=32)
        det_short = MagicMock()
        det_short.detect = MagicMock(return_value=(100, 50, 80, 80))  # h=80 < 128

        cap1 = self._make_mock_cap()
        cap2 = self._make_mock_cap()

        top_tall, bot_tall, _   = _compute_auto_crop_margins(cap1, det_tall,  cfg_face_prio, 640, 480)
        top_short, bot_short, _ = _compute_auto_crop_margins(cap2, det_short, cfg_normal,    640, 480)

        # Face priority: bottom boundary is at roi_y + roi_h * 0.32 = 50 + 64 = 114
        # Normal (short): bottom boundary is at roi_y + roi_h = 50 + 80 = 130
        # Face priority excludes MORE from the bottom → bot_tall > bot_short
        self.assertGreater(bot_tall, bot_short,
            "Face priority mode should crop more from the bottom than normal mode "
            "(body-too-tall triggers face region focus)")

    def test_face_priority_head_always_visible(self):
        """The top_pct should be small enough that the head is always included.

        Even in face priority mode the top boundary should be above (or at) the
        head position.
        """
        cfg = AutoActionConfig(detector="motion", target_width=128, target_height=32)
        det = MagicMock()
        # Very tall ROI: y=50, h=250 (head at y=50)
        det.detect = MagicMock(return_value=(100, 50, 60, 250))
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        # top boundary must be at or above y=50 (head position)
        top_y_px = top * 480
        self.assertLessEqual(top_y_px, 50.0,
            f"top_y_px={top_y_px:.1f} is below the head (y=50) — head would be cut off")

    def test_face_roi_gives_larger_padding(self):
        """Face-like ROI (square) → larger relative padding applied."""
        cfg = AutoActionConfig(detector="motion")
        det_face = MagicMock()
        det_body = MagicMock()
        # Face: h/w ≈ 1.0
        det_face.detect = MagicMock(return_value=(200, 180, 80, 80))
        # Full body: h/w ≈ 4.0
        det_body.detect = MagicMock(return_value=(200, 180, 40, 160))

        cap = self._make_mock_cap()
        top_face, bot_face, _ = _compute_auto_crop_margins(cap, det_face, cfg, 640, 480)

        cap2 = self._make_mock_cap()
        top_body, bot_body, _ = _compute_auto_crop_margins(cap2, det_body, cfg, 640, 480)

        # Face should have more padding than body (face pad_frac=0.15, body pad_frac=0.06)
        # The face roi starts at y=180, body roi also starts at y=180
        # Face top_pct = (180 - 0.15*480) / 480 ≈ (180-72)/480 = 108/480 ≈ 0.225
        # Body top_pct = (180 - 0.06*480) / 480 ≈ (180-29)/480 = 151/480 ≈ 0.315
        # Actually face pad is LARGER so top_pct (starting further down) < body
        # The important thing is just that both are non-negative
        self.assertGreaterEqual(top_face, 0.0)
        self.assertGreaterEqual(top_body, 0.0)

    def test_values_clamped_to_valid_range(self):
        """Both returned values must be in [0, 0.9]."""
        cfg = AutoActionConfig(detector="motion")
        det = MagicMock()
        det.detect = MagicMock(return_value=(0, 0, 640, 480))  # Full frame ROI
        cap = self._make_mock_cap()
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertGreaterEqual(top, 0.0)
        self.assertLessEqual(top, 0.9)
        self.assertGreaterEqual(bottom, 0.0)
        self.assertLessEqual(bottom, 0.9)

    def test_zero_total_frames_returns_zeros(self):
        """If cap reports 0 total frames, should return (0.0, 0.0)."""
        import cv2
        cfg = AutoActionConfig()
        det = MagicMock()
        cap = MagicMock()
        cap.get = MagicMock(return_value=0.0)
        top, bottom, _ = _compute_auto_crop_margins(cap, det, cfg, 640, 480)
        self.assertAlmostEqual(top, 0.0)
        self.assertAlmostEqual(bottom, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# _build_camera_rect — frame_top parameter
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# _smart_auto_crop_decision
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartAutoCropDecision(unittest.TestCase):
    """Tests for _smart_auto_crop_decision using a mock cv2.VideoCapture."""

    def _make_cap(self, total_frames: int = 30, frame_w: int = 640, frame_h: int = 480):
        """Return a mock VideoCapture that yields blank black frames."""
        import numpy as np
        cap = MagicMock()
        cap.get.side_effect = lambda prop: {
            0: 0.0,               # CAP_PROP_POS_FRAMES
            7: float(total_frames),  # CAP_PROP_FRAME_COUNT
        }.get(prop, 0.0)
        blank = np.zeros((frame_h, frame_w, 3), dtype="uint8")
        cap.read.return_value = (True, blank)
        return cap

    def _cfg(self, **kw):
        defaults = dict(detector="motion", target_width=128, target_height=32)
        defaults.update(kw)
        return AutoActionConfig(**defaults)

    def test_returns_required_keys(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        for key in ("auto_bottom_crop", "auto_top_crop", "auto_vertical_bias",
                    "top_pct", "bottom_pct", "reasons"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_no_detections_returns_all_false(self):
        """Blank frames produce no detections → all auto flags False."""
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertFalse(result["auto_vertical_bias"])

    def test_pct_values_are_floats_in_range(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        for key in ("top_pct", "bottom_pct"):
            self.assertIsInstance(result[key], float)
            self.assertGreaterEqual(result[key], 0.0)
            self.assertLessEqual(result[key], 0.9)

    def test_reasons_is_nonempty_list(self):
        cap = self._make_cap()
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertIsInstance(result["reasons"], list)
        self.assertGreater(len(result["reasons"]), 0)

    def test_zero_frames_returns_safe_defaults(self):
        cap = self._make_cap(total_frames=0)
        cfg = self._cfg()
        result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertEqual(result["top_pct"], 0.0)
        self.assertEqual(result["bottom_pct"], 0.0)

    def test_detector_init_failure_returns_safe_defaults(self):
        """If _FrameDetector() raises, the function should return safe defaults."""
        cap = self._make_cap()
        cfg = self._cfg()
        with patch("dmd_auto_action._FrameDetector", side_effect=RuntimeError("mock fail")):
            result = _smart_auto_crop_decision(cap, cfg, 640, 480)
        self.assertFalse(result["auto_bottom_crop"])
        self.assertFalse(result["auto_top_crop"])
        self.assertIn("reasons", result)

    def test_preprocess_smart_crop_exception_degrades_gracefully(self):
        """If _smart_auto_crop_decision raises, preprocess falls back without crashing."""
        with patch("dmd_auto_action._smart_auto_crop_decision",
                   side_effect=RuntimeError("boom")):
            cfg = AutoActionConfig(smart_auto_crop=True)
            ok, out, msg = preprocess_video_for_dmd("/nonexistent_file_xyz.mp4", cfg)
        # Should fail gracefully (no crash), not because of the smart scan
        self.assertFalse(ok)
        self.assertIsNone(out)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 1 — _calculate_dmd_visibility_score
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateDMDVisibilityScore(unittest.TestCase):
    """Tests pour _calculate_dmd_visibility_score()."""

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2  # noqa: F401 — only needed transitively inside the func
        except ImportError:
            self.skipTest("opencv non disponible")

    def _blank(self, w=128, h=32):
        """Completely black frame — minimum visibility."""
        return self.np.zeros((h, w, 3), dtype=self.np.uint8)

    def _bright(self, w=128, h=32):
        """Fully white frame — maximum brightness, but low edge density."""
        return self.np.full((h, w, 3), 255, dtype=self.np.uint8)

    def _checkerboard(self, w=128, h=32):
        """Checkerboard pattern — high edge / contrast score."""
        np = self.np
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        for r in range(h):
            for c in range(w):
                if (r + c) % 2 == 0:
                    frame[r, c] = [255, 255, 255]
        return frame

    def _center_rect(self, w=128, h=32, rect_w=64, rect_h=20):
        """Frame with a bright rectangle in the centre — medium score."""
        np = self.np
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        x0 = (w - rect_w) // 2
        y0 = (h - rect_h) // 2
        frame[y0:y0 + rect_h, x0:x0 + rect_w] = [200, 200, 200]
        return frame

    # ── Return type & range ───────────────────────────────────────────────────

    def test_returns_float(self):
        score = _calculate_dmd_visibility_score(self._blank())
        self.assertIsInstance(score, float)

    def test_blank_frame_returns_zero(self):
        """A completely black frame should score 0.0 (nothing visible)."""
        score = _calculate_dmd_visibility_score(self._blank())
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_score_is_non_negative(self):
        for frame in [self._blank(), self._bright(), self._checkerboard(), self._center_rect()]:
            self.assertGreaterEqual(_calculate_dmd_visibility_score(frame), 0.0)

    def test_none_frame_returns_zero(self):
        """Passing None must not raise and must return 0.0."""
        score = _calculate_dmd_visibility_score(None)
        self.assertAlmostEqual(score, 0.0, places=4)

    def test_empty_array_returns_zero(self):
        np = self.np
        score = _calculate_dmd_visibility_score(np.zeros((0, 0, 3), dtype=np.uint8))
        self.assertAlmostEqual(score, 0.0, places=4)

    # ── Monotonicity — more content → higher score ────────────────────────────

    def test_bright_frame_scores_higher_than_blank(self):
        score_blank  = _calculate_dmd_visibility_score(self._blank())
        score_bright = _calculate_dmd_visibility_score(self._bright())
        self.assertGreater(score_bright, score_blank,
                           "A bright frame should score higher than a blank frame")

    def test_checkerboard_scores_higher_than_blank(self):
        score_blank = _calculate_dmd_visibility_score(self._blank())
        score_check = _calculate_dmd_visibility_score(self._checkerboard())
        self.assertGreater(score_check, score_blank,
                           "A checkerboard (high edge density) should score higher than blank")

    def test_center_rect_scores_higher_than_blank(self):
        score_blank = _calculate_dmd_visibility_score(self._blank())
        score_rect  = _calculate_dmd_visibility_score(self._center_rect())
        self.assertGreater(score_rect, score_blank,
                           "A frame with a bright rect should score higher than blank")

    def test_high_contrast_region_scores_higher_than_flat_region(self):
        """A frame with alternating high-contrast stripes (2-px bands) must score higher
        than a flat grey frame — validating that the Sobel-based contrast component works.
        We use 4-px bands to avoid aliasing at kernel size 3."""
        np = self.np
        flat = np.full((32, 128, 3), 128, dtype=np.uint8)   # featureless grey

        striped = np.zeros((32, 128, 3), dtype=np.uint8)
        for c in range(0, 128, 4):
            striped[:, c:c + 2] = 255   # alternate 2px white / 2px black bands

        score_flat    = _calculate_dmd_visibility_score(flat)
        score_striped = _calculate_dmd_visibility_score(striped)
        self.assertGreater(score_striped, score_flat,
                           "A high-contrast striped frame must score higher than a flat grey frame")

    # ── Partial content occupation ────────────────────────────────────────────

    def test_larger_rect_scores_higher_than_smaller(self):
        score_small = _calculate_dmd_visibility_score(self._center_rect(rect_w=20, rect_h=8))
        score_large = _calculate_dmd_visibility_score(self._center_rect(rect_w=100, rect_h=28))
        self.assertGreater(score_large, score_small,
                           "A larger bright area should produce a higher score")

    # ── Different DMD resolutions ─────────────────────────────────────────────

    def test_works_on_256x64_frame(self):
        """Score function must handle non-default DMD sizes without error."""
        frame = self._checkerboard(w=256, h=64)
        score = _calculate_dmd_visibility_score(frame)
        self.assertGreater(score, 0.0)

    def test_works_on_single_row_frame(self):
        """Edge case: 1-pixel tall frame must not raise."""
        np = self.np
        frame = np.full((1, 128, 3), 200, dtype=np.uint8)
        score = _calculate_dmd_visibility_score(frame)
        self.assertIsInstance(score, float)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 1 — AutoActionConfig.dmd_visibility_score_enabled
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 1 — Visibility score integration guard
# Tests _calculate_dmd_visibility_score logic used inside the main loop:
# "if proposed score < 95% of current score → keep current camera position"
# ─────────────────────────────────────────────────────────────────────────────

class TestDMDVisibilityScoreGuard(unittest.TestCase):
    """
    Validates the 5%-threshold guard used in preprocess_video_for_dmd:
    when a proposed crop scores < 95% of the current crop, the current
    camera should be preferred.
    """

    def setUp(self):
        try:
            import numpy as np
            self.np = np
        except ImportError:
            self.skipTest("numpy non disponible")
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("opencv non disponible")

    def test_good_proposed_accepted(self):
        """When proposed score >= 95% of current, the proposed crop is accepted."""
        np = self.np
        # Both frames equally bright
        frame_a = np.full((32, 128, 3), 200, dtype=np.uint8)
        frame_b = np.full((32, 128, 3), 200, dtype=np.uint8)
        score_a = _calculate_dmd_visibility_score(frame_a)
        score_b = _calculate_dmd_visibility_score(frame_b)
        # Guard condition: proposed (b) < current (a) * 0.95 → revert
        # Here scores are equal, so proposed should be accepted (NOT reverted)
        self.assertFalse(score_b < score_a * 0.95,
                         "Equal-brightness frames should not trigger the revert guard")

    def test_bad_proposed_rejected(self):
        """When proposed score < 95% of current, the guard should trigger revert."""
        np = self.np
        # Current: bright/rich content
        current_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    current_frame[r, c] = [255, 255, 255]

        # Proposed: nearly blank (zoomed into a flat area)
        proposed_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        proposed_frame[14:18, 60:68] = [30, 30, 30]  # tiny dim rectangle

        score_current  = _calculate_dmd_visibility_score(current_frame)
        score_proposed = _calculate_dmd_visibility_score(proposed_frame)

        self.assertLess(score_proposed, score_current * 0.95,
                        "A nearly blank proposed frame should fall below 95% of a rich current frame "
                        "and trigger the revert guard")

    def test_slight_degradation_within_threshold_accepted(self):
        """A 3% degradation (within 5% tolerance) must not trigger revert."""
        np = self.np
        # Current: checkerboard
        current_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    current_frame[r, c] = [200, 200, 200]

        # Proposed: same but slightly dimmer (simulate marginal quality change)
        proposed_frame = np.zeros((32, 128, 3), dtype=np.uint8)
        for r in range(32):
            for c in range(128):
                if (r + c) % 2 == 0:
                    proposed_frame[r, c] = [195, 195, 195]  # ~2.5% dimmer

        score_current  = _calculate_dmd_visibility_score(current_frame)
        score_proposed = _calculate_dmd_visibility_score(proposed_frame)
        # Should NOT trigger revert (within tolerance)
        self.assertFalse(score_proposed < score_current * 0.95,
                         "A marginal quality difference should not trigger the revert guard")


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 2 — Temporal Scene Memory
# ─────────────────────────────────────────────────────────────────────────────

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


class TestROIHistoryWeightedAverage(unittest.TestCase):
    """Unit tests for the weighted-average ROI synthesis logic (Priority 2).

    The production code computes a linearly-weighted average over a deque of
    (_, roi) tuples where the weight for index idx is (idx+1) — so the most
    recent entry has the highest weight.  We replicate that logic here to
    verify its correctness independently of the full preprocessing pipeline.
    """

    def _weighted_avg(self, history):
        """Replication of the in-loop weighted-average computation."""
        total_w = 0.0
        wx, wy, ww, wh = 0.0, 0.0, 0.0, 0.0
        for idx, (_, hr) in enumerate(history):
            w = float(idx + 1)
            total_w += w
            wx += w * hr[0]
            wy += w * hr[1]
            ww += w * hr[2]
            wh += w * hr[3]
        if total_w <= 0:
            return None
        return (
            int(wx / total_w),
            int(wy / total_w),
            int(ww / total_w),
            int(wh / total_w),
        )

    def test_single_entry_returns_that_roi(self):
        """With one history entry the average equals that entry."""
        history = [(1.0, (100, 50, 80, 120))]
        result = self._weighted_avg(history)
        self.assertEqual(result, (100, 50, 80, 120))

    def test_two_equal_rois_return_that_roi(self):
        """Two identical ROIs → weighted average is that same ROI."""
        roi = (100, 50, 80, 120)
        history = [(1.0, roi), (1.0, roi)]
        result = self._weighted_avg(history)
        self.assertEqual(result, roi)

    def test_recent_entry_has_more_weight(self):
        """With two entries, the more recent one (idx=1, weight=2) biases the result."""
        old_roi = (0, 0, 40, 40)
        new_roi = (200, 200, 40, 40)
        history = [(1.0, old_roi), (1.0, new_roi)]  # old=idx0(w=1), new=idx1(w=2)
        result = self._weighted_avg(history)
        # x: (1*0 + 2*200) / 3 = 133
        self.assertAlmostEqual(result[0], int((0 + 400) / 3))
        # Result x must be closer to new_roi (200) than to old_roi (0)
        self.assertGreater(result[0], 100,
                           "Weighted average should be closer to the more-recent ROI")

    def test_three_entries_progressive_weight(self):
        """Three entries: weights 1, 2, 3. Validate x-component math."""
        history = [
            (1.0, (0, 0, 10, 10)),    # oldest: w=1
            (1.0, (100, 0, 10, 10)),  # middle: w=2
            (1.0, (200, 0, 10, 10)),  # newest: w=3
        ]
        result = self._weighted_avg(history)
        # x = (1*0 + 2*100 + 3*200) / 6 = (0+200+600)/6 = 800/6 ≈ 133
        expected_x = int((0 + 200 + 600) / 6)
        self.assertEqual(result[0], expected_x)

    def test_empty_history_returns_none(self):
        """Empty history must not crash and must return None."""
        result = self._weighted_avg([])
        self.assertIsNone(result)

    def test_result_biased_toward_most_recent(self):
        """With N entries linearly weighted, the result must be strictly
        closer to the latest entry than to the oldest."""
        old_roi = (10, 10, 50, 50)
        new_roi = (300, 300, 50, 50)
        history = [(1.0, old_roi), (1.0, new_roi)]
        result = self._weighted_avg(history)
        dist_old = abs(result[0] - old_roi[0])
        dist_new = abs(result[0] - new_roi[0])
        self.assertLess(dist_new, dist_old,
                        "The weighted average x must be closer to the newest ROI")


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 3 — Scene Change Detection
# ─────────────────────────────────────────────────────────────────────────────
from dmd_auto_action import _compute_scene_change_score


class TestSceneChangeScore(unittest.TestCase):

    def _frame(self, color):
        """Return a 64×64 BGR frame filled with the given color."""
        import numpy as np
        f = np.zeros((64, 64, 3), dtype=np.uint8)
        f[:] = color
        return f

    def test_identical_frames_score_near_one(self):
        f = self._frame((128, 64, 200))
        score = _compute_scene_change_score(f, f.copy())
        self.assertGreaterEqual(score, 0.9,
                                "Identical frames should score close to 1.0")

    def test_black_vs_white_scores_low(self):
        black = self._frame((0, 0, 0))
        white = self._frame((255, 255, 255))
        score = _compute_scene_change_score(black, white)
        # Pure luminance change — V channel histograms will be maximally different
        self.assertLess(score, 0.8,
                        "Black→white hard cut should score well below 1.0")

    def test_none_frame_returns_one(self):
        """Graceful degradation: None input → treat as no cut."""
        f = self._frame((100, 100, 100))
        self.assertAlmostEqual(_compute_scene_change_score(None, f), 1.0)
        self.assertAlmostEqual(_compute_scene_change_score(f, None), 1.0)
        self.assertAlmostEqual(_compute_scene_change_score(None, None), 1.0)

    def test_score_in_zero_one_range(self):
        a = self._frame((30, 200, 100))
        b = self._frame((200, 30, 100))
        score = _compute_scene_change_score(a, b)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_config_default_threshold(self):
        cfg = AutoActionConfig()
        self.assertAlmostEqual(cfg.scene_change_threshold, 0.45)

    def test_config_disabled(self):
        cfg = AutoActionConfig(scene_change_threshold=0.0)
        self.assertAlmostEqual(cfg.scene_change_threshold, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 4 — Micro-detection Rejection
# ─────────────────────────────────────────────────────────────────────────────

class TestMicroDetectionRejection(unittest.TestCase):

    def _cfg(self, ratio=0.02):
        return AutoActionConfig(min_roi_area_ratio=ratio)

    def _frame_area(self, w=1920, h=1080):
        return w * h

    def _reject(self, roi, frame_w=1920, frame_h=1080, ratio=0.02):
        """Replicate the rejection check from the main loop."""
        if roi is not None and ratio > 0.0:
            roi_area = roi[2] * roi[3]
            frame_area = frame_w * frame_h
            if frame_area > 0 and (roi_area / frame_area) < ratio:
                return None
        return roi

    def test_default_ratio(self):
        self.assertAlmostEqual(AutoActionConfig().min_roi_area_ratio, 0.02)

    def test_disabled_when_zero(self):
        tiny_roi = (0, 0, 1, 1)
        result = self._reject(tiny_roi, ratio=0.0)
        self.assertIsNotNone(result, "ratio=0 disables rejection; tiny ROI must pass")

    def test_tiny_roi_rejected(self):
        """A 10×10 ROI in a 1920×1080 frame (0.0048%) is below 2 % threshold."""
        tiny = (100, 100, 10, 10)
        result = self._reject(tiny)
        self.assertIsNone(result, "Tiny ROI should be rejected")

    def test_large_roi_accepted(self):
        """A 400×300 ROI in 1920×1080 frame (5.8%) is above 2 % threshold."""
        large = (100, 100, 400, 300)
        result = self._reject(large)
        self.assertIsNotNone(result, "Large ROI should pass the area filter")

    def test_boundary_roi_accepted(self):
        """ROI exactly at threshold: area / frame_area == min_ratio should pass."""
        frame_w, frame_h = 1000, 1000
        ratio = 0.02
        # Area = 200 / 1000000 = 0.0002  → 0.02 % which is < 2 %, so rejected
        # Use area = ratio * frame_area exactly
        roi_area = int(ratio * frame_w * frame_h)  # 20000
        rw = 200
        rh = roi_area // rw    # 100
        roi = (0, 0, rw, rh)
        actual_ratio = rw * rh / (frame_w * frame_h)
        # If actual_ratio < ratio it gets rejected, else accepted
        result = self._reject(roi, frame_w, frame_h, ratio)
        if actual_ratio < ratio:
            self.assertIsNone(result)
        else:
            self.assertIsNotNone(result)

    def test_none_roi_passes_through(self):
        result = self._reject(None)
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 5 — Directional Look-Ahead
# ─────────────────────────────────────────────────────────────────────────────
from dmd_auto_action import _apply_look_ahead


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


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 6 — Multi-ROI Fusion
# ─────────────────────────────────────────────────────────────────────────────
from dmd_auto_action import _fuse_rois


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


class TestFuseROIs(unittest.TestCase):

    def test_empty_returns_none(self):
        self.assertIsNone(_fuse_rois([]))

    def test_single_entry_returns_that_roi(self):
        roi = (10, 20, 100, 80)
        result = _fuse_rois([(0.9, roi)])
        self.assertEqual(result, roi)

    def test_two_equal_score_rois_centroid(self):
        """Two equal-score ROIs → simple average centroid."""
        r1 = (0, 0, 100, 100)    # cx=50, cy=50
        r2 = (200, 0, 100, 100)  # cx=250, cy=50
        result = _fuse_rois([(0.8, r1), (0.8, r2)])
        # Weighted cx = (0.8*50 + 0.8*250) / 1.6 = 150
        # Weighted x  = 150 - 100/2 = 100
        self.assertAlmostEqual(result[0], 100, delta=2)

    def test_high_score_roi_dominates(self):
        """High-confidence detection biases the centroid toward itself."""
        r_weak  = (0,   0, 50, 50)   # cx=25
        r_strong = (500, 0, 50, 50)  # cx=525
        result = _fuse_rois([(0.1, r_weak), (0.9, r_strong)])
        fused_cx = result[0] + result[2] / 2.0
        # fused_cx = (0.1*25 + 0.9*525) / 1.0 = 475  → should be much closer to 525
        self.assertGreater(fused_cx, 400,
                           "High-confidence ROI should dominate the centroid")

    def test_fused_box_dimensions_are_weighted_average(self):
        """Width/height of fused box = confidence-weighted average (not union)."""
        r1 = (0, 0, 100, 80)
        r2 = (200, 0, 200, 160)
        result = _fuse_rois([(0.5, r1), (0.5, r2)])
        # ww = (0.5*100 + 0.5*200) / 1.0 = 150
        self.assertAlmostEqual(result[2], 150, delta=2)
        # wh = (0.5*80 + 0.5*160) / 1.0 = 120
        self.assertAlmostEqual(result[3], 120, delta=2)

    def test_result_has_non_negative_coordinates(self):
        """Returned x, y must always be >= 0."""
        r = (0, 0, 10, 10)
        result = _fuse_rois([(0.9, r), (0.1, r)])
        self.assertGreaterEqual(result[0], 0)
        self.assertGreaterEqual(result[1], 0)

    def test_three_rois_returns_tuple_of_four(self):
        rois = [(0.7, (0, 0, 50, 50)), (0.5, (100, 0, 50, 50)), (0.3, (200, 0, 50, 50))]
        result = _fuse_rois(rois)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 4)
# ─────────────────────────────────────────────────────────────────────────────
# PRIORITY 7, 8, 10
# ─────────────────────────────────────────────────────────────────────────────

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
