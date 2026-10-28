import collections
import os
import logging
from typing import Deque, Tuple, Optional, List
import numpy as np
import cv2
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.engine.scoring.dmd_readability_engine import DmdReadabilityEngine

logger = logging.getLogger(__name__)

class SceneChangeScore:
    """Detects cuts and hard scene transitions."""
    @staticmethod
    def compute(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        import cv2
        try:
            if frame_a is None or frame_b is None:
                return 1.0
            small_a = cv2.resize(frame_a, (64, 32), interpolation=cv2.INTER_AREA)
            small_b = cv2.resize(frame_b, (64, 32), interpolation=cv2.INTER_AREA)
            hsv_a = cv2.cvtColor(small_a, cv2.COLOR_BGR2HSV)
            hsv_b = cv2.cvtColor(small_b, cv2.COLOR_BGR2HSV)
            scores = []
            for ch in (0, 2):   # H, V
                hist_a = cv2.calcHist([hsv_a], [ch], None, [32], [0, 256])
                hist_b = cv2.calcHist([hsv_b], [ch], None, [32], [0, 256])
                cv2.normalize(hist_a, hist_a)
                cv2.normalize(hist_b, hist_b)
                scores.append(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))
            return max(0.0, min(1.0, float(np.mean(scores))))
        except Exception:
            return 1.0

from src.engine.config.auto_action_config import AutoActionConfig
from src.plugins.detectors.detector import _FrameDetector, DetectorFactory
from src.engine.auto_action.camera import _build_camera_rect, _apply_look_ahead, closeup_eye_mouth_fractions
from src.engine.analysis.analysis import _FloorEstimator, _clamp
from src.engine.auto_action.interfaces import ITracker, BoundingBox, CamRect
from src.engine.auto_action.renderer import Renderer


@dataclass
class FrameTrackingContext:
    """Context object passed through the tracker pipeline stages."""
    frame: np.ndarray
    cam_prev: CamRect
    src_idx: int
    out_w: int
    out_h: int
    
    # State accumulated across stages
    raw_roi: Optional[BoundingBox] = None
    face_roi: Optional[BoundingBox] = None
    floor_y_est: Optional[float] = None
    cam_now_proposed: Optional[CamRect] = None
    cam_now: Optional[CamRect] = None
    fresh_detection: bool = True


class ITrackerStage(ABC):
    """Abstract base class for a tracking pipeline stage."""
    @abstractmethod
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        pass


