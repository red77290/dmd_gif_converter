import collections
import os
import logging
from typing import Deque, Tuple, Optional, List
import numpy as np
import cv2
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
from src.engine.auto_action.camera import _build_camera_rect, _apply_look_ahead
from src.engine.analysis.analysis import _FloorEstimator
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
            if sim < (1.0 - engine.cfg.scene_change_threshold):
                engine.roi_history.clear()
                context.cam_prev = engine.cam_full_view
                if engine.floor_est is not None:
                    engine.floor_est = _FloorEstimator(engine.cam_frame_h)
                engine.prev_roi_cx = None
                engine.prev_roi_cy = None
                engine.frames_since_scene_change = 0
                
                # Reset dynamic profile temporarily on cut
                if getattr(engine.cfg, "dynamic_scene_detection", False):
                    from src.engine.analysis.scene_types import DEFAULT_SCENE_PROFILE
                    engine.cfg.scene_profile = DEFAULT_SCENE_PROFILE
                    engine.cfg.scene_type = DEFAULT_SCENE_PROFILE.scene_type
                    
                # Reset dynamic detector on cut
                if getattr(engine.cfg, "auto_detector_fallback", False):
                    engine.current_detector = "person"

        engine.prev_frame_for_scene = context.frame
        engine.frames_since_scene_change += 1


class DetectionStage(ITrackerStage):
    """Invokes the detector model to retrieve raw ROI."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        expected_floor_y = engine.floor_est.floor_y if engine.floor_est is not None else None
        
        subsample = getattr(engine.cfg, 'subsample_frames', 3)
        run_detector = (
            subsample <= 1 or
            engine.frames_since_scene_change <= 1 or
            engine.frames_since_scene_change % subsample == 0
        )

        if not run_detector:
            context.raw_roi = getattr(engine, "_last_yolo_roi", None)
            return

        if engine.face_priority_mode:
            context.raw_roi = engine.detector.detect(
                context.frame, engine.current_detector,
                multi_fusion=engine.cfg.multi_roi_fusion_enabled and not engine.cfg.platformer_mode,
                min_conf=engine.cfg.roi_confidence_min,
                roi_persistence_score=engine.roi_persistence_score if getattr(engine.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=engine.cfg.platformer_mode,
                expected_floor_y=expected_floor_y
            )
        else:
            detect_frame = context.frame[engine.effective_frame_top:engine.effective_frame_h, :]
            context.raw_roi = engine.detector.detect(
                detect_frame, engine.current_detector,
                multi_fusion=engine.cfg.multi_roi_fusion_enabled and not engine.cfg.platformer_mode,
                min_conf=engine.cfg.roi_confidence_min,
                roi_persistence_score=engine.roi_persistence_score if getattr(engine.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=engine.cfg.platformer_mode,
                expected_floor_y=expected_floor_y - engine.effective_frame_top if expected_floor_y is not None else None
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
    """Rejects micro or insignificant ROI detections."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        # Micro-detection Rejection
        if context.raw_roi is not None and engine.cfg.min_roi_area_ratio > 0.0:
            roi_area = context.raw_roi[2] * context.raw_roi[3]
            frame_area = engine.frame_w * engine.frame_h
            if frame_area > 0 and (roi_area / frame_area) < engine.cfg.min_roi_area_ratio:
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
    """Estimates floor level for platformer modes."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.floor_est is not None:
            roi_bottom = None
            if context.raw_roi is not None:
                rx, ry, rw, rh = context.raw_roi
                engine._platformer = getattr(engine.cfg, "platformer_mode", False)
                if engine._platformer:
                    max_char_h = engine.effective_frame_h * 0.25
                    effective_rh = min(float(rh), max_char_h)
                    roi_bottom = ry + effective_rh
                else:
                    roi_bottom = float(ry + rh)
            context.floor_y_est = engine.floor_est.update(roi_bottom)


class HistorySynthesisStage(ITrackerStage):
    """Smooths ROI over time using a deque history buffer."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.roi_history_enabled:
            if context.raw_roi is not None:
                engine.roi_history.append((1.0, context.raw_roi))
                while len(engine.roi_history) > engine.roi_history_max_len:
                    engine.roi_history.popleft()
            elif engine.roi_history:
                n = len(engine.roi_history)
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
                    context.raw_roi = BoundingBox(int(wx / total_w), int(wy / total_w), int(ww / total_w), int(wh / total_w))
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
                
                scene_signals = {
                    "tall_ratio":      median_h / float(engine.cam_frame_h) if engine.cam_frame_h > 0 else 0.0,
                    "fill_ratio":      float(np.median(fill_ratios)),
                    "body_aspect":     median_h / max(1.0, median_w),
                    "floor_in_lower":  floor_in_lower,
                    "floor_var_score": 1.0, 
                    "x_variance":      float(np.var(x_centers)) / max(1.0, float(engine.frame_w)**2),
                    "y_variance":      float(np.var(y_centers)) / max(1.0, float(engine.cam_frame_h)**2),
                }
                
                new_profile, _, _ = classify_scene(scene_signals)
                if getattr(engine.cfg, "scene_type", None) != new_profile.scene_type:
                    old_scene = getattr(engine.cfg, "scene_type", "Unknown")
                    logger.debug(f"[DYNAMIC] Camera cut detected! Scene changed dynamically from '{old_scene}' to '{new_profile.scene_type}'")
                    if logger.isEnabledFor(logging.DEBUG):
                        print(f"16:00:00 [DEBUG  ] [UI] [DYNAMIC] Camera cut! Scene changed: {old_scene} -> {new_profile.scene_type}")
                
                engine.cfg.scene_profile = new_profile
                engine.cfg.scene_type = new_profile.scene_type


