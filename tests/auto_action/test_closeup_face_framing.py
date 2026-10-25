"""
Comprehensive unit tests for close-up face framing across wide DMD aspect
ratios (128x32 = 4:1, 128x64 = 2:1, 256x64 = 4:1).

Verifies that:
  1. YOLOv8 `person` close-up / portrait boxes (crown/hair down to neck and upper
     shoulders at the bottom of the frame) anchor on the expressive eye-to-mouth
     band (`[0.23*rh .. 0.61*rh]` for wide/square close-ups, centred at `0.42*rh`,
     and scaled smoothly upward for `1.0 < aspect <= 1.4` bust shots).
  2. Both the eyes (`~0.26..0.35*rh`) AND the mouth (`~0.48..0.58*rh`) sit cleanly
     inside `[cam_top, cam_bottom]` — preventing both the forehead+eyes upward bias
     (`~0.27*rh`) and the nose+chin downward overshoot (`~0.57*rh`).
  3. Letterboxed 2.39:1 cinema close-ups (`1920x1080` with 140px black bars) frame
     eyes + mouth cleanly without leaking top/bottom black bars or cutting off eyes.
  4. `classify_scene()` and `_clip_to_face_roi()` handle widescreen 16:9 close-up
     aspects (`~0.60..1.40`) without misapplying full-body head proportions, and
     self-heal if a scene cut occurs mid-clip.
  5. Non-`face_priority` close-ups (`auto_vertical_bias=True`) and `roi=None`
     intro/fallback frames also anchor on the eye-to-mouth band (`~0.42*h`), while
     preserving full-body, wide-shot, and platformer floor-locked shots.
"""
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from src.engine.analysis.scene_types import SCENE_PROFILES, SceneType, classify_scene
from src.engine.auto_action.camera import _build_camera_rect, closeup_eye_mouth_fractions
from src.engine.auto_action.interfaces import BoundingBox
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.trackers.tracker import TrackingEngine


def _overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _make_engine(
    frame_w: int = 640,
    frame_h: int = 480,
    target_w: int = 128,
    target_h: int = 32,
    face_priority: bool = True,
    scene_type: str | None = SceneType.TALKING_CLOSEUP,
    auto_vertical_bias: bool = False,
    platformer_mode: bool = False,
    dynamic_scene_detection: bool = False,
    locked_crop_size: tuple[float, float] | None = None,
) -> TrackingEngine:
    profile = SCENE_PROFILES[scene_type] if scene_type else None
    cfg = AutoActionConfig(
        target_width=target_w,
        target_height=target_h,
        detector="person",
        smart_auto_crop=True,
        smoothness=0.0,
        zoom_max=1.0,
        min_roi_area_ratio=0.0,
        min_subject_dmd_px=0,
        roi_history_window_s=0.0,
        dmd_visibility_score_enabled=False,
        dmd_readability_score_enabled=False,
        look_ahead_enabled=False,
        auto_vertical_bias=profile.auto_vertical_bias if profile else auto_vertical_bias,
        platformer_mode=profile.platformer_mode if profile else platformer_mode,
        dynamic_scene_detection=dynamic_scene_detection,
    )
    if profile is not None:
        cfg.scene_type = profile.scene_type
        cfg.scene_profile = profile
        cfg.face_clip_mode = profile.face_clip_mode

    with patch("src.plugins.detectors.detector.DetectorFactory.create") as mock_factory, \
         patch("src.plugins.detectors.detector._ensure_yolo_model", return_value=None):
        mock_factory.return_value = MagicMock()
        engine = TrackingEngine(
            fps=25.0,
            frame_w=frame_w,
            frame_h=frame_h,
            effective_frame_top=0,
            effective_frame_h=frame_h,
            effective_frame_left=0,
            effective_frame_w=frame_w,
            face_priority_mode=face_priority,
            cfg=cfg,
            locked_crop_size=locked_crop_size,
        )
    return engine


