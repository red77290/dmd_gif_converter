import collections
import os
from typing import Deque, Tuple, Optional
import numpy as np
import cv2

from src.engine.scoring.dmd_readability_engine import DmdReadabilityEngine

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
from src.engine.auto_action.renderer import Renderer  # Used for crop_frame_static in scoring


class TrackingEngine(ITracker):
    """Stateful engine that handles target tracking across frames."""
    
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
        self.face_priority_mode = face_priority_mode
        self.cfg = cfg
        
        self.detector = DetectorFactory.create()

        # Camera Bounds
        if self.face_priority_mode:
            self.cam_frame_h = self.frame_h
            self.cam_frame_top = 0.0
        else:
            self.cam_frame_h = self.effective_frame_h
            self.cam_frame_top = float(self.effective_frame_top)

        # DMD Readability Evaluator (replaces legacy DMDVisibilityScore/DMDReadabilityScore)
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
        
        # Floor Estimator
        self.floor_est: Optional[_FloorEstimator] = (
            _FloorEstimator(self.cam_frame_h) 
            if self.cfg.auto_vertical_bias or self.cfg.platformer_mode else None
        )
        
        # Scene Change
        self.prev_frame_for_scene: Optional[np.ndarray] = None
        self.scene_change_enabled = self.cfg.scene_change_threshold > 0.0
        self.frames_since_scene_change: int = 0
        
        # ROI History
        self.roi_history: Deque[Tuple[float, Tuple[int, int, int, int]]] = collections.deque()
        self.roi_history_max_len: int = max(1, int(self.fps * max(0.0, self.cfg.roi_history_window_s)))
        self.roi_history_enabled: bool = self.cfg.roi_history_window_s > 0.0
        
        # Look-Ahead & Scroll Memory
        self.prev_roi_cx: Optional[float] = None
        self.prev_roi_cy: Optional[float] = None
        self.scroll_vx: float = 0.0
        self.scroll_vy: float = 0.0
        self.scroll_memory_frames: int = 0
        
        # Persistence Score
        self.roi_persistence_frames: int = 0
        self.roi_persistence_score: float = 1.0
        
        # Detector state
        self.current_detector: str = self.cfg.detector

    @property
    def last_roi(self) -> Optional[BoundingBox]:
        return self._last_roi

    @property
    def cam_full_view(self) -> CamRect:
        return self._cam_full_view

    def process_frame(self, frame: np.ndarray, cam_prev: CamRect, src_idx: int, out_w: int, out_h: int) -> CamRect:
        """Processes a single frame, updates internal state, and returns the next proposed un-smoothed camera."""
        # 1. Scene Change Detection
        if self.scene_change_enabled and self.prev_frame_for_scene is not None:
            sim = SceneChangeScore.compute(self.prev_frame_for_scene, frame)
            if sim < (1.0 - self.cfg.scene_change_threshold):
                self.roi_history.clear()
                cam_prev = self._cam_full_view
                if self.floor_est is not None:
                    self.floor_est = _FloorEstimator(self.cam_frame_h)
                self.prev_roi_cx = None
                self.prev_roi_cy = None
                self.frames_since_scene_change = 0
                
                # Reset dynamic profile temporarily on cut
                if getattr(self.cfg, "dynamic_scene_detection", False):
                    from src.engine.analysis.scene_types import DEFAULT_SCENE_PROFILE
                    self.cfg.scene_profile = DEFAULT_SCENE_PROFILE
                    self.cfg.scene_type = DEFAULT_SCENE_PROFILE.scene_type
                    
                # Reset dynamic detector on cut
                if getattr(self.cfg, "auto_detector_fallback", False):
                    self.current_detector = "person"

        self.prev_frame_for_scene = frame
        self.frames_since_scene_change += 1
        
        # 2. ROI Detection  (raw bbox from detector, before any face-clipping)
        expected_floor_y = self.floor_est.floor_y if self.floor_est is not None else None
        
        if self.face_priority_mode:
            raw_roi = self.detector.detect(
                frame, self.current_detector,
                multi_fusion=self.cfg.multi_roi_fusion_enabled and not self.cfg.platformer_mode,
                min_conf=self.cfg.roi_confidence_min,
                roi_persistence_score=self.roi_persistence_score if getattr(self.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=self.cfg.platformer_mode,
                expected_floor_y=expected_floor_y
            )
        else:
            detect_frame = frame[self.effective_frame_top:self.effective_frame_h, :]
            raw_roi = self.detector.detect(
                detect_frame, self.current_detector,
                multi_fusion=self.cfg.multi_roi_fusion_enabled and not self.cfg.platformer_mode,
                min_conf=self.cfg.roi_confidence_min,
                roi_persistence_score=self.roi_persistence_score if getattr(self.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=self.cfg.platformer_mode,
                expected_floor_y=expected_floor_y - self.effective_frame_top if expected_floor_y is not None else None
            )
            if raw_roi is not None and self.effective_frame_top > 0:
                rx, ry, rw, rh = raw_roi
                raw_roi = (rx, ry + self.effective_frame_top, rw, rh)

        # 3. Persistence Update  (based on the raw detection, before size filters)
        if getattr(self.cfg, 'roi_persistence_score_enabled', True):
            if raw_roi is not None:
                self.roi_persistence_frames = min(120, self.roi_persistence_frames + 1)
            else:
                self.roi_persistence_frames = max(0, self.roi_persistence_frames - 2)
            self.roi_persistence_score = min(1.0, self.roi_persistence_frames / 60.0)
        else:
            self.roi_persistence_score = 1.0

        # 4. Micro-detection Rejection  (use raw bbox so face-clipping cannot shrink
        #    the roi below the threshold for a legitimate full-body detection)
        if raw_roi is not None and self.cfg.min_roi_area_ratio > 0.0:
            check_roi = raw_roi  # always compare against the original detection
            roi_area = check_roi[2] * check_roi[3]
            frame_area = self.frame_w * self.frame_h
            if frame_area > 0 and (roi_area / frame_area) < self.cfg.min_roi_area_ratio:
                raw_roi = None

        # 5. Minimum Useful Size Rejection  (same: compare raw detection to threshold)
        cx, cy_center, crop_w_full, crop_h_src = self._cam_full_view
        if raw_roi is not None and self.cfg.min_subject_dmd_px > 0:
            _dmd_scale = out_w / float(crop_w_full)
            dmd_w = raw_roi[2] * _dmd_scale
            dmd_h = raw_roi[3] * _dmd_scale
            if dmd_w < self.cfg.min_subject_dmd_px and dmd_h < self.cfg.min_subject_dmd_px:
                raw_roi = None

        # 2b. Face-region clipping (after size validation so filters use raw bbox).
        # Determine the clipped ROI used EXCLUSIVELY for camera framing.
        face_roi = self._clip_to_face_roi(raw_roi)

        # 6. Floor Estimation (uses original unclipped roi)
        floor_y_est: Optional[float] = None
        if self.floor_est is not None:
            roi_bottom = None
            if raw_roi is not None:
                rx, ry, rw, rh = raw_roi
                self._platformer = getattr(self.cfg, "platformer_mode", False)
                if self._platformer:
                    # Cap perceived character height to prevent thick scrolling ground 
                    # from pulling the floor estimate down
                    max_char_h = self.effective_frame_h * 0.25
                    effective_rh = min(float(rh), max_char_h)
                    roi_bottom = ry + effective_rh
                else:
                    roi_bottom = float(ry + rh)
            floor_y_est = self.floor_est.update(roi_bottom)

        # 7. Temporal History Synthesis (uses original unclipped roi)
        if self.roi_history_enabled:
            if raw_roi is not None:
                self.roi_history.append((1.0, raw_roi))
                while len(self.roi_history) > self.roi_history_max_len:
                    self.roi_history.popleft()
            elif self.roi_history:
                n = len(self.roi_history)
                total_w = 0.0
                wx, wy, ww, wh = 0.0, 0.0, 0.0, 0.0
                for idx, (_, hr) in enumerate(self.roi_history):
                    w = float(idx + 1)
                    total_w += w
                    wx += w * hr[0]
                    wy += w * hr[1]
                    ww += w * hr[2]
                    wh += w * hr[3]
                if total_w > 0:
                    raw_roi = (int(wx / total_w), int(wy / total_w), int(ww / total_w), int(wh / total_w))
                    face_roi = self._clip_to_face_roi(raw_roi)

        # 7b. Dynamic Scene Classification (on-the-fly per shot)
        if getattr(self.cfg, "dynamic_scene_detection", False):
            # We wait a few frames after a cut to gather enough ROI history
            wait_frames = min(15, max(5, self.roi_history_max_len))
            if self.frames_since_scene_change == wait_frames and len(self.roi_history) > 3:
                from src.engine.analysis.scene_types import classify_scene
                
                arr_widths = []
                x_centers = []
                y_centers = []
                fill_ratios = []
                heights = []
                
                for _, hr in self.roi_history:
                    arr_widths.append(hr[2])
                    heights.append(hr[3])
                    x_centers.append(hr[0] + hr[2]/2.0)
                    y_centers.append(hr[1] + hr[3]/2.0)
                    fill_ratios.append(hr[3] / float(self.frame_h))
                    
                median_h = float(np.median(heights))
                median_w = float(np.median(arr_widths))
                
                floor_in_lower = False
                if self.floor_est and self.floor_est.floor_y and self.floor_est.floor_y > (self.cam_frame_h * 0.5):
                    floor_in_lower = True
                
                scene_signals = {
                    "tall_ratio":      median_h / float(self.cam_frame_h) if self.cam_frame_h > 0 else 0.0,
                    "fill_ratio":      float(np.median(fill_ratios)),
                    "body_aspect":     median_h / max(1.0, median_w),
                    "floor_in_lower":  floor_in_lower,
                    "floor_var_score": 1.0, # Hard to compute accurate variance with short history, assume unstable unless floor_est locked
                    "x_variance":      float(np.var(x_centers)) / max(1.0, float(self.frame_w)**2),
                    "y_variance":      float(np.var(y_centers)) / max(1.0, float(self.cam_frame_h)**2),
                }
                
                new_profile, _ = classify_scene(scene_signals)
                self.cfg.scene_profile = new_profile
                self.cfg.scene_type = new_profile.scene_type

        # 7c. Dynamic Detector Fallback (on-the-fly per shot)
        if getattr(self.cfg, "auto_detector_fallback", False):
            wait_frames = min(15, max(5, self.roi_history_max_len))
            if self.frames_since_scene_change == wait_frames and len(self.roi_history) == 0:
                if self.current_detector == "person":
                    self.current_detector = "hybrid"

        # 8. Build Base Camera (uses face_roi for positioning)
        cam_now_proposed = _build_camera_rect(
            self.frame_w, self.cam_frame_h, face_roi, self.cfg,
            floor_y_est=floor_y_est, frame_top=self.cam_frame_top,
            face_priority_mode=self.face_priority_mode,
            effective_frame_left=self.effective_frame_left,
            effective_frame_w=self.effective_frame_w,
            effective_frame_top=float(self.effective_frame_top),
            effective_frame_h=self.effective_frame_h
        )

        # 9. Score Validation Loop
        cam_now = cam_now_proposed
        if self.cfg.dmd_visibility_score_enabled or getattr(self.cfg, 'dmd_readability_score_enabled', True):
            # We use DmdReadabilityEngine to evaluate the predicted readability
            # of the frame if cropped to cam_prev vs cam_now_proposed.
            read_prev_score = self.readability_engine.evaluate(frame, roi=cam_prev).overall / 100.0
            read_prop_score = self.readability_engine.evaluate(frame, roi=cam_now_proposed).overall / 100.0

            # Provide a slight momentum bonus to the previous camera position to avoid jitter
            if read_prop_score < read_prev_score * 0.95:
                # Proposed camera framing is significantly less readable than the previous one.
                # Hold the previous camera size/position but track the new subject if possible.
                # (Keep previous width/height, but use proposed x/y if it fits).
                # For simplicity, we just reject the new size.
                cam_now = (cam_now_proposed[0], cam_now_proposed[1], cam_prev[2], cam_prev[3])

            if getattr(self.cfg, 'auto_tuning_dataset_dir', None) is not None:
                _ds_dir = self.cfg.auto_tuning_dataset_dir
                os.makedirs(_ds_dir, exist_ok=True)
                cropped_proposed = Renderer.crop_frame_static(frame, cam_now)
                dmd_proposed_frame = cv2.resize(cropped_proposed, (self.cfg.target_width, self.cfg.target_height), interpolation=cv2.INTER_LANCZOS4)
                cv2.imwrite(os.path.join(_ds_dir, f"frame_{src_idx:04d}_dmd.png"), dmd_proposed_frame)
                with open(os.path.join(_ds_dir, "scores.csv"), "a") as f:
                    f.write(f"{src_idx},{read_prop_score:.3f},{read_prop_score:.3f},{self.roi_persistence_score:.3f}\n")

        # 10. Look-Ahead and Momentum (uses original unclipped roi)
        curr_roi_cx: Optional[float] = None
        curr_roi_cy: Optional[float] = None
        if raw_roi is not None:
            curr_roi_cx = float(raw_roi[0] + raw_roi[2] / 2.0)
            curr_roi_cy = float(raw_roi[1] + raw_roi[3] / 2.0)
            
        live_vx, live_vy = 0.0, 0.0
        if curr_roi_cx is not None and self.prev_roi_cx is not None:
            live_vx = curr_roi_cx - self.prev_roi_cx
            live_vy = curr_roi_cy - self.prev_roi_cy
            
        if getattr(self.cfg, "scroll_direction_memory_enabled", True):
            if raw_roi is not None:
                self.scroll_vx = 0.9 * self.scroll_vx + 0.1 * live_vx
                self.scroll_vy = 0.9 * self.scroll_vy + 0.1 * live_vy
                self.scroll_memory_frames = min(60, self.scroll_memory_frames + 1)
            else:
                self.scroll_memory_frames = max(0, self.scroll_memory_frames - 1)
                if self.scroll_memory_frames == 0:
                    self.scroll_vx *= 0.9
                    self.scroll_vy *= 0.9
        else:
            self.scroll_vx, self.scroll_vy = live_vx, live_vy

        if self.cfg.look_ahead_enabled and self.cfg.look_ahead_factor > 0.0:
            cam_now = _apply_look_ahead(
                cam_now,
                self.scroll_vx, self.scroll_vy,
                self.frame_w, self.frame_h,
                self.cfg.look_ahead_factor,
                roi_persistence=self.roi_persistence_score,
                effective_frame_left=self.effective_frame_left,
                effective_frame_w=self.effective_frame_w,
            )
            
        self.prev_roi_cx = curr_roi_cx
        self.prev_roi_cy = curr_roi_cy
        
        self._last_roi = raw_roi  # Store for vignette
        return cam_now

    def _clip_to_face_roi(self, raw_roi: Optional[BoundingBox]) -> Optional[BoundingBox]:
        """Apply face clipping based on the configured scene profile."""
        if raw_roi is None:
            return None

        # Fallback if config has no face_clip_mode but face_priority_mode is enabled
        clip_mode = getattr(self.cfg, "face_clip_mode", "auto")
        if clip_mode == "none" or (not self.face_priority_mode and clip_mode == "auto"):
            return raw_roi

        rx, ry, rw, rh = raw_roi
        aspect = rh / max(1, rw)

        # "auto" uses aspect ratio to choose between close-up and full body
        if clip_mode == "auto":
            clip_mode = "closeup" if aspect <= 1.4 else "full_body_head"

        if clip_mode == "closeup":
            # Face / head close-up — bbox IS the face.
            # Skip top 25 % (hair) and keep eye region (35 %).
            hair_skip = int(rh * 0.25)
            face_h    = max(8, int(rh * 0.35))
            return (rx, ry + hair_skip, rw, face_h)

        if clip_mode == "full_body_head":
            # Adaptive eye targeting using aspect-ratio formula
            eye_target_pct = min(0.22, max(0.08, 0.32 / (aspect + 0.6)))
            head_frac = 0.10  # default 10% of body height
            
            if hasattr(self.cfg, "scene_profile") and self.cfg.scene_profile is not None:
                if getattr(self.cfg.scene_profile, "face_eye_offset", None) is not None:
                    eye_target_pct = self.cfg.scene_profile.face_eye_offset
                if getattr(self.cfg.scene_profile, "face_head_frac", None) is not None:
                    head_frac = self.cfg.scene_profile.face_head_frac
            
            roi_h   = max(8, int(rh * head_frac))
            roi_top = max(0, int(rh * eye_target_pct - roi_h / 2.0))
            return (rx, ry + roi_top, rw, roi_h)

        return raw_roi