class SceneChangeStage(ITrackerStage):
    """Detects cuts and hard scene transitions, resetting history."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.scene_change_enabled and engine.prev_frame_for_scene is not None:
            sim = SceneChangeScore.compute(engine.prev_frame_for_scene, context.frame)
            cut_threshold = min(0.35, 1.0 - engine.cfg.scene_change_threshold)
            if sim < cut_threshold:
                engine.roi_history.clear()
                engine.standing_heights.clear()
                engine.standing_subject_h = float(getattr(engine.cfg, "median_subject_height", 0.0) or 0.0)
                engine._prev_valid_top = None
                engine._locked_first_detection = False
                engine.just_locked_first_detection = False
                if engine.floor_est is not None:
                    engine.floor_est = _FloorEstimator(engine.cam_frame_h)
                engine.prev_roi_cx = None
                engine.prev_roi_cy = None
                engine._last_valid_roi_cx = None
                engine._last_yolo_roi = None
                engine.frames_since_scene_change = 0
                
                # Reset dynamic detector on cut
                if getattr(engine.cfg, "auto_detector_fallback", False):
                    engine.current_detector = "person"

        engine.prev_frame_for_scene = context.frame
        engine.frames_since_scene_change += 1


class DetectionStage(ITrackerStage):
    """Invokes the detector model to retrieve raw ROI."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        expected_floor_y = engine.floor_est.floor_y if engine.floor_est is not None else None
        expected_cx = getattr(engine, "_last_valid_roi_cx", None)
        
        if getattr(engine.cfg, 'auto_fast_tracking', False):
            # Target roughly 5 frames per second for YOLO processing
            subsample = max(1, math.ceil(engine.fps / 5.0))
        else:
            subsample = getattr(engine.cfg, 'subsample_frames', 3)
        run_detector = (
            subsample <= 1 or
            engine.frames_since_scene_change <= 1 or
            engine.frames_since_scene_change % subsample == 0
        )

        if not run_detector:
            context.fresh_detection = False
            context.raw_roi = getattr(engine, "_last_yolo_roi", None)
            return

        context.fresh_detection = True
        extra_kw = {"expected_cx": expected_cx} if isinstance(engine.detector, _FrameDetector) else {}

        if engine.face_priority_mode:
            context.raw_roi = engine.detector.detect(
                context.frame, engine.current_detector,
                multi_fusion=engine.cfg.multi_roi_fusion_enabled and not engine.cfg.platformer_mode,
                min_conf=engine.cfg.roi_confidence_min,
                roi_persistence_score=engine.roi_persistence_score if getattr(engine.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=engine.cfg.platformer_mode,
                expected_floor_y=expected_floor_y,
                **extra_kw,
            )
        else:
            detect_frame = context.frame[engine.effective_frame_top:engine.effective_frame_h, :]
            context.raw_roi = engine.detector.detect(
                detect_frame, engine.current_detector,
                multi_fusion=engine.cfg.multi_roi_fusion_enabled and not engine.cfg.platformer_mode,
                min_conf=engine.cfg.roi_confidence_min,
                roi_persistence_score=engine.roi_persistence_score if getattr(engine.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=engine.cfg.platformer_mode,
                expected_floor_y=expected_floor_y - engine.effective_frame_top if expected_floor_y is not None else None,
                **extra_kw,
            )
            if context.raw_roi is not None and engine.effective_frame_top > 0:
                rx, ry, rw, rh = context.raw_roi
                context.raw_roi = BoundingBox(rx, ry + engine.effective_frame_top, rw, rh)

        engine._last_yolo_roi = context.raw_roi


class PersistenceStage(ITrackerStage):
    """Calculates ROI persistence score over time."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if getattr(engine.cfg, 'roi_persistence_score_enabled', True):
            if context.raw_roi is not None:
                engine.roi_persistence_frames = min(120, engine.roi_persistence_frames + 1)
            else:
                engine.roi_persistence_frames = max(0, engine.roi_persistence_frames - 2)
            engine.roi_persistence_score = min(1.0, engine.roi_persistence_frames / 60.0)
        else:
            engine.roi_persistence_score = 1.0


class ValidationStage(ITrackerStage):
    """Rejects micro or insignificant ROI detections and full-frame scroll noise."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        # Micro-detection Rejection (relaxed in platformer/2D sprite mode where sprites are ~0.8%-1.5% of screen area)
        if context.raw_roi is not None and engine.cfg.min_roi_area_ratio > 0.0:
            roi_area = context.raw_roi[2] * context.raw_roi[3]
            frame_area = engine.frame_w * engine.frame_h
            is_floor_scene = getattr(engine.cfg, "platformer_mode", False)
            min_ratio = (
                min(engine.cfg.min_roi_area_ratio, 0.004)
                if is_floor_scene
                else engine.cfg.min_roi_area_ratio
            )
            if frame_area > 0 and (roi_area / frame_area) < min_ratio:
                context.raw_roi = None

        # Minimum Useful Size Rejection
        cx, cy_center, crop_w_full, crop_h_src = engine.cam_full_view
        if context.raw_roi is not None and engine.cfg.min_subject_dmd_px > 0:
            _dmd_scale = context.out_w / float(crop_w_full)
            dmd_w = context.raw_roi[2] * _dmd_scale
            dmd_h = context.raw_roi[3] * _dmd_scale
            if dmd_w < engine.cfg.min_subject_dmd_px and dmd_h < engine.cfg.min_subject_dmd_px:
                context.raw_roi = None


class FaceClippingStage(ITrackerStage):
    """Clips ROI to face or eyes depending on profile."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        context.face_roi = engine._clip_to_face_roi(context.raw_roi)


class FloorEstimationStage(ITrackerStage):
    """Estimates floor level for platformer and ground-tracked modes."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.floor_est is not None:
            # Never feed cached subsampled ROIs into _FloorEstimator: repeating a single
            # frozen mid-air jump sample across N subsampled frames would forge zero
            # foot-variance and trigger a false upper-platform stance jump.
            if not context.fresh_detection:
                context.floor_y_est = (
                    engine.floor_est.floor_y
                    if engine.floor_est.floor_y is not None
                    else engine.floor_est.update(None)
                )
                return

            roi_bottom = None
            if context.raw_roi is not None:
                rx, ry, rw, rh = context.raw_roi
                engine._platformer = getattr(engine.cfg, "platformer_mode", False)
                bottom_val = float(ry + rh)
                if engine._platformer:
                    # Reject squat horizontal tiles wholly below the established floor surface
                    # (prevents deep-ground brick pareidolia from pulling the floor underground)
                    is_underground_tile = (
                        engine.floor_est.floor_y is not None
                        and getattr(engine.floor_est, "_has_detection", False)
                        and float(ry) >= float(engine.floor_est.floor_y) - 2.0
                        and float(rw) > float(rh) * 1.15
                    )
                    min_valid_bottom = float(engine.effective_frame_top) + float(engine.effective_frame_h) * 0.30
                    is_wide_explosion = (
                        float(rw) > float(engine.effective_frame_w) * 0.60
                        and float(rh) > float(engine.effective_frame_h) * 0.55
                    )
                    if is_underground_tile:
                        context.raw_roi = None
                        context.face_roi = None
                    elif not is_wide_explosion and float(rh) <= float(engine.effective_frame_h) * 0.78 and bottom_val >= min_valid_bottom:
                        # Clamp single-frame downward bbox bloat into deep ground shadows/tiles
                        # when the character's head stayed steady on the same platform.
                        if len(engine.standing_heights) >= 3 and engine._prev_valid_top is not None:
                            med_char_h = float(np.median(engine.standing_heights))
                            if float(rh) > med_char_h * 1.28 and abs(float(ry) - engine._prev_valid_top) <= med_char_h * 0.25:
                                clamped_h = max(8, int(round(med_char_h)))
                                context.raw_roi = BoundingBox(rx, ry, rw, clamped_h)
                                context.face_roi = engine._clip_to_face_roi(context.raw_roi)
                                rh = clamped_h
                                bottom_val = float(ry + rh)
                        roi_bottom = bottom_val
                        engine.standing_heights.append(float(rh))
                        cfg_med = float(getattr(engine.cfg, "median_subject_height", 0.0) or 0.0)
                        engine.standing_subject_h = max(cfg_med, float(np.percentile(engine.standing_heights, 75)))
                        engine._prev_valid_top = float(ry)
                elif not engine.face_priority_mode:
                    # Non-platformer ground estimation: use actual feet bottom (never ry + 0.25*H,
                    # which falsely treated a close-up character's forehead as their shoes),
                    # and ignore dominant close-up/tall boxes where the bottom is a chest/frame clip.
                    if float(rh) <= float(engine.effective_frame_h) * 0.65:
                        roi_bottom = bottom_val
            context.floor_y_est = engine.floor_est.update(roi_bottom)


class HistorySynthesisStage(ITrackerStage):
    """Smooths ROI over time using a deque history buffer."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.roi_history_enabled:
            if context.fresh_detection and context.raw_roi is not None:
                if (
                    bool(getattr(engine.cfg, "platformer_mode", False))
                    and engine.roi_history
                ):
                    prev_hr = engine.roi_history[-1][1]
                    prev_bottom = float(prev_hr[1] + prev_hr[3])
                    new_bottom = float(context.raw_roi[1] + context.raw_roi[3])
                    # Flush stale platform history on genuine downward drops OR confirmed
                    # upward platform climbs so synthesized ROI tracks the new platform cleanly.
                    is_downward_drop = (
                        new_bottom - prev_bottom > float(engine.effective_frame_h) * 0.08
                        and new_bottom < float(engine.effective_frame_h) * 0.96
                    )
                    is_upward_climb = (
                        engine.floor_est is not None
                        and getattr(engine.floor_est, "_reanchoring_up", False)
                        and prev_bottom - new_bottom > float(engine.effective_frame_h) * 0.06
                    )
                    if is_downward_drop or is_upward_climb:
                        engine.roi_history.clear()
                engine.roi_history.append((1.0, context.raw_roi))
                while len(engine.roi_history) > engine.roi_history_max_len:
                    engine.roi_history.popleft()
            if engine.roi_history:
                total_w = 0.0
                wx, wy, ww, wh = 0.0, 0.0, 0.0, 0.0
                for idx, (_, hr) in enumerate(engine.roi_history):
                    w = float(idx + 1)
                    total_w += w
                    wx += w * hr[0]
                    wy += w * hr[1]
                    ww += w * hr[2]
                    wh += w * hr[3]
                if total_w > 0:
                    context.raw_roi = BoundingBox(int(round(wx / total_w)), int(round(wy / total_w)), int(round(ww / total_w)), int(round(wh / total_w)))
                    context.face_roi = engine._clip_to_face_roi(context.raw_roi)


class SceneClassificationStage(ITrackerStage):
    """Dynamically applies the Continuous Scoring Matrix."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if getattr(engine.cfg, "dynamic_scene_detection", False):
            wait_frames = min(15, max(5, engine.roi_history_max_len))
            if engine.frames_since_scene_change == wait_frames and len(engine.roi_history) > 3:
                from src.engine.analysis.scene_types import classify_scene
                
                arr_widths, heights, x_centers, y_centers, fill_ratios = [], [], [], [], []
                for _, hr in engine.roi_history:
                    arr_widths.append(hr[2])
                    heights.append(hr[3])
                    x_centers.append(hr[0] + hr[2]/2.0)
                    y_centers.append(hr[1] + hr[3]/2.0)
                    fill_ratios.append(hr[3] / float(engine.frame_h))
                    
                median_h = float(np.median(heights))
                median_w = float(np.median(arr_widths))
                
                floor_in_lower = False
                if engine.floor_est and engine.floor_est.floor_y and engine.floor_est.floor_y > (engine.cam_frame_h * 0.5):
                    floor_in_lower = True
                
                target_ratio = float(engine.cfg.target_width) / max(1, engine.cfg.target_height)
                dmd_crop_h = float(engine.frame_w) / max(0.01, target_ratio)
                bottoms = [hr[1] + hr[3] for _, hr in engine.roi_history]
                dyn_floor_var = float(np.std(bottoms)) / max(1.0, float(engine.cam_frame_h)) if bottoms else 1.0
                scene_signals = {
                    "tall_ratio":      median_h / max(1.0, dmd_crop_h),
                    "fill_ratio":      float(np.median(fill_ratios)),
                    "body_aspect":     median_h / max(1.0, median_w),
                    "floor_in_lower":  floor_in_lower,
                    "floor_var_score": dyn_floor_var,
                    "x_variance":      float(np.var(x_centers)) / max(1.0, float(engine.frame_w)**2),
                    "y_variance":      float(np.var(y_centers)) / max(1.0, float(engine.cam_frame_h)**2),
                }
                
                new_profile, scoreboard_lines, _ = classify_scene(scene_signals)
                old_scene = getattr(engine.cfg, "scene_type", "Unknown")
                
                if old_scene != new_profile.scene_type:
                    logger.info(f"[DYNAMIC] Camera cut detected! Scene changed dynamically from '{old_scene}' to '{new_profile.scene_type}'")
                else:
                    logger.debug(f"[DYNAMIC] Camera cut detected! Scene remains '{new_profile.scene_type}'")
                
                for line in scoreboard_lines:
                    logger.debug(line)
                
                engine.cfg.scene_profile = new_profile
                engine.cfg.scene_type = new_profile.scene_type
                engine.cfg.face_clip_mode = new_profile.face_clip_mode
                engine.cfg.platformer_mode = new_profile.platformer_mode
                engine.cfg.auto_vertical_bias = new_profile.auto_vertical_bias
                context.face_roi = engine._clip_to_face_roi(context.raw_roi)


class DetectorFallbackStage(ITrackerStage):
    """Falls back to hybrid detector if person detection fails on an unknown object."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if getattr(engine.cfg, "auto_detector_fallback", False):
            wait_frames = min(15, max(5, engine.roi_history_max_len))
            if engine.frames_since_scene_change == wait_frames and len(engine.roi_history) == 0:
                if engine.current_detector == "person":
                    engine.current_detector = "hybrid"


class CameraBuilderStage(ITrackerStage):
    """Builds the raw proposed Camera rectangle before lissage, with Tripod Deadzone & Velocity Clamping."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        engine.just_locked_first_detection = False
        if context.face_roi is not None and not engine._locked_first_detection:
            engine._locked_first_detection = True
            engine.just_locked_first_detection = True

        raw_cam = _build_camera_rect(
            engine.frame_w, engine.cam_frame_h, context.face_roi, engine.cfg,
            floor_y_est=context.floor_y_est, frame_top=engine.cam_frame_top,
            face_priority_mode=engine.face_priority_mode,
            effective_frame_left=engine.effective_frame_left,
            effective_frame_w=engine.effective_frame_w,
            effective_frame_top=float(engine.effective_frame_top),
            effective_frame_h=engine.effective_frame_h,
            locked_crop_size=engine.locked_crop_size,
            standing_height=engine.standing_subject_h,
        )
        if (
            context.cam_prev is not None
            and engine.frames_since_scene_change > 1
            and not engine.just_locked_first_detection
            and float(getattr(engine.cfg, "smoothness", 0.0)) > 0.0
        ):
            prev_cx, prev_cy = float(context.cam_prev[0]), float(context.cam_prev[1])
            prop_cx, prop_cy, cw, ch = float(raw_cam[0]), float(raw_cam[1]), float(raw_cam[2]), float(raw_cam[3])
            dx = prop_cx - prev_cx
            dy = prop_cy - prev_cy
            # Tripod deadzone hysteresis: wider upward in platformer mode so sprite walk-cycle
            # wobble and normal hops never cause bobbing, but responsive both when dropping onto
            # a lower platform and when rescuing a sprite head crowding the top border.
            is_platformer = bool(getattr(engine.cfg, "platformer_mode", False))
            med_h = float(getattr(engine.cfg, "median_subject_height", 0.0) or 0.0)
            roi_h = float(context.face_roi[3]) if context.face_roi is not None else med_h
            is_tall_sprite = is_platformer and max(med_h, engine.standing_subject_h, roi_h) > ch * 0.79
            prev_top = prev_cy - ch / 2.0
            head_crowded = (
                is_platformer
                and context.face_roi is not None
                and float(context.face_roi[1]) < prev_top + ch * 0.06
            )
            dead_x = cw * (0.065 if is_platformer else 0.04)
            if is_platformer:
                if dy > 0.0:
                    dead_y = ch * 0.035
                elif head_crowded:
                    dead_y = ch * 0.02
                else:
                    dead_y = ch * (0.05 if is_tall_sprite else 0.085)
            else:
                dead_y = ch * 0.04
            target_cx = prev_cx if abs(dx) <= dead_x else prev_cx + math.copysign(abs(dx) - dead_x, dx)
            target_cy = prev_cy if abs(dy) <= dead_y else prev_cy + math.copysign(abs(dy) - dead_y, dy)
            # Maximum pan speed per frame before outer smoothing
            max_step_x = max(4.0, cw * (0.11 if is_platformer else 0.14))
            if is_platformer:
                if dy > 0.0 or head_crowded:
                    max_step_y = max(8.0, ch * 0.34)
                else:
                    max_step_y = max(5.0, ch * 0.22) if is_tall_sprite else max(2.5, ch * 0.08)
            else:
                max_step_y = max(3.5, ch * 0.14)
            clamped_cx = prev_cx + _clamp(target_cx - prev_cx, -max_step_x, max_step_x)
            clamped_cy = prev_cy + _clamp(target_cy - prev_cy, -max_step_y, max_step_y)
            raw_cam = CamRect(clamped_cx, clamped_cy, cw, ch)

        context.cam_now_proposed = raw_cam
        context.cam_now = context.cam_now_proposed


class ReadabilityScoreStage(ITrackerStage):
    """Evaluates spatial readability and rejects poor camera proposals (Momentum penalty)."""
    @staticmethod
    def _cam_to_top_left_roi(cam: Optional[CamRect]) -> Optional[Tuple[int, int, int, int]]:
        if cam is None:
            return None
        cx, cy, cw, ch = cam
        return (
            int(round(cx - cw / 2.0)),
            int(round(cy - ch / 2.0)),
            int(round(cw)),
            int(round(ch)),
        )

    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.cfg.dmd_visibility_score_enabled or getattr(engine.cfg, 'dmd_readability_score_enabled', True):
            roi_prev = self._cam_to_top_left_roi(context.cam_prev)
            roi_prop = self._cam_to_top_left_roi(context.cam_now_proposed)
            read_prev_score = engine.readability_engine.evaluate(context.frame, roi=roi_prev).overall / 100.0
            read_prop_score = engine.readability_engine.evaluate(context.frame, roi=roi_prop).overall / 100.0

            is_platformer_sprite = (
                bool(getattr(engine.cfg, "platformer_mode", False))
                and context.face_roi is not None
            )
            if not is_platformer_sprite and read_prop_score < read_prev_score * 0.72:
                # Reject severely degraded framing proposals (never in platformer mode when
                # tracking a detected sprite, where textured deep ground bricks otherwise
                # outscore clean sky and freeze the camera below the character's head).
                context.cam_now = context.cam_prev

            if getattr(engine.cfg, 'auto_tuning_dataset_dir', None) is not None:
                _ds_dir = engine.cfg.auto_tuning_dataset_dir
                os.makedirs(_ds_dir, exist_ok=True)
                cropped_proposed = Renderer.crop_frame_static(context.frame, context.cam_now)
                dmd_proposed_frame = cv2.resize(cropped_proposed, (engine.cfg.target_width, engine.cfg.target_height), interpolation=cv2.INTER_LANCZOS4)
                cv2.imwrite(os.path.join(_ds_dir, f"frame_{context.src_idx:04d}_dmd.png"), dmd_proposed_frame)
                with open(os.path.join(_ds_dir, "scores.csv"), "a") as f:
                    f.write(f"{context.src_idx},{read_prop_score:.3f},{read_prop_score:.3f},{engine.roi_persistence_score:.3f}\n")


class LookAheadStage(ITrackerStage):
    """Applies camera smoothing and look-ahead inertial scroll."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        curr_roi_cx: Optional[float] = None
        curr_roi_cy: Optional[float] = None
        if context.raw_roi is not None:
            curr_roi_cx = float(context.raw_roi[0] + context.raw_roi[2] / 2.0)
            curr_roi_cy = float(context.raw_roi[1] + context.raw_roi[3] / 2.0)
            
        live_vx, live_vy = 0.0, 0.0
        if curr_roi_cx is not None and engine.prev_roi_cx is not None:
            max_v = max(4.0, engine.frame_w * 0.025)
            live_vx = _clamp(curr_roi_cx - engine.prev_roi_cx, -max_v, max_v)
            live_vy = _clamp(curr_roi_cy - engine.prev_roi_cy, -max_v, max_v)
            
        if getattr(engine.cfg, "scroll_direction_memory_enabled", True):
            if context.raw_roi is not None:
                engine.scroll_vx = 0.94 * engine.scroll_vx + 0.06 * live_vx
                engine.scroll_vy = 0.94 * engine.scroll_vy + 0.06 * live_vy
                engine.scroll_memory_frames = min(60, engine.scroll_memory_frames + 1)
            else:
                engine.scroll_memory_frames = max(0, engine.scroll_memory_frames - 1)
                if engine.scroll_memory_frames == 0:
                    engine.scroll_vx *= 0.9
                    engine.scroll_vy *= 0.9
        else:
            engine.scroll_vx, engine.scroll_vy = live_vx, live_vy

        if engine.cfg.look_ahead_enabled and engine.cfg.look_ahead_factor > 0.0:
            context.cam_now = _apply_look_ahead(
                context.cam_now,
                engine.scroll_vx, engine.scroll_vy,
                engine.frame_w, engine.frame_h,
                engine.cfg.look_ahead_factor,
                roi_persistence=engine.roi_persistence_score,
                effective_frame_left=engine.effective_frame_left,
                effective_frame_w=engine.effective_frame_w,
            )
            
        engine.prev_roi_cx = curr_roi_cx
        engine.prev_roi_cy = curr_roi_cy
        if curr_roi_cx is not None:
            engine._last_valid_roi_cx = curr_roi_cx
        elif engine.roi_persistence_frames == 0:
            engine._last_valid_roi_cx = None
        
        engine._last_roi = context.raw_roi


class TrackingEngine(ITracker):
    """Stateful engine that handles target tracking across frames using a Pipeline pattern."""
    
    def __init__(self, fps: float, frame_w: int, frame_h: int, 
                 effective_frame_top: int, effective_frame_h: int, 
                 effective_frame_left: int, effective_frame_w: int,
                 face_priority_mode: bool, cfg: AutoActionConfig,
                 locked_crop_size: Optional[Tuple[float, float]] = None):
        self.fps = fps
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.effective_frame_top = effective_frame_top
        self.effective_frame_h = effective_frame_h
        self.effective_frame_left = effective_frame_left
        self.effective_frame_w = effective_frame_w
        self._face_priority_mode_init = face_priority_mode
        self.cfg = cfg
        
        target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
        from src.engine.auto_action.camera import _compute_base_crop_dimensions
        max_w, max_h = _compute_base_crop_dimensions(float(self.effective_frame_w), float(self.effective_frame_h), target_ratio)
        
        if locked_crop_size is not None:
            self.locked_crop_size = locked_crop_size
        else:
            # DMD Invariant: Keep the widest possible shot fitting the target aspect ratio
            self.locked_crop_size = (max_w, max_h)


        self.detector = DetectorFactory.create()

        self.readability_engine = DmdReadabilityEngine(
            target_w=self.cfg.target_width,
            target_h=self.cfg.target_height
        )

        self.floor_est: Optional[_FloorEstimator] = (
            _FloorEstimator(self.cam_frame_h) 
            if self.cfg.auto_vertical_bias or self.cfg.platformer_mode else None
        )
        initial_floor_y: Optional[float] = None
        if self.floor_est is not None and getattr(self.cfg, "platformer_mode", False) and not self.face_priority_mode:
            initial_floor_y = self.floor_est.update(None)

        self._cam_full_view: CamRect = _build_camera_rect(
            self.frame_w, self.cam_frame_h, None, self.cfg,
            floor_y_est=initial_floor_y,
            frame_top=self.cam_frame_top,
            face_priority_mode=self.face_priority_mode,
            effective_frame_left=self.effective_frame_left,
            effective_frame_w=self.effective_frame_w,
            effective_frame_top=float(self.effective_frame_top),
            effective_frame_h=self.effective_frame_h,
            locked_crop_size=self.locked_crop_size
        )
        self._last_roi: Optional[BoundingBox] = None
        
        self.prev_frame_for_scene: Optional[np.ndarray] = None
        self.scene_change_enabled = self.cfg.scene_change_threshold > 0.0
        self.frames_since_scene_change: int = 0
        
        self.roi_history: Deque[Tuple[float, Tuple[int, int, int, int]]] = collections.deque()
        self.roi_history_max_len: int = max(1, int(self.fps * max(0.0, self.cfg.roi_history_window_s)))
        self.roi_history_enabled: bool = self.cfg.roi_history_window_s > 0.0
        self.standing_heights: Deque[float] = collections.deque(maxlen=30)
        self.standing_subject_h: float = float(getattr(self.cfg, "median_subject_height", 0.0) or 0.0)
        self._prev_valid_top: Optional[float] = None
        self._locked_first_detection: bool = False
        self.just_locked_first_detection: bool = False
        
        self.prev_roi_cx: Optional[float] = None
        self.prev_roi_cy: Optional[float] = None
        self._last_valid_roi_cx: Optional[float] = None
        self.scroll_vx: float = 0.0
        self.scroll_vy: float = 0.0
        self.scroll_memory_frames: int = 0
        
        self.roi_persistence_frames: int = 0
        self.roi_persistence_score: float = 1.0
        self.current_detector: str = self.cfg.detector
        
        # Initialize Pipeline Stages
        self.stages: List[ITrackerStage] = [
            SceneChangeStage(),
            DetectionStage(),
            PersistenceStage(),
            ValidationStage(),
            FaceClippingStage(),
            FloorEstimationStage(),
            HistorySynthesisStage(),
            SceneClassificationStage(),
            DetectorFallbackStage(),
            CameraBuilderStage(),
            ReadabilityScoreStage(),
            LookAheadStage()
        ]

    @property
    def last_roi(self) -> Optional[BoundingBox]:
        return self._last_roi

    @property
    def cam_full_view(self) -> CamRect:
        return self._cam_full_view

    @property
    def face_priority_mode(self) -> bool:
        if hasattr(self.cfg, "scene_profile") and self.cfg.scene_profile is not None:
            return self.cfg.scene_profile.face_priority
        return self._face_priority_mode_init

    @property
    def cam_frame_h(self) -> float:
        return float(self.effective_frame_h)

    @property
    def cam_frame_top(self) -> float:
        return float(self.effective_frame_top)

    def process_frame(self, frame: np.ndarray, cam_prev: CamRect, src_idx: int, out_w: int, out_h: int) -> CamRect:
        """Processes a single frame using the discrete Pipeline stages."""
        context = FrameTrackingContext(
            frame=frame,
            cam_prev=cam_prev,
            src_idx=src_idx,
            out_w=out_w,
            out_h=out_h
        )
        
        for stage in self.stages:
            stage.process(context, self)
            
        return context.cam_now

    def _clip_to_face_roi(self, raw_roi: Optional[BoundingBox]) -> Optional[BoundingBox]:
        """Apply face clipping based on box geometry and the configured scene profile.

        For close-up `person` portraits (`aspect <= 1.4`), anchors on the expressive
        eye-to-mouth band (`[0.23*rh .. 0.61*rh]` for wide/square close-ups, centred at
        `0.42*rh`, and scaled smoothly upward for `1.0 < aspect <= 1.4` bust shots where
        upper chest enters `rh`) so wide DMD strips (`128x32`, `128x64`, `256x64`) frame
        both the eyes and the mouth without drifting up into the forehead or down onto
        the nose and chin.
        """
        if raw_roi is None:
            return None

        clip_mode = getattr(self.cfg, "face_clip_mode", "auto")
        if clip_mode == "none" or (not self.face_priority_mode and clip_mode == "auto"):
            return raw_roi

        rx, ry, rw, rh = raw_roi
        aspect = rh / max(1, rw)

        if clip_mode == "auto":
            clip_mode = "closeup" if aspect <= 1.4 else "full_body_head"
        elif clip_mode == "full_body_head" and aspect <= 1.4:
            # Self-healing guard: a compact/wide box (aspect <= 1.4) is a face or
            # close-up portrait, never a standing full-body figure. Applying full-body
            # head proportions (~10-20% at top) would clip pure forehead/hair.
            clip_mode = "closeup"
        elif clip_mode == "closeup" and aspect > 1.65:
            # Self-healing guard: a tall vertical box (aspect > 1.65) is a standing
            # character, not a close-up face; target the head rather than the torso.
            clip_mode = "full_body_head"

        sp = getattr(self.cfg, "scene_profile", None)
        sp_mode = getattr(sp, "face_clip_mode", None) if sp is not None else None

        if clip_mode == "closeup":
            eye_offset, head_frac = closeup_eye_mouth_fractions(aspect)

            if sp is not None and sp_mode in ("closeup", "auto"):
                if getattr(sp, "face_eye_offset", None) is not None:
                    eye_offset = sp.face_eye_offset
                if getattr(sp, "face_head_frac", None) is not None:
                    head_frac = sp.face_head_frac

            forehead_skip = int(rh * eye_offset)
            face_h = max(8, int(rh * head_frac))
            face_h = min(face_h, max(1, rh - forehead_skip))
            return BoundingBox(rx, ry + forehead_skip, rw, face_h)

        if clip_mode == "full_body_head":
            eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
            head_frac = 0.10

            if sp is not None and sp_mode in ("full_body_head", "auto"):
                if getattr(sp, "face_eye_offset", None) is not None:
                    eye_target_pct = sp.face_eye_offset
                if getattr(sp, "face_head_frac", None) is not None:
                    head_frac = sp.face_head_frac

            roi_h = max(8, int(rh * head_frac))
            roi_top = max(0, int(rh * eye_target_pct - roi_h / 2.0))
            roi_h = min(roi_h, max(1, rh - roi_top))
            return BoundingBox(rx, ry + roi_top, rw, roi_h)

        return raw_roi
