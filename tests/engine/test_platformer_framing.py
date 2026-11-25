"""
Unit tests for 2D platformer vertical framing, stance-aware floor estimation,
character headroom/footroom guards, and anti-thick-ground-scroll detection.
"""

from unittest.mock import MagicMock
import numpy as np
import pytest

from src.engine.analysis.analysis import _FloorEstimator
from src.engine.auto_action.camera import _build_camera_rect
from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import _FrameDetector


def _platformer_cfg(**overrides) -> AutoActionConfig:
    params = dict(
        target_width=128,
        target_height=32,
        platformer_mode=True,
        auto_vertical_bias=True,
        smoothness=0.0,
        look_ahead_enabled=False,
        look_ahead_factor=0.0,
    )
    params.update(overrides)
    return AutoActionConfig(**params)


class TestPlatformerFloorRatioAndThickGroundFraming:
    """Verify 0.90 floor ratio and framing on thick ground slabs."""

    def test_default_platformer_floor_ratio_is_090(self):
        cfg = AutoActionConfig()
        assert cfg.platformer_floor_ratio == pytest.approx(0.90)

    def test_thick_ground_shows_few_dmd_pixels_below_feet_without_clipping(self):
        """
        Scenario (a): On a 304x224 frame where thick ground spans y=145..224 and
        the player stands with feet at y=145 (sprite y=109..145, h=36):
        - Camera shows ~3 DMD pixels of ground below y=145 on a 128x32 DMD.
        - Character head has ample headroom (zero top clipping).
        - Camera is NOT dragged down to y=224.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32)
        roi = (120, 109, 24, 36)  # feet at y_bottom = 145

        cx, cy, cw, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        # Ground visible below y=145 in DMD pixels (~3.2 px on 32px DMD)
        ground_src_px = cam_bottom - 145.0
        ground_dmd_px = ground_src_px * (32.0 / ch)
        assert 2.0 <= ground_dmd_px <= 4.5

        # Full character visibility with comfortable headroom
        assert cam_top < roi[1] - 4.0
        assert cam_bottom >= roi[1] + roi[3]
        assert cam_bottom < 165.0  # nowhere near frame bottom y=224

    def test_thick_ground_64px_dmd_shows_proportional_ground_strip(self):
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=64)
        roi = (120, 95, 28, 50)  # feet at y_bottom = 145

        _, cy, _, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0
        ground_dmd_px = (cam_bottom - 145.0) * (64.0 / ch)

        assert 5.0 <= ground_dmd_px <= 7.5
        assert cam_top < roi[1]

    def test_lagging_low_floor_estimate_never_clips_character_head_on_thick_ground(self):
        """
        Even if floor_y_est temporarily lags deep inside a thick ground slab (e.g. 210),
        the headroom guard must keep the character's head inside the DMD frame.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        roi = (120, 109, 24, 36)  # feet at 145, head at 109

        _, cy, _, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=210.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        assert cam_top <= roi[1] - (ch * 0.06 - 1e-4)


