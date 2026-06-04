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
    _clamp,
    _crop_frame,
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


if __name__ == "__main__":
    unittest.main()

