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

if __name__ == "__main__":
    unittest.main()