class DetectorFallbackStage(ITrackerStage):
    """Falls back to hybrid detector if person detection fails on an unknown object."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if getattr(engine.cfg, "auto_detector_fallback", False):
            wait_frames = min(15, max(5, engine.roi_history_max_len))
            if engine.frames_since_scene_change == wait_frames and len(engine.roi_history) == 0:
                if engine.current_detector == "person":
                    engine.current_detector = "hybrid"


class CameraBuilderStage(ITrackerStage):
    """Builds the raw proposed Camera rectangle before lissage."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        context.cam_now_proposed = _build_camera_rect(
            engine.frame_w, engine.cam_frame_h, context.face_roi, engine.cfg,
            floor_y_est=context.floor_y_est, frame_top=engine.cam_frame_top,
            face_priority_mode=engine.face_priority_mode,
            effective_frame_left=engine.effective_frame_left,
            effective_frame_w=engine.effective_frame_w,
            effective_frame_top=float(engine.effective_frame_top),
            effective_frame_h=engine.effective_frame_h
        )
        context.cam_now = context.cam_now_proposed


class ReadabilityScoreStage(ITrackerStage):
    """Evaluates spatial readability and rejects poor camera proposals (Momentum penalty)."""
    def process(self, context: FrameTrackingContext, engine: 'TrackingEngine') -> None:
        if engine.cfg.dmd_visibility_score_enabled or getattr(engine.cfg, 'dmd_readability_score_enabled', True):
            read_prev_score = engine.readability_engine.evaluate(context.frame, roi=context.cam_prev).overall / 100.0
            read_prop_score = engine.readability_engine.evaluate(context.frame, roi=context.cam_now_proposed).overall / 100.0

            if read_prop_score < read_prev_score * 0.95:
                # Reject width/height changes if readability is significantly worse
                context.cam_now = CamRect(context.cam_now_proposed[0], context.cam_now_proposed[1], context.cam_prev[2], context.cam_prev[3])

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
            live_vx = curr_roi_cx - engine.prev_roi_cx
            live_vy = curr_roi_cy - engine.prev_roi_cy
            
        if getattr(engine.cfg, "scroll_direction_memory_enabled", True):
            if context.raw_roi is not None:
                engine.scroll_vx = 0.9 * engine.scroll_vx + 0.1 * live_vx
                engine.scroll_vy = 0.9 * engine.scroll_vy + 0.1 * live_vy
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
        
        engine._last_roi = context.raw_roi