class TestCharacterHeadroomAndFootroomGuards:
    """Verify strict character visibility envelope in _build_camera_rect."""

    def test_high_jump_never_clips_head_above_cam_rect(self):
        """
        Scenario (b): Character jumps high near the top of the screen while
        floor_y_est remains anchored on the ground below.
        """
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        jumping_roi = (130, 18, 24, 36)  # head at y=18, feet at y=54

        _, cy, _, ch = _build_camera_rect(
            fw, fh, jumping_roi, cfg, floor_y_est=180.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        cam_bottom = cy + ch / 2.0

        assert cam_top <= jumping_roi[1]
        assert cam_bottom >= jumping_roi[1] + jumping_roi[3]

    def test_dropping_below_floor_estimate_never_clips_feet(self):
        """When dropping from a high platform before floor_y_est catches up, feet stay visible."""
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        falling_roi = (130, 152, 24, 36)  # feet at y=188 while floor_y_est is still 105

        _, cy, _, ch = _build_camera_rect(
            fw, fh, falling_roi, cfg, floor_y_est=105.0, face_priority_mode=False
        )
        cam_bottom = cy + ch / 2.0
        assert cam_bottom >= falling_roi[1] + falling_roi[3]

    def test_sprite_taller_than_crop_h_anchors_on_upper_body_without_head_clip(self):
        """Tall character/boss sprite exceeding crop_h=76 keeps head visible."""
        fw, fh = 304, 224
        cfg = _platformer_cfg()
        tall_character = (120, 80, 44, 92)  # h=92 > crop_h=76

        _, cy, _, ch = _build_camera_rect(
            fw, fh, tall_character, cfg, floor_y_est=172.0, face_priority_mode=False
        )
        cam_top = cy - ch / 2.0
        assert cam_top <= tall_character[1]


class TestBidirectionalFloorEstimator:
    """Verify stance-aware bidirectional platform tracking and spike rejection."""

    def test_bidirectional_platform_climb_and_drop(self):
        """
        Scenario (c): Character starts at y_bottom=185 on a 224p frame, climbs onto
        an upper platform at y_bottom=105 (stays >= 8 frames), then drops back to 185.
        """
        fe = _FloorEstimator(frame_h=224)
        for _ in range(5):
            fe.update(185.0)
        assert fe.floor_y == pytest.approx(185.0, abs=0.5)

        # Climb onto upper platform at y_bottom = 105 and hold for 8 fresh samples
        # (first 5 samples confirm deliberate stance vs jump apex; samples 6..8 re-anchor smoothly)
        for _ in range(8):
            fe.update(105.0)
        assert fe.floor_y < 138.0

        # Settling a few more frames converges tightly onto ~105
        for _ in range(8):
            fe.update(105.0)
        assert fe.floor_y == pytest.approx(105.0, abs=3.0)

        # Drop back down to lower platform y_bottom = 185
        for _ in range(12):
            fe.update(185.0)
        assert fe.floor_y == pytest.approx(185.0, abs=3.5)

    def test_isolated_bottom_border_spike_is_rejected_until_corroborated(self):
        fe = _FloorEstimator(frame_h=224)
        fe.update(145.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Single-frame ground-scroll noise touching extreme bottom (222 >= 0.96 * 224)
        fe.update(222.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Next frame returns to normal sprite feet -> spike streak resets cleanly
        fe.update(145.0)
        assert fe.floor_y == pytest.approx(145.0)

        # Two consecutive corroborated bottom detections are accepted smoothly
        fe.update(220.0)
        assert fe.floor_y == pytest.approx(145.0)
        fe.update(220.0)
        assert fe.floor_y > 160.0

    def test_transient_jump_arc_keeps_floor_calm(self):
        fe = _FloorEstimator(frame_h=224)
        for _ in range(6):
            fe.update(185.0)

        # Parabolic 6-frame jump arc on the same platform (high spread -> jump, not stance)
        for y_jump in (162.0, 136.0, 118.0, 118.0, 136.0, 162.0):
            fe.update(y_jump)

        assert fe.floor_y > 173.0  # stays calm near 185 instead of snapping to jump apex

    def test_first_real_detection_after_none_snaps_immediately(self):
        """TrackingEngine calls update(None) at init; first real sprite detection must snap."""
        fe = _FloorEstimator(frame_h=224)
        default_y = fe.update(None)
        assert default_y == pytest.approx(224 * 0.80)

        snapped_y = fe.update(145.0)
        assert snapped_y == pytest.approx(145.0)


class TestAntiThickGroundScrollDetector:
    """Verify motion and YOLO detectors ignore thick scrolling ground slabs."""

    def test_detect_motion_selects_player_sprite_over_wide_scrolling_ground_slab(self):
        """
        Scenario (d): Wide scrolling ground-slab motion noise at y=160..224, w=180
        vs compact player sprite motion at y=120..156, w=24 -> selects player sprite.
        """
        det = _FrameDetector()
        fw, fh = 304, 224

        # Warm up background model on static dark background
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        frame_a = bg.copy()
        # Initial positions before horizontal scroll step
        frame_a[160:224, 50:230] = (90, 90, 90)
        frame_a[120:156, 96:120] = (220, 220, 220)
        det.detect_motion(frame_a, platformer_mode=True)

        frame_b = bg.copy()
        # Frame B: wide ground band shifts producing 180px-wide motion at y=160..224,
        # while compact player sprite moves at y=120..156, w=24.
        frame_b[160:224, 60:240] = (255, 255, 255)
        frame_b[120:156, 124:148] = (255, 255, 255)

        roi = det.detect_motion(frame_b, platformer_mode=True)
        assert roi is not None
        rx, ry, rw, rh = roi
        # Must lock onto the compact player sprite near x=124..148, y=120..156 (NOT ground y=160..224)
        assert rw < 60
        assert 110 <= ry <= 130
        assert 145 <= (ry + rh) <= 166

    def test_detect_motion_tracks_upper_platform_sprite_with_expected_floor(self):
        det = _FrameDetector()
        fw, fh = 304, 224
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True, expected_floor_y=185.0)

        frame_b = bg.copy()
        # Wide scrolling ground slab at bottom + compact sprite on upper platform y=69..105
        frame_b[170:224, 40:220] = (255, 255, 255)
        frame_b[69:105, 140:164] = (255, 255, 255)

        roi = det.detect_motion(frame_b, platformer_mode=True, expected_floor_y=185.0)
        assert roi is not None
        _, ry, rw, rh = roi
        assert rw < 60
        assert 60 <= ry <= 80
        assert 95 <= (ry + rh) <= 115

    def test_detect_yolo_platformer_prefers_playfield_sprite_over_bottom_border_noise(self):
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Build synthetic YOLOv8 output tensor of shape (1, 5, 2):
        # Box 0: bottom-border tile pareidolia (cy=615, bh=48 -> bottom=639/640 = 0.998, conf=0.60)
        # Box 1: player sprite on thick ground (cy=363, bh=102 -> bottom=414/640 = 0.647, conf=0.65)
        pred = np.zeros((1, 5, 2), dtype=np.float32)
        pred[0, :, 0] = [320.0, 615.0, 80.0, 48.0, 0.60]
        pred[0, :, 1] = [260.0, 363.0, 50.0, 102.0, 0.65]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi = det._detect_yolo(frame, platformer_mode=True, expected_floor_y=None)
        assert roi is not None
        _, ry, _, rh = roi
        # Box 1 maps to y_bottom ≈ 145 on 224p (NOT Box 0 at y_bottom ≈ 224)
        assert 138 <= (ry + rh) <= 152

    def test_detect_motion_separates_sprite_directly_touching_scrolling_ground_slab(self):
        """Even with zero vertical gap (feet at y=160 touching ground y=160..224), extracts the sprite."""
        det = _FrameDetector()
        fw, fh = 304, 224
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        frame_b = bg.copy()
        frame_b[160:224, 40:230] = (240, 240, 240)
        frame_b[124:160, 130:154] = (240, 240, 240)

        roi = det.detect_motion(frame_b, platformer_mode=True)
        assert roi is not None
        _, ry, rw, rh = roi
        assert rw < 60
        assert 115 <= ry <= 132
        assert 150 <= (ry + rh) <= 165


class TestCameraStabilityAndAntiIndecision:
    """Regression suite for v8.0.5 camera stability (no jump bobbing, no subsample stance, no ping-pong)."""

    def test_normal_jump_within_floor_window_produces_zero_vertical_shift(self):
        """Standing vs normal hop inside the floor-anchored crop window must keep exact same cy."""
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32)
        standing_roi = (120, 109, 24, 36)  # feet at 145
        hop_roi = (128, 86, 24, 36)        # hop 23px upward, head=86 well inside window top ~76.6

        _, cy_stand, _, _ = _build_camera_rect(
            fw, fh, standing_roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        _, cy_hop, _, _ = _build_camera_rect(
            fw, fh, hop_roi, cfg, floor_y_est=145.0, face_priority_mode=False
        )
        assert cy_hop == pytest.approx(cy_stand, abs=1e-6)

    def test_subsampled_frozen_midair_roi_never_triggers_false_upper_platform_stance(self):
        """
        With subsample_frames=5, a single mid-air YOLO detection is cached for 4 subsampled
        frames. FloorEstimationStage must NOT feed cached duplicates into _FloorEstimator.
        """
        from src.plugins.trackers.tracker import TrackingEngine
        from src.engine.auto_action.interfaces import BoundingBox

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=5,
            auto_fast_tracking=False,
            smoothness=0.8,
            scene_change_threshold=0.0,
        )
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )

        # Sequence of fresh detections (evaluated at frames 1, 5, 10):
        # Frame 1: standing at y_bottom=175 -> snaps floor to 175 (window y=106.6..182.6)
        # Frame 5: mid-air jump apex at y=112..148 (27px jump inside window, cached across 5 frames!)
        # Frame 10: landed back at y_bottom=175
        fresh_rois = [
            BoundingBox(120, 139, 24, 36),  # frame 1: standing bottom = 175
            BoundingBox(126, 112, 24, 36),  # frame 5: mid-air apex bottom = 148
            BoundingBox(132, 139, 24, 36),  # frame 10: landed bottom = 175
        ]
        call_idx = {"i": 0}

        def fake_detect(*args, **kwargs):
            idx = min(call_idx["i"], len(fresh_rois) - 1)
            call_idx["i"] += 1
            return fresh_rois[idx]

        engine.detector.detect = fake_detect
        blank = np.full((fh, fw, 3), 64, dtype=np.uint8)
        cam = engine.cam_full_view
        cy_trace = []
        for f_idx in range(12):
            cam = engine.process_frame(blank, cam, f_idx, 128, 32)
            cy_trace.append(cam[1])

        # Floor must stay rock-steady near 175 throughout the subsampled mid-air apex (< 2px drift)
        assert engine.floor_est.floor_y == pytest.approx(175.0, abs=2.0)
        # Camera cy after initial frame-1 lock must have near-zero vertical oscillation
        assert max(cy_trace[1:]) - min(cy_trace[1:]) < 2.0

    def test_horizontal_continuity_locks_onto_hero_over_distant_enemy(self):
        """expected_cx prevents YOLO argmax from ping-ponging between hero (left) and enemy (right)."""
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Box 0: Enemy on right side (x≈240 -> cx_model=505, y_bottom≈145 -> 414, conf=0.72)
        # Box 1: Hero on left side (x≈85 -> cx_model=179, y_bottom≈145 -> 414, conf=0.60)
        pred = np.zeros((1, 5, 2), dtype=np.float32)
        pred[0, :, 0] = [505.0, 363.0, 50.0, 102.0, 0.72]
        pred[0, :, 1] = [179.0, 363.0, 50.0, 102.0, 0.60]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi = det._detect_yolo(
            frame, platformer_mode=True, expected_floor_y=145.0, expected_cx=85.0
        )
        assert roi is not None
        rx, _, rw, _ = roi
        hero_cx = rx + rw / 2.0
        assert 70.0 <= hero_cx <= 100.0

    def test_downward_platform_drop_recovers_briskly_even_with_subsampling(self):
        """
        Regression test for v8.0.8: when the player drops from an upper platform (y_bottom=95)
        onto a lower platform (y_bottom=185) under subsample_frames=5 and smoothness=0.80,
        the camera must descend rapidly onto the lower platform within <= 6 frames (~0.24s at 25fps)
        instead of lagging for 2-3 seconds, while keeping jump hops steady.
        """
        from src.engine.auto_action.camera import _smooth
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=5,
            auto_fast_tracking=False,
            smoothness=0.80,
            scene_change_threshold=0.0,
        )
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )

        # Frame 1 & Frame 5: player standing on upper platform (y=59..95)
        # Frame 10 & Frame 15: player drops to lower ground (y=149..185)
        fresh_rois = [
            BoundingBox(120, 59, 24, 36),
            BoundingBox(124, 59, 24, 36),
            BoundingBox(132, 149, 24, 36),
            BoundingBox(136, 149, 24, 36),
        ]
        call_idx = {"i": 0}

        def fake_detect(*args, **kwargs):
            idx = min(call_idx["i"], len(fresh_rois) - 1)
            call_idx["i"] += 1
            return fresh_rois[idx]

        engine.detector.detect = fake_detect
        blank = np.full((fh, fw, 3), 64, dtype=np.uint8)
        cam_prev = engine.cam_full_view

        # Settle on upper platform through frame 9 (fresh detections at f=1 and f=5)
        for f_idx in range(10):
            cam_now = engine.process_frame(blank, cam_prev, f_idx, 128, 32)
            cam_prev = cam_now if f_idx <= 1 else _smooth(cam_prev, cam_now, 0.80)

        # At f_idx=10, fresh detection lands on y_bottom=185; run 6 frames of pipeline descent
        for f_idx in range(10, 16):
            cam_now = engine.process_frame(blank, cam_prev, f_idx, 128, 32)
            if (cam_now[1] - cam_prev[1]) > cam_now[3] * 0.04:
                sx = _smooth(cam_prev, cam_now, 0.80)
                sy = _smooth(cam_prev, cam_now, 0.30)
                cam_prev = type(sx)(sx[0], sy[1], sx[2], sx[3])
            else:
                cam_prev = _smooth(cam_prev, cam_now, 0.80)

        # After just 6 frames from the drop, the character's feet (y=185) MUST be cleanly inside
        # the DMD strip (cam_bottom >= 185) instead of still floating up on the old platform!
        cam_bottom_after_6f = cam_prev[1] + cam_prev[3] / 2.0
        assert cam_bottom_after_6f >= 185.0
        assert engine.floor_est.floor_y > 165.0