class TestCloseUpEyesAndMouthFraming(unittest.TestCase):
    """End-to-end vertical crop verification on 128x32, 128x64, and 256x64 DMDs."""

    def test_hd_widescreen_person_closeup_covers_eyes_and_mouth_not_forehead_or_chin(self):
        """
        16:9 HD close-up person box (1920x1080, YOLOv8 person bbox [480, 60, 960, 1020]
        from crown of hair down to neck/upper shoulders at frame bottom):
          - Hair & forehead: [60 .. 284]   (0.00 .. 0.22 * rh)
          - Eyes:            [325 .. 417]  (0.26 .. 0.35 * rh)
          - Nose:            [427 .. 529]  (0.36 .. 0.46 * rh)
          - Mouth:           [550 .. 652]  (0.48 .. 0.58 * rh)
          - Chin & neck:     [733 .. 1080] (0.66 .. 1.00 * rh)
        On 128x32 (4:1), 256x64 (4:1), and 128x64 (2:1), the camera strip must
        capture 100% of both eyes and mouth while avoiding forehead-only or
        nose+chin framing.
        """
        fw, fh_frame = 1920, 1080
        rx, ry, rw, rh = 480, 60, 960, 1020
        forehead_band = (ry, ry + 0.22 * rh)
        eyes_band = (ry + 0.26 * rh, ry + 0.35 * rh)
        mouth_band = (ry + 0.48 * rh, ry + 0.58 * rh)
        expressive_band = (eyes_band[0], mouth_band[1])
        neck_band = (ry + 0.72 * rh, ry + rh)

        for target_w, target_h in [(128, 32), (256, 64), (128, 64)]:
            with self.subTest(dmd=f"{target_w}x{target_h}"):
                engine = _make_engine(
                    frame_w=fw,
                    frame_h=fh_frame,
                    target_w=target_w,
                    target_h=target_h,
                    face_priority=True,
                    scene_type=SceneType.TALKING_CLOSEUP,
                )
                engine.detector.detect = MagicMock(return_value=BoundingBox(rx, ry, rw, rh))
                frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

                _, cy, _, ch = engine.process_frame(
                    frame, engine.cam_full_view, src_idx=0, out_w=target_w, out_h=target_h
                )
                cam_top = cy - ch / 2.0
                cam_bottom = cy + ch / 2.0

                # Anti-nose+chin check: eyes MUST NOT be cut off at the top
                self.assertLessEqual(
                    cam_top, eyes_band[0],
                    f"{target_w}x{target_h}: cam_top={cam_top:.1f} cut into eyes={eyes_band}",
                )
                # Anti-forehead check: mouth MUST NOT be cut off at the bottom
                self.assertGreaterEqual(
                    cam_bottom, mouth_band[1],
                    f"{target_w}x{target_h}: cam_bottom={cam_bottom:.1f} cut off mouth={mouth_band}",
                )

                forehead_cov = _overlap_1d(cam_top, cam_bottom, *forehead_band)
                expressive_cov = _overlap_1d(cam_top, cam_bottom, *expressive_band)
                neck_cov = _overlap_1d(cam_top, cam_bottom, *neck_band)
                expressive_span = expressive_band[1] - expressive_band[0]

                self.assertGreaterEqual(expressive_cov / expressive_span, 0.99)
                min_ratio = 2.5 if ch < rh * 0.55 else 1.4
                self.assertGreater(expressive_cov, forehead_cov * min_ratio)
                if ch < rh * 0.55:
                    # On 4:1 DMD strips (ch=480), neck/collar below chin must stay excluded
                    self.assertEqual(neck_cov, 0.0)

    def test_letterboxed_cinema_closeup_frames_eyes_and_mouth_without_black_bars(self):
        """
        2.39:1 cinema trailer encoded inside 1920x1080 (140px black bars top/bottom,
        active picture y=[140..940], person close-up bbox [520, 145, 880, 795]):
        On 128x32 (crop_h=480), both eyes and mouth must sit cleanly inside the strip
        with zero black-bar leakage.
        """
        fw, fh_frame = 1920, 1080
        rx, ry, rw, rh = 520, 145, 880, 795
        eyes_band = (ry + 0.26 * rh, ry + 0.35 * rh)
        mouth_band = (ry + 0.48 * rh, ry + 0.58 * rh)

        engine = _make_engine(
            frame_w=fw,
            frame_h=fh_frame,
            target_w=128,
            target_h=32,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        engine.detector.detect = MagicMock(return_value=BoundingBox(rx, ry, rw, rh))
        frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        self.assertGreaterEqual(cam_top, 140.0, "Top letterbox bar leaked into DMD crop")
        self.assertLessEqual(cam_bottom, 940.0, "Bottom letterbox bar leaked into DMD crop")
        self.assertLessEqual(cam_top, eyes_band[0])
        self.assertGreaterEqual(cam_bottom, mouth_band[1])

    def test_extreme_4_by_3_closeup_captures_both_eyes_and_mouth_on_4_to_1_dmd(self):
        """
        Tight 4:3 close-up (640x480, person bbox [40, 0, 560, 460]):
        On 128x32 (crop_h = 160 px = 0.348 * rh), the narrow 160 px strip must:
          - Skip the upper forehead ([0 .. 0.22*rh = 101 px]),
          - Include the eyes ([0.26*rh .. 0.35*rh = 120 .. 161 px]),
          - Include the mouth ([0.48*rh .. 0.58*rh = 221 .. 267 px]),
          - Exclude the lower chin & neck ([0.65*rh .. 1.00*rh = 299 .. 460 px]).
        """
        fw, fh_frame = 640, 480
        face_box = BoundingBox(40, 0, 560, 460)
        engine = _make_engine(
            frame_w=fw,
            frame_h=fh_frame,
            target_w=128,
            target_h=32,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        engine.detector.detect = MagicMock(return_value=face_box)
        frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        self.assertGreater(cam_top, 0.22 * 460, "Upper forehead should stay outside 4:1 strip")
        self.assertLessEqual(cam_top, 0.26 * 460, "Eyes top must not be cut off")
        self.assertGreaterEqual(cam_bottom, 0.58 * 460, "Mouth bottom must not be cut off")
        self.assertLess(cam_bottom, 0.65 * 460, "Chin/neck should stay outside 4:1 strip")

    def test_bust_medium_closeup_scales_upward_to_preserve_eyes_when_zoomed(self):
        """
        Head-and-shoulders bust shot (`aspect = 1.25`, rw=720, rh=900 in 1920x1080)
        under TALKING_MEDIUM (`1.25x` zoom -> crop_h = 384 px):
        Because upper chest enters the bottom of `rh`, eyes sit higher (~0.21..0.28*rh)
        and mouth sits around ~0.39..0.46*rh. Aspect-aware scaling keeps both inside.
        """
        fw, fh_frame = 1920, 1080
        rx, ry, rw, rh = 600, 90, 720, 900
        engine = _make_engine(
            frame_w=fw,
            frame_h=fh_frame,
            target_w=128,
            target_h=32,
            face_priority=True,
            scene_type=SceneType.TALKING_MEDIUM,
            locked_crop_size=(1536.0, 384.0),
        )
        engine.detector.detect = MagicMock(return_value=BoundingBox(rx, ry, rw, rh))
        frame = np.zeros((fh_frame, fw, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        self.assertLessEqual(cam_top, ry + 0.21 * rh, "Bust shot eyes must remain inside zoomed strip")
        self.assertGreaterEqual(cam_bottom, ry + 0.46 * rh, "Bust shot mouth must remain inside zoomed strip")

    def test_talking_closeup_intro_full_view_anchors_on_eyes_and_mouth_not_chin(self):
        """When roi is None on intro/missed frames, TALKING_CLOSEUP centers at 0.42*H (not 0.57*H)."""
        engine = _make_engine(
            frame_w=1920,
            frame_h=1080,
            target_w=128,
            target_h=32,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        self.assertAlmostEqual(engine.cam_full_view[1], 1080 * 0.42, delta=1.0)


class TestSceneClassificationAndSelfHealing(unittest.TestCase):
    """Scene classification and _clip_to_face_roi self-healing guards."""

    def test_widescreen_closeup_portrait_classifies_as_talking_closeup(self):
        """
        A 16:9 close-up face often has body_aspect ~0.75..0.82 (< 0.85) with
        fill_ratio ~0.65. It must classify as TALKING_CLOSEUP, not TALKING_MEDIUM
        or ACTION_HORIZONTAL.
        """
        profile, _, _ = classify_scene({
            "tall_ratio": 1.55,
            "fill_ratio": 0.67,
            "body_aspect": 0.78,
            "floor_in_lower": True,
            "floor_var_score": 0.05,
            "x_variance": 0.001,
            "y_variance": 0.001,
        })
        self.assertEqual(profile.scene_type, SceneType.TALKING_CLOSEUP)
        self.assertTrue(profile.face_priority)
        self.assertEqual(profile.face_clip_mode, "closeup")

    def test_standing_tall_character_classifies_as_full_body_tall_not_closeup(self):
        """
        A full-body character filling 85% of frame height with body_aspect = 2.65
        must classify as FULL_BODY_TALL rather than TALKING_CLOSEUP.
        """
        profile, _, _ = classify_scene({
            "tall_ratio": 3.50,
            "fill_ratio": 0.85,
            "body_aspect": 2.65,
            "floor_in_lower": True,
            "floor_var_score": 0.02,
            "x_variance": 0.001,
            "y_variance": 0.001,
        })
        self.assertEqual(profile.scene_type, SceneType.FULL_BODY_TALL)
        self.assertEqual(profile.face_clip_mode, "full_body_head")

    def test_full_body_profile_self_heals_when_given_compact_closeup_roi(self):
        """
        Even if FULL_BODY_TALL is active, a compact close-up ROI (aspect <= 1.4)
        must promote to 'closeup' eye-to-mouth clipping instead of taking the top
        10-20% forehead slice.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            face_priority=True,
            scene_type=SceneType.FULL_BODY_TALL,
        )
        clipped = engine._clip_to_face_roi(BoundingBox(100, 12, 280, 266))
        self.assertIsNotNone(clipped)
        eye_off, band_frac = closeup_eye_mouth_fractions(266 / 280)
        self.assertEqual(clipped.y, 12 + int(266 * eye_off))
        self.assertEqual(clipped.h, int(266 * band_frac))

    def test_closeup_profile_self_heals_when_given_tall_standing_roi(self):
        """
        Conversely, if TALKING_CLOSEUP is active and a scene cut reveals a standing
        character (aspect = 2.6 > 1.65), _clip_to_face_roi must target the head
        rather than the abdomen.
        """
        engine = _make_engine(
            frame_w=500,
            frame_h=500,
            face_priority=True,
            scene_type=SceneType.TALKING_CLOSEUP,
        )
        clipped = engine._clip_to_face_roi(BoundingBox(150, 20, 170, 440))
        self.assertIsNotNone(clipped)
        head_center_rel = (clipped.y - 20) + clipped.h / 2.0
        self.assertLess(head_center_rel, 440 * 0.25)


class TestNonFacePriorityCloseUpAndNonRegression(unittest.TestCase):
    """Protects mid-trailer close-up cuts and preserves wide/platformer framing."""

    def test_non_face_priority_closeup_frames_eyes_and_mouth_without_sinking_to_chin(self):
        """
        When face_priority_mode=False and auto_vertical_bias=True (e.g., ACTION_MOVING
        cutting briefly to a close-up portrait [100, 12, 280, 266] in 496x278),
        FloorEstimationStage + _build_camera_rect must neither clamp onto the forehead
        nor sink to the nose+chin (0.57*rh), capturing both eyes and mouth cleanly.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.ACTION_MOVING,
        )
        rx, ry, rw, rh = 100, 12, 280, 266
        engine.detector.detect = MagicMock(return_value=BoundingBox(rx, ry, rw, rh))
        frame = np.zeros((278, 496, 3), dtype=np.uint8)

        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        self.assertLessEqual(cam_top, ry + 0.26 * rh)
        self.assertGreaterEqual(cam_bottom, ry + 0.58 * rh)

    def test_wide_shot_small_character_still_tracks_ground_feet(self):
        """Wide/medium shot with a small walking character keeps feet anchored near floor."""
        cfg = AutoActionConfig(
            target_width=128,
            target_height=32,
            auto_vertical_bias=True,
            platformer_mode=False,
            smoothness=0.0,
        )
        cfg.scene_profile = SCENE_PROFILES[SceneType.WIDE_SHOT]
        roi = BoundingBox(280, 320, 50, 90)
        _, cy, _, ch = _build_camera_rect(
            640, 480, roi, cfg, floor_y_est=410.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0
        self.assertLessEqual(cam_top, 320.0, "Character head should remain inside wide-shot crop")
        self.assertGreaterEqual(cam_bottom, 410.0, "Character feet should remain inside wide-shot crop")

    def test_platformer_floor_lock_unbroken(self):
        """Platformer mode stays strictly locked to floor_y_est even on wide jumping ROIs."""
        engine = _make_engine(
            frame_w=304,
            frame_h=224,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.PLATFORMER,
        )
        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        engine.detector.detect = MagicMock(return_value=BoundingBox(120, 140, 32, 44))
        cam1 = engine.process_frame(frame, engine.cam_full_view, src_idx=0, out_w=128, out_h=32)

        engine.detector.detect = MagicMock(return_value=BoundingBox(40, 20, 220, 150))
        cam2 = engine.process_frame(frame, cam1, src_idx=1, out_w=128, out_h=32)

        self.assertAlmostEqual(cam1[1], cam2[1], delta=2.0)

    def test_dynamic_scene_cut_to_closeup_syncs_clip_mode_and_frames_eyes_mouth(self):
        """
        When dynamic_scene_detection=True detects a cut from ACTION_MOVING
        (face_clip_mode='none', auto_vertical_bias=True) into a close-up face,
        SceneClassificationStage must sync face_clip_mode and re-clip face_roi
        on the cut evaluation frame to frame eyes + mouth.
        """
        engine = _make_engine(
            frame_w=496,
            frame_h=278,
            target_w=128,
            target_h=32,
            face_priority=False,
            scene_type=SceneType.ACTION_MOVING,
            dynamic_scene_detection=True,
        )
        rx, ry, rw, rh = 100, 12, 280, 266
        engine.roi_history_enabled = True
        engine.roi_history_max_len = 5
        for _ in range(4):
            engine.roi_history.append((1.0, BoundingBox(rx, ry, rw, rh)))
        engine.frames_since_scene_change = 4

        engine.detector.detect = MagicMock(return_value=BoundingBox(rx, ry, rw, rh))
        frame = np.zeros((278, 496, 3), dtype=np.uint8)
        _, cy, _, ch = engine.process_frame(frame, engine.cam_full_view, src_idx=5, out_w=128, out_h=32)

        self.assertEqual(engine.cfg.scene_type, SceneType.TALKING_CLOSEUP)
        self.assertEqual(engine.cfg.face_clip_mode, "closeup")
        self.assertFalse(engine.cfg.auto_vertical_bias)
        self.assertLessEqual(cy - ch / 2.0, ry + 0.26 * rh)
        self.assertGreaterEqual(cy + ch / 2.0, ry + 0.58 * rh)


if __name__ == "__main__":
    unittest.main()