class TrackingEngine(ITracker):
    """Stateful engine that handles target tracking across frames using a Pipeline pattern."""
    
    def __init__(self, fps: float, frame_w: int, frame_h: int, 
                 effective_frame_top: int, effective_frame_h: int, 
                 effective_frame_left: int, effective_frame_w: int,
                 face_priority_mode: bool, cfg: AutoActionConfig):
        self.fps = fps
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.effective_frame_top = effective_frame_top
        self.effective_frame_h = effective_frame_h
        self.effective_frame_left = effective_frame_left
        self.effective_frame_w = effective_frame_w
        self._face_priority_mode_init = face_priority_mode
        self.cfg = cfg
        
        self.detector = DetectorFactory.create()

        self.readability_engine = DmdReadabilityEngine(
            target_w=self.cfg.target_width,
            target_h=self.cfg.target_height
        )

        self._cam_full_view: CamRect = _build_camera_rect(
            self.frame_w, self.cam_frame_h, None, self.cfg,
            frame_top=self.cam_frame_top,
            effective_frame_left=self.effective_frame_left,
            effective_frame_w=self.effective_frame_w,
            effective_frame_top=float(self.effective_frame_top),
            effective_frame_h=self.effective_frame_h
        )
        self._last_roi: Optional[BoundingBox] = None
        
        self.floor_est: Optional[_FloorEstimator] = (
            _FloorEstimator(self.cam_frame_h) 
            if self.cfg.auto_vertical_bias or self.cfg.platformer_mode else None
        )
        
        self.prev_frame_for_scene: Optional[np.ndarray] = None
        self.scene_change_enabled = self.cfg.scene_change_threshold > 0.0
        self.frames_since_scene_change: int = 0
        
        self.roi_history: Deque[Tuple[float, Tuple[int, int, int, int]]] = collections.deque()
        self.roi_history_max_len: int = max(1, int(self.fps * max(0.0, self.cfg.roi_history_window_s)))
        self.roi_history_enabled: bool = self.cfg.roi_history_window_s > 0.0
        
        self.prev_roi_cx: Optional[float] = None
        self.prev_roi_cy: Optional[float] = None
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
        """Apply face clipping based on the configured scene profile."""
        if raw_roi is None:
            return None

        clip_mode = getattr(self.cfg, "face_clip_mode", "auto")
        if clip_mode == "none" or (not self.face_priority_mode and clip_mode == "auto"):
            return raw_roi

        rx, ry, rw, rh = raw_roi
        aspect = rh / max(1, rw)

        if clip_mode == "auto":
            clip_mode = "closeup" if aspect <= 1.4 else "full_body_head"

        if clip_mode == "closeup":
            hair_skip = int(rh * 0.25)
            face_h    = max(8, int(rh * 0.35))
            return BoundingBox(rx, ry + hair_skip, rw, face_h)

        if clip_mode == "full_body_head":
            eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
            head_frac = 0.10
            
            if hasattr(self.cfg, "scene_profile") and self.cfg.scene_profile is not None:
                if getattr(self.cfg.scene_profile, "face_eye_offset", None) is not None:
                    eye_target_pct = self.cfg.scene_profile.face_eye_offset
                if getattr(self.cfg.scene_profile, "face_head_frac", None) is not None:
                    head_frac = self.cfg.scene_profile.face_head_frac
            
            roi_h   = max(8, int(rh * head_frac))
            roi_top = max(0, int(rh * eye_target_pct - roi_h / 2.0))
            return BoundingBox(rx, ry + roi_top, rw, roi_h)

        return raw_roi