class TestUnifiedSmallVsTallSpriteFraming:
    """
    Regression suite for v8.0.11 unified 2D Platformer & VS Fighting camera model:
    - Small sprites (h <= 0.79 * crop_h) lock onto the floor line at 90% strip height (~3.2 px ground).
    - Tall sprites (h > 0.79 * crop_h, in both VS Fighting and tall-sprite Platformers)
      raise an imaginary floor line up to the knees/thighs until the face fits with ~3.5 DMD px
      headroom (11% crop_h), keeping that imaginary floor locked across crouches, jumps, and
      landings until a platform change occurs, with C0 continuity at the threshold.
    """

    def test_tall_sprite_focuses_upper_half_with_head_at_top_and_floor_below_frame(self):
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32)
        # crop_h = 76.0, max_fit_h = 76.0 * (0.90 - 0.11) = 60.04
        for roi, floor_y in [
            ((110, 92, 52, 98), 190.0),  # VS Fighting tall sprite (h=98)
            ((124, 96, 38, 84), 180.0),  # Tall-sprite platformer e.g. Dracula (h=84)
        ]:
            _, cy, _, ch = _build_camera_rect(
                fw, fh, roi, cfg, floor_y_est=floor_y, face_priority_mode=False
            )
            cam_top = cy - ch / 2.0
            cam_bottom = cy + ch / 2.0
            # Head anchored with comfortable ~3.5 DMD px (11% crop_h) headroom pad (never glued to row 0)
            assert cam_top == pytest.approx(roi[1] - ch * 0.11, abs=0.25)
            # Upper half of the character (head + torso) 100% inside the DMD strip
            assert cam_bottom >= roi[1] + 0.50 * roi[3]
            # Real floor line / lower ankles deliberately below frame (imaginary floor at knees)
            assert cam_bottom < roi[1] + roi[3]

    def test_continuous_transition_at_max_fit_height_zero_vertical_jump(self):
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32)
        ch = 76.0
        floor_y = 180.0
        max_fit_h = ch * (0.90 - 0.11)  # 60.04

        small_just_below = (120, floor_y - (max_fit_h - 0.05), 30, max_fit_h - 0.05)
        tall_just_above = (120, floor_y - (max_fit_h + 0.05), 30, max_fit_h + 0.05)

        _, cy_small, _, _ = _build_camera_rect(
            fw, fh, small_just_below, cfg, floor_y_est=floor_y, face_priority_mode=False
        )
        _, cy_tall, _, _ = _build_camera_rect(
            fw, fh, tall_just_above, cfg, floor_y_est=floor_y, face_priority_mode=False
        )
        assert abs(cy_tall - cy_small) < 0.15

    def test_missed_detection_holds_tall_sprite_head_height_instead_of_plunging_to_floor(self):
        fw, fh = 304, 224
        cfg = _platformer_cfg(target_width=128, target_height=32, median_subject_height=96.0)
        _, cy_miss, _, ch = _build_camera_rect(
            fw, fh, None, cfg, floor_y_est=190.0, face_priority_mode=False
        )
        expected_head_top = 190.0 - 96.0 - ch * 0.11
        assert (cy_miss - ch / 2.0) == pytest.approx(expected_head_top, abs=0.25)

    def test_imaginary_floor_line_stays_locked_on_crouch_follows_jump_and_reanchors_on_new_platform(self):
        """
        Verify the full Imaginary Floor Line lifecycle on a tall platformer/fighter sprite:
        1. Standing (h=92, feet=180): imaginary floor locks at knees (~148.0), ~3.5 DMD px headroom.
        2. Crouching (h=56, feet=180, head=124): camera stays 100% locked on the imaginary floor
           instead of plunging down with the crouched head!
        3. High Jump (h=92, head=42, feet=134) & Return (feet=180): camera lifts smoothly so head is
           never clipped at apex, then returns to the exact imaginary floor line on landing.
        4. Platform Change (climbs onto upper platform at feet=120): imaginary floor re-anchors onto
           the character's knees on the new platform (~88.0).
        """
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=1,
            smoothness=0.0,
            scene_change_threshold=0.0,
            roi_history_window_s=0.0,
        )
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )
        blank = np.full((fh, fw, 3), 48, dtype=np.uint8)
        cam = engine.cam_full_view

        # 1. Standing on lower platform (y=88..180, h=92)
        for i in range(6):
            engine.detector.detect = lambda *a, **kw: BoundingBox(120, 88, 40, 92)
            cam = engine.process_frame(blank, cam, i, 128, 32)
        cy_stand = cam[1]
        ch = cam[3]
        assert (cy_stand - ch / 2.0) == pytest.approx(88.0 - ch * 0.11, abs=0.5)

        # 2. Crouch on the same platform (y=124..180, h=56): camera stays locked on imaginary floor!
        for i in range(6, 9):
            engine.detector.detect = lambda *a, **kw: BoundingBox(120, 124, 42, 56)
            cam = engine.process_frame(blank, cam, i, 128, 32)
        assert cam[1] == pytest.approx(cy_stand, abs=0.5)

        # 3. High jump (y=42..134, h=92) -> head protected, then return to feet=180 -> returns to cy_stand!
        engine.detector.detect = lambda *a, **kw: BoundingBox(124, 42, 40, 92)
        cam_jump = engine.process_frame(blank, cam, 9, 128, 32)
        assert (cam_jump[1] - ch / 2.0) <= 42.0 - ch * 0.10

        for i in range(10, 14):
            engine.detector.detect = lambda *a, **kw: BoundingBox(124, 88, 40, 92)
            cam = engine.process_frame(blank, cam_jump if i == 10 else cam, i, 128, 32)
        assert cam[1] == pytest.approx(cy_stand, abs=1.5)

        # 4. Climb onto upper platform (y=28..120, h=92) -> re-anchors imaginary floor to knees on new platform!
        for i in range(14, 30):
            engine.detector.detect = lambda *a, **kw: BoundingBox(140, 28, 40, 92)
            cam = engine.process_frame(blank, cam, i, 128, 32)
        assert (cam[1] - ch / 2.0) == pytest.approx(28.0 - ch * 0.11, abs=1.5)

    def test_deep_ground_bloat_and_textured_bricks_never_glue_or_clip_player_head(self):
        """
        Verify deep-ground protections:
        - Late first detection after frame-0 miss snaps immediately instead of crawling up from bottom.
        - Single-frame bbox downward bloat into deep ground shadow/bricks is clamped at standing height.
        - Textured high-contrast bricks in deep ground never cause ReadabilityScoreStage to freeze
          the camera below a sprite backed by flat dark sky.
        """
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=1,
            smoothness=0.80,
            scene_change_threshold=0.0,
            dmd_readability_score_enabled=True,
        )
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )

        # Build synthetic frame with flat sky at top (y=0..135) and busy checkerboard bricks (y=135..224)
        frame = np.zeros((fh, fw, 3), dtype=np.uint8)
        yy, xx = np.indices((fh - 135, fw))
        checker = (((xx // 4) + (yy // 4)) % 2 * 220).astype(np.uint8)
        frame[135:, :, 0] = checker
        frame[135:, :, 1] = checker // 2
        frame[135:, :, 2] = 180

        cam = engine.cam_full_view
        # Frames 0..1: missed detections (cam starts deep in the bricks at ~0.80*fh)
        engine.detector.detect = lambda *a, **kw: None
        cam = engine.process_frame(frame, cam, 0, 128, 32)
        cam = engine.process_frame(frame, cam, 1, 128, 32)

        # Frames 2..5: player detected standing on top of deep ground (y=99..135, h=36)
        for i in range(2, 6):
            engine.detector.detect = lambda *a, **kw: BoundingBox(130, 99, 24, 36)
            cam = engine.process_frame(frame, cam, i, 128, 32)
            assert engine.just_locked_first_detection == (i == 2)

        # Frame 6: single-frame bbox bloats deep into ground bricks (y=100..192, h=92!) while head stays at ~100
        engine.detector.detect = lambda *a, **kw: BoundingBox(130, 100, 24, 92)
        cam = engine.process_frame(frame, cam, 6, 128, 32)

        cam_top = cam[1] - cam[3] / 2.0
        cam_bottom = cam[1] + cam[3] / 2.0
        ground_dmd_px = (cam_bottom - 135.0) * (32.0 / cam[3])
        # Floor stayed locked near y=135 (~3.2 DMD px of ground), head has generous sky headroom!
        assert engine.floor_est.floor_y == pytest.approx(135.5, abs=2.0)
        assert 2.0 <= ground_dmd_px <= 4.5
        assert cam_top < 99.0 - 15.0

    def test_fighting_2d_and_platformer_share_unified_profile_and_classifier_avoids_cinema_traps(self):
        from src.engine.analysis.scene_types import SCENE_PROFILES, SceneType, classify_scene

        f2d = SCENE_PROFILES[SceneType.FIGHTING_2D]
        plat = SCENE_PROFILES[SceneType.PLATFORMER]
        assert f2d.platformer_mode is True
        assert f2d.auto_vertical_bias is True
        assert f2d.face_priority is False
        assert f2d.suggested_smoothness == pytest.approx(plat.suggested_smoothness)

        # Grounded tall 2D sprite (Dracula / SF2' PCE) -> platformer or fighting_2d, NEVER full_body_tall
        prof_tall, _, _ = classify_scene(
            {
                "tall_ratio": 1.18,
                "fill_ratio": 0.37,
                "body_aspect": 2.1,
                "floor_in_lower": True,
                "floor_var_score": 0.14,
                "x_variance": 0.18,
            }
        )
        assert prof_tall.scene_type in (SceneType.PLATFORMER, SceneType.FIGHTING_2D)
        assert prof_tall.platformer_mode is True

        # Very tall Neo-Geo 2D fighter (Art of Fighting, fill_ratio=0.57) -> fighting_2d / platformer
        prof_aof, _, _ = classify_scene(
            {
                "tall_ratio": 1.67,
                "fill_ratio": 0.567,
                "body_aspect": 1.85,
                "floor_in_lower": True,
                "floor_var_score": 0.12,
                "x_variance": 0.08,
            }
        )
        assert prof_aof.scene_type in (SceneType.PLATFORMER, SceneType.FIGHTING_2D)
        assert prof_aof.platformer_mode is True

        # Multi-tier vertical platformer (Earthworm Jim / Xenophobe) -> platformer, NEVER wide_shot
        prof_multi, _, _ = classify_scene(
            {
                "tall_ratio": 0.65,
                "fill_ratio": 0.17,
                "body_aspect": 1.6,
                "floor_in_lower": True,
                "floor_var_score": 0.34,
                "x_variance": 0.22,
            }
        )
        assert prof_multi.scene_type in (SceneType.PLATFORMER, SceneType.ACTION_HORIZONTAL)
        assert prof_multi.platformer_mode is True

        # Small arcade sprite -> NEVER talking_closeup / talking_medium
        prof_small, _, _ = classify_scene(
            {
                "tall_ratio": 0.42,
                "fill_ratio": 0.12,
                "body_aspect": 1.2,
                "floor_in_lower": False,
                "floor_var_score": 0.55,
                "x_variance": 0.04,
            }
        )
        assert prof_small.scene_type not in (SceneType.TALKING_CLOSEUP, SceneType.TALKING_MEDIUM)

    def test_detector_rejects_bulky_cave_scenery_and_outer_edge_signpost_pareidolia(self):
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Box 0: Giant cave ceiling rock pareidolia (Dracula: bw=340 -> 0.53 > 0.40, conf=0.82)
        # Box 1: Left-border static signpost (Earthworm Jim: cx=22 -> 0.034 < 0.07, conf=0.72)
        # Box 2: Actual player sprite in playfield (cx=310, cy=400, bw=64, bh=128, conf=0.52)
        pred = np.zeros((1, 5, 3), dtype=np.float32)
        pred[0, :, 0] = [320.0, 220.0, 340.0, 320.0, 0.82]
        pred[0, :, 1] = [22.0, 400.0, 36.0, 120.0, 0.72]
        pred[0, :, 2] = [310.0, 400.0, 64.0, 128.0, 0.52]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        # Even if expected_cx previously touched the left-edge signpost (x=22), must select Box 2!
        roi = det._detect_yolo(
            frame, platformer_mode=True, expected_floor_y=348.0, expected_cx=22.0
        )
        assert roi is not None
        rx, _, rw, _ = roi
        assert 260 <= rx <= 300
        assert rw < 90

    def test_explicit_dmd_clip_config_scene_type_forwards_to_auto_action_config(self):
        from src.engine.api import DmdClipConfig

        clip_cfg = DmdClipConfig(width=128, height=32, scene_type="platformer")
        assert clip_cfg.scene_type == "platformer"
        aa_cfg = AutoActionConfig.from_params({"action_scene_type": clip_cfg.scene_type})
        assert aa_cfg.scene_type == "platformer"


class TestDeepGroundPlatformerRegressionSuite:
    """
    Regression suite for v8.0.14 deep-ground platformer framing:
    Prevents the floor line from sinking into deep tiled/brick ground (showing only the
    character's feet until a crouch/jump snaps the camera back) and preserves standing height
    across sustained crouches.
    """

    def test_uninitialized_floor_estimator_never_biases_frame0_detector_toward_deep_ground(self):
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(subsample_frames=1, smoothness=0.0, scene_change_threshold=0.0)
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )
        assert engine.floor_est is not None
        assert engine.floor_est.has_detection is False

        seen_expected_floors: list = []

        def spy_detect(*args, **kwargs):
            seen_expected_floors.append(kwargs.get("expected_floor_y"))
            return BoundingBox(120, 96, 24, 36)  # surface at y=132 (60% height, NOT 80% = 179.2)

        engine.detector.detect = spy_detect
        blank = np.full((fh, fw, 3), 48, dtype=np.uint8)
        cam = engine.cam_full_view
        cam = engine.process_frame(blank, cam, 0, 128, 32)
        cam = engine.process_frame(blank, cam, 1, 128, 32)

        # Frame 0 MUST pass expected_floor_y=None (no synthetic 0.80*fh underground bias!)
        assert seen_expected_floors[0] is None
        # Frame 1+ passes the true locked surface floor y=132.0
        assert seen_expected_floors[1] == pytest.approx(132.0, abs=0.5)

    def test_detect_motion_strips_tiled_mortar_gap_deep_ground_scroll_and_locks_onto_sprite(self):
        det = _FrameDetector()
        fw, fh = 304, 224
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        # Frame A: deep brick ground (y=136..224) with 16px bricks + 12px mortar gaps,
        # plus compact player sprite standing on top at y=104..136, x=132..156.
        frame_a = bg.copy()
        for bx in range(20, 270, 28):
            frame_a[136:224, bx : bx + 16] = (140, 140, 140)
        frame_a[104:136, 132:156] = (230, 230, 230)
        det.detect_motion(frame_a, platformer_mode=True)

        # Frame B: deep ground scrolls left by 6px (creating gapped brick motion contours across
        # the whole 250px ground span) while sprite walks right by 6px.
        frame_b = bg.copy()
        for bx in range(14, 264, 28):
            frame_b[136:224, bx : bx + 16] = (240, 240, 240)
        frame_b[104:136, 138:162] = (255, 255, 255)

        roi = det.detect_motion(frame_b, platformer_mode=True)
        assert roi is not None
        rx, ry, rw, rh = roi
        assert rw < 55
        assert 96 <= ry <= 114
        assert 128 <= (ry + rh) <= 144

        # Verify camera framing puts 2..4.5 DMD pixels of ground below feet with full head visibility
        cfg = _platformer_cfg(target_width=128, target_height=32)
        _, cy, _, ch = _build_camera_rect(
            fw, fh, roi, cfg, floor_y_est=float(ry + rh), face_priority_mode=False
        )
        ground_dmd_px = ((cy + ch / 2.0) - float(ry + rh)) * (32.0 / ch)
        assert 2.0 <= ground_dmd_px <= 4.5
        assert (cy - ch / 2.0) < ry - 8.0

    def test_hybrid_detector_never_fuses_surface_sprite_with_disjoint_underground_motion(self):
        from src.engine.auto_action.interfaces import BoundingBox

        det = _FrameDetector()
        det.detect_person = lambda *a, **kw: BoundingBox(130, 100, 24, 36)
        det.detect_motion = lambda *a, **kw: BoundingBox(40, 184, 72, 34)

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi = det.detect(frame, mode="hybrid", platformer_mode=True)
        assert roi == BoundingBox(130, 100, 24, 36)

    def test_yolo_moderated_floor_affinity_immediately_breaks_drifted_underground_lock(self):
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Box 0: low-confidence underground brick pareidolia right at drifted expected_floor_y=202
        #        (bottom_model = 202 * 640 / 224 = 577, cy=532, bh=90, conf=0.24)
        # Box 1: genuine player sprite on surface y=100..136
        #        (bottom_model = 136 * 640 / 224 = 388.6, cy=337, bh=103, conf=0.65)
        pred = np.zeros((1, 5, 2), dtype=np.float32)
        pred[0, :, 0] = [320.0, 532.0, 72.0, 90.0, 0.24]
        pred[0, :, 1] = [280.0, 337.0, 52.0, 103.0, 0.65]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi = det._detect_yolo(frame, platformer_mode=True, expected_floor_y=202.0)
        assert roi is not None
        _, ry, _, rh = roi
        assert 128 <= (ry + rh) <= 144

        # And _FloorEstimator recovers rapidly from y=202 upward onto y=136 in <= 6 walking frames
        fe = _FloorEstimator(frame_h=224)
        fe.update(202.0)
        for _ in range(6):
            fe.update(136.0)
        assert fe.floor_y < 155.0

    def test_sustained_35_frame_crouch_preserves_tall_sprite_standing_height_and_imaginary_floor(self):
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=1,
            smoothness=0.0,
            scene_change_threshold=0.0,
            roi_history_window_s=0.0,
        )
        engine = TrackingEngine(
            fps=25.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )
        blank = np.full((fh, fw, 3), 48, dtype=np.uint8)
        cam = engine.cam_full_view

        # Stand for 8 frames (tall sprite h=92, feet=180)
        for i in range(8):
            engine.detector.detect = lambda *a, **kw: BoundingBox(120, 88, 40, 92)
            cam = engine.process_frame(blank, cam, i, 128, 32)
        cy_stand = cam[1]

        # Hold crouch for 35 frames (> maxlen=30) on the same floor (h=54, feet=180)
        for i in range(8, 43):
            engine.detector.detect = lambda *a, **kw: BoundingBox(120, 126, 42, 54)
            cam = engine.process_frame(blank, cam, i, 128, 32)

        assert engine.standing_subject_h == pytest.approx(92.0, abs=1.0)
        assert cam[1] == pytest.approx(cy_stand, abs=0.5)


class TestMultiTierJumpAndAntiHijackStability:
    """
    Regression suite for v8.0.18 multi-tier platformer jump tracking & sprite lock:
    - 2D `(expected_cx, expected_cy)` continuity keeps airborne jumping heroes favored over
      grounded enemies/sawblades even directly underneath on the same X column.
    - Global camera-scroll compensation extracts screen-centered jumping sprites over
      fast-scrolling background pipes/clouds/bushes.
    - Target-switch probation prevents 1-2 frame enemy/firebar/projectile spikes from
      stealing focus or corrupting `_FloorEstimator`.
    - Progressive lower-envelope floor adaptation + `_smooth_platformer_camera` follow
      continuous multi-platform chain-jumps smoothly without late freezes or catapult jumps.
    """

    def test_airborne_hero_jump_is_never_hijacked_by_grounded_enemy_in_yolo_or_motion(self):
        det = _FrameDetector()
        det._model_w = 640
        det._model_h = 640

        # Same horizontal column (x≈140 -> cx_model≈295), two sprites on 304x224:
        # Box 0: Grounded sawblade/enemy right on expected_floor_y=180 (y=144..180 -> cy_m=463, bh_m=103, conf=0.62)
        # Box 1: Airborne jumping hero above (y=52..88 -> cy_m=200, bh_m=103, conf=0.56)
        pred = np.zeros((1, 5, 2), dtype=np.float32)
        pred[0, :, 0] = [295.0, 463.0, 52.0, 103.0, 0.62]
        pred[0, :, 1] = [295.0, 200.0, 52.0, 103.0, 0.56]

        mock_session = MagicMock()
        mock_input = MagicMock()
        mock_input.name = "images"
        mock_session.get_inputs.return_value = [mock_input]
        mock_session.run.return_value = [pred]
        det._onnx_session_fast = mock_session

        frame = np.zeros((224, 304, 3), dtype=np.uint8)
        roi_yolo = det._detect_yolo(
            frame,
            platformer_mode=True,
            expected_floor_y=180.0,
            expected_cx=140.0,
            expected_cy=76.0,
        )
        assert roi_yolo is not None
        assert 44 <= roi_yolo[1] <= 62

        # Verify motion detector likewise keeps airborne hero over grounded enemy
        det_m = _FrameDetector()
        bg = np.zeros((224, 304, 3), dtype=np.uint8)
        for _ in range(3):
            det_m.detect_motion(bg.copy(), platformer_mode=True)
        frame_m = bg.copy()
        frame_m[144:180, 128:152] = (180, 180, 180)  # grounded grey hazard
        frame_m[52:88, 128:152] = (40, 80, 240)      # airborne colorful hero
        roi_m = det_m.detect_motion(
            frame_m,
            platformer_mode=True,
            expected_floor_y=180.0,
            expected_cx=140.0,
            expected_cy=76.0,
        )
        assert roi_m is not None
        assert 44 <= roi_m[1] <= 62

    def test_scroll_compensated_motion_tracks_stationary_screen_hero_over_scrolling_pipes(self):
        det = _FrameDetector()
        fw, fh = 320, 240

        def _render_scrolling_scene(scroll_x: int, hero_y: int) -> np.ndarray:
            img = np.full((fh, fw, 3), (180, 90, 50), dtype=np.uint8)  # sky
            # Rigidly scrolling ground, pipes, and clouds (all shift by -scroll_x)
            for pipe_base in (90, 230, 360):
                px = pipe_base - scroll_x
                x1, x2 = max(0, px), min(fw, px + 44)
                if x2 > x1:
                    img[152:216, x1:x2] = (40, 185, 40)
                    img[152:216, x1 : min(x2, x1 + 6)] = (120, 235, 120)
            for cloud_base in (70, 210, 340):
                cx = cloud_base - scroll_x
                x1, x2 = max(0, cx), min(fw, cx + 48)
                if x2 > x1:
                    img[42:68, x1:x2] = (235, 235, 235)
            img[216:240, :] = (60, 110, 190)
            # Hero stays near screen center x=144 while jumping vertically
            img[hero_y : hero_y + 34, 144:168] = (30, 40, 245)
            img[hero_y + 6 : hero_y + 20, 148:164] = (230, 200, 40)
            return img

        f0 = _render_scrolling_scene(scroll_x=0, hero_y=120)
        f1 = _render_scrolling_scene(scroll_x=12, hero_y=104)
        f2 = _render_scrolling_scene(scroll_x=24, hero_y=88)

        det.detect_motion(f0, platformer_mode=True)
        det.detect_motion(f1, platformer_mode=True)
        roi = det.detect_motion(f2, platformer_mode=True, expected_cx=156.0, expected_cy=105.0)

        assert roi is not None
        rx, ry, rw, _rh = roi
        hero_cx = rx + rw * 0.5
        assert 132.0 <= hero_cx <= 180.0
        assert 76 <= ry <= 102
        assert rw <= 52

    def test_target_switch_probation_rejects_transient_enemy_hijacks_and_preserves_floor(self):
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=1,
            smoothness=0.75,
            scene_change_threshold=0.0,
            roi_history_window_s=1.0,
        )
        engine = TrackingEngine(
            fps=20.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )
        blank = np.full((fh, fw, 3), 48, dtype=np.uint8)
        cam = engine.cam_full_view

        # Lock onto hero on upper platform (x=76..100, y=64..100 -> floor=100) for 6 frames
        for i in range(6):
            engine.detector.detect = lambda *a, **kw: BoundingBox(76, 64, 24, 36)
            cam = engine.process_frame(blank, cam, i, 128, 32)

        locked_floor = engine.floor_est.floor_y
        locked_cx = cam[0]
        locked_cy = cam[1]
        assert locked_floor == pytest.approx(100.0, abs=1.0)

        # 2 transient enemy detections far away on lower ground (x=248..272, y=154..190)
        for i in range(6, 8):
            engine.detector.detect = lambda *a, **kw: BoundingBox(248, 154, 24, 36)
            cam = engine.process_frame(blank, cam, i, 128, 32)

        # Must completely ignore the 2-frame hijack: zero floor corruption and near-zero camera jump
        assert engine.floor_est.floor_y == pytest.approx(locked_floor, abs=0.5)
        assert abs(cam[0] - locked_cx) < 2.0
        assert abs(cam[1] - locked_cy) < 2.0

        # Hero resumes jumping at x=80..104 -> stays seamlessly locked
        engine.detector.detect = lambda *a, **kw: BoundingBox(80, 50, 24, 36)
        cam = engine.process_frame(blank, cam, 8, 128, 32)
        assert engine._last_valid_roi_cx == pytest.approx(92.0, abs=1.0)

    def test_chain_jumping_across_vertical_platforms_tracks_smoothly_without_late_lurch(self):
        from src.engine.auto_action.camera import _smooth_platformer_camera
        from src.engine.auto_action.interfaces import BoundingBox
        from src.plugins.trackers.tracker import TrackingEngine

        fw, fh = 304, 224
        cfg = _platformer_cfg(
            target_width=128,
            target_height=32,
            subsample_frames=1,
            smoothness=0.75,
            scene_change_threshold=0.0,
            roi_history_window_s=3.0,
        )
        engine = TrackingEngine(
            fps=20.0,
            frame_w=fw,
            frame_h=fh,
            effective_frame_top=0,
            effective_frame_h=fh,
            effective_frame_left=0,
            effective_frame_w=fw,
            face_priority_mode=False,
            cfg=cfg,
        )
        blank = np.full((fh, fw, 3), 48, dtype=np.uint8)
        cam_prev = engine.cam_full_view

        # Continuous upward chain-jumping sequence across 3 platform tiers (never standing still 6f!):
        # Tier 0 (feet=190) -> Jump -> Tier 1 touch (142) -> Jump (108) -> Tier 2 touch (116) -> Jump (74) -> Tier 3 (84)
        bottom_seq = [
            190, 190, 190,
            166, 140, 142, 122, 106, 116, 96, 78, 84, 72, 82, 84, 84,
        ]
        cy_history = []
        for idx, btm in enumerate(bottom_seq):
            roi_now = BoundingBox(132, int(btm - 34), 24, 34)
            engine.detector.detect = lambda *a, _r=roi_now, **kw: _r
            cam_now = engine.process_frame(blank, cam_prev, idx, 128, 32)
            if idx == 0 or engine.just_locked_first_detection:
                cam = cam_now
            else:
                cam = _smooth_platformer_camera(cam_prev, cam_now, cfg.smoothness)
            cam_prev = cam
            cy_history.append(cam[1])

        ch = cam_prev[3]
        step_deltas = [abs(cy_history[i] - cy_history[i - 1]) for i in range(2, len(cy_history))]

        # 1. Floor estimator adapted upward via lower-envelope tracking despite non-zero jump spread
        assert engine.floor_est.floor_y < 140.0
        # 2. Final camera strip cleanly frames the hero on the top platform (y=50..84)
        assert (cam_prev[1] - ch / 2.0) <= 50.0
        assert (cam_prev[1] + ch / 2.0) >= 84.0
        # 3. Every single frame step is smooth and bounded (zero sudden catapult lurch)
        assert max(step_deltas) <= ch * 0.21

    def test_projectile_scale_filter_demotes_small_fireballs_and_bubbles_near_hero(self):
        det = _FrameDetector()
        fw, fh = 320, 240
        bg = np.zeros((fh, fw, 3), dtype=np.uint8)
        for _ in range(3):
            det.detect_motion(bg.copy(), platformer_mode=True)

        frame = bg.copy()
        # Small bright projectile/bubble right on expected_floor_y=185 (h=18 < 0.48 * 68)
        frame[167:185, 165:185] = (40, 200, 255)
        # Jumping hero above (h=68 matching expected_h=68)
        frame[78:146, 132:168] = (40, 120, 245)

        roi = det.detect_motion(
            frame,
            platformer_mode=True,
            expected_floor_y=185.0,
            expected_cx=155.0,
            expected_cy=125.0,
            expected_h=68.0,
        )
        assert roi is not None
        assert roi[3] >= 50
        assert 70 <= roi[1] <= 90





