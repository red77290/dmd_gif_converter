import collections
import os
from typing import Deque, Tuple, Optional
import numpy as np
import cv2

from .config import AutoActionConfig
from .detector import _FrameDetector, DetectorFactory
from .camera import _build_camera_rect, _apply_look_ahead
from .analysis import (
    _FloorEstimator,
    _compute_scene_change_score,
    _calculate_dmd_visibility_score,
    _calculate_dmd_readability_score,
)
from .interfaces import ITracker, BoundingBox, CamRect
from .renderer import Renderer  # Used for crop_frame_static in scoring


class TrackingEngine(ITracker):
    """Stateful engine that handles target tracking across frames."""
    
    def __init__(self, fps: float, frame_w: int, frame_h: int, 
                 effective_frame_top: int, effective_frame_h: int, 
                 face_priority_mode: bool, cfg: AutoActionConfig):
        self.fps = fps
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.effective_frame_top = effective_frame_top
        self.effective_frame_h = effective_frame_h
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

        self._cam_full_view: CamRect = _build_camera_rect(
            self.frame_w, self.cam_frame_h, None, self.cfg,
            frame_top=self.cam_frame_top
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
            sim = _compute_scene_change_score(self.prev_frame_for_scene, frame)
            if sim < (1.0 - self.cfg.scene_change_threshold):
                self.roi_history.clear()
                cam_prev = self._cam_full_view
                if self.floor_est is not None:
                    self.floor_est = _FloorEstimator(self.cam_frame_h)
                self.prev_roi_cx = None
                self.prev_roi_cy = None
        self.prev_frame_for_scene = frame
        
        # 2. ROI Detection
        roi = None
        if self.face_priority_mode:
            roi = self.detector.detect(
                frame, self.cfg.detector,
                multi_fusion=self.cfg.multi_roi_fusion_enabled and not self.cfg.platformer_mode,
                min_conf=self.cfg.roi_confidence_min,
                roi_persistence_score=self.roi_persistence_score if getattr(self.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=self.cfg.platformer_mode
            )
            if roi is not None:
                rx, ry, rw, rh = roi
                _face_h = max(8, int(rh * 0.28))
                roi = (rx, ry, rw, _face_h)
        else:
            detect_frame = frame[self.effective_frame_top:self.effective_frame_h, :]
            roi = self.detector.detect(
                detect_frame, self.cfg.detector,
                multi_fusion=self.cfg.multi_roi_fusion_enabled and not self.cfg.platformer_mode,
                min_conf=self.cfg.roi_confidence_min,
                roi_persistence_score=self.roi_persistence_score if getattr(self.cfg, 'dynamic_roi_confidence_enabled', True) else 1.0,
                platformer_mode=self.cfg.platformer_mode
            )
            if roi is not None and self.effective_frame_top > 0:
                rx, ry, rw, rh = roi
                roi = (rx, ry + self.effective_frame_top, rw, rh)

        # 3. Persistence Update
        if getattr(self.cfg, 'roi_persistence_score_enabled', True):
            if roi is not None:
                self.roi_persistence_frames = min(120, self.roi_persistence_frames + 1)
            else:
                self.roi_persistence_frames = max(0, self.roi_persistence_frames - 2)
            self.roi_persistence_score = min(1.0, self.roi_persistence_frames / 60.0)
        else:
            self.roi_persistence_score = 1.0

        # 4. Micro-detection Rejection
        if roi is not None and self.cfg.min_roi_area_ratio > 0.0:
            roi_area = roi[2] * roi[3]
            frame_area = self.frame_w * self.frame_h
            if frame_area > 0 and (roi_area / frame_area) < self.cfg.min_roi_area_ratio:
                roi = None

        # 5. Minimum Useful Size Rejection
        cx, cy_center, crop_w_full, crop_h_src = self._cam_full_view
        if roi is not None and self.cfg.min_subject_dmd_px > 0:
            _dmd_scale = out_w / float(crop_w_full)
            dmd_w = roi[2] * _dmd_scale
            dmd_h = roi[3] * _dmd_scale
            if dmd_w < self.cfg.min_subject_dmd_px and dmd_h < self.cfg.min_subject_dmd_px:
                roi = None

        # 6. Floor Estimation
        floor_y_est: Optional[float] = None
        if self.floor_est is not None:
            roi_bottom = float(roi[1] + roi[3]) if roi is not None else None
            floor_y_est = self.floor_est.update(roi_bottom)

        # 7. Temporal History Synthesis
        if self.roi_history_enabled:
            if roi is not None:
                self.roi_history.append((1.0, roi))
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
                    roi = (int(wx / total_w), int(wy / total_w), int(ww / total_w), int(wh / total_w))

        # 8. Build Base Camera
        cam_now_proposed = _build_camera_rect(
            self.frame_w, self.cam_frame_h, roi, self.cfg,
            floor_y_est=floor_y_est, frame_top=self.cam_frame_top
        )

        # 9. Score Validation Loop
        cam_now = cam_now_proposed
        if self.cfg.dmd_visibility_score_enabled or getattr(self.cfg, 'dmd_readability_score_enabled', True):
            def get_sub_rect(c_rect, r_roi):
                if r_roi is None: return None
                cx, cy, cw, ch = c_rect
                sx = r_roi[0] - (cx - cw/2.0)
                sy = r_roi[1] - (cy - ch/2.0)
                _scale = out_w / cw if cw > 0 else 1.0
                return (int(sx*_scale), int(sy*_scale), int(r_roi[2]*_scale), int(r_roi[3]*_scale))

            sub_rect_prev = get_sub_rect(cam_prev, roi)
            sub_rect_prop = get_sub_rect(cam_now_proposed, roi)

            cropped_prev = Renderer.crop_frame_static(frame, cam_prev)
            dmd_prev_frame = cv2.resize(cropped_prev, (self.cfg.target_width, self.cfg.target_height), interpolation=cv2.INTER_LANCZOS4)
            vis_prev = _calculate_dmd_visibility_score(dmd_prev_frame, sub_rect_prev) if self.cfg.dmd_visibility_score_enabled else 1.0
            read_prev = _calculate_dmd_readability_score(dmd_prev_frame) if getattr(self.cfg, 'dmd_readability_score_enabled', True) else 1.0

            cropped_proposed = Renderer.crop_frame_static(frame, cam_now_proposed)
            dmd_proposed_frame = cv2.resize(cropped_proposed, (self.cfg.target_width, self.cfg.target_height), interpolation=cv2.INTER_LANCZOS4)
            vis_proposed = _calculate_dmd_visibility_score(dmd_proposed_frame, sub_rect_prop) if self.cfg.dmd_visibility_score_enabled else 1.0
            read_proposed = _calculate_dmd_readability_score(dmd_proposed_frame) if getattr(self.cfg, 'dmd_readability_score_enabled', True) else 1.0

            if self.cfg.dmd_visibility_score_enabled and getattr(self.cfg, 'dmd_readability_score_enabled', True):
                score_prev = vis_prev * 0.5 + read_prev * 0.5
                score_proposed = vis_proposed * 0.5 + read_proposed * 0.5
            elif getattr(self.cfg, 'dmd_readability_score_enabled', True):
                score_prev = read_prev
                score_proposed = read_proposed
            else:
                score_prev = vis_prev
                score_proposed = vis_proposed

            if score_proposed < score_prev * 0.95:
                cam_now = (cam_now_proposed[0], cam_now_proposed[1], cam_prev[2], cam_prev[3])

            if getattr(self.cfg, 'auto_tuning_dataset_dir', None) is not None:
                _ds_dir = self.cfg.auto_tuning_dataset_dir
                os.makedirs(_ds_dir, exist_ok=True)
                cv2.imwrite(os.path.join(_ds_dir, f"frame_{src_idx:04d}_dmd.png"), dmd_proposed_frame)
                with open(os.path.join(_ds_dir, "scores.csv"), "a") as f:
                    f.write(f"{src_idx},{vis_proposed:.3f},{read_proposed:.3f},{self.roi_persistence_score:.3f}\n")

        # 10. Look-Ahead and Momentum
        curr_roi_cx: Optional[float] = None
        curr_roi_cy: Optional[float] = None
        if roi is not None:
            curr_roi_cx = float(roi[0] + roi[2] / 2.0)
            curr_roi_cy = float(roi[1] + roi[3] / 2.0)
            
        live_vx, live_vy = 0.0, 0.0
        if curr_roi_cx is not None and self.prev_roi_cx is not None:
            live_vx = curr_roi_cx - self.prev_roi_cx
            live_vy = curr_roi_cy - self.prev_roi_cy
            
        if getattr(self.cfg, "scroll_direction_memory_enabled", True):
            if roi is not None:
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
            )
            
        self.prev_roi_cx = curr_roi_cx
        self.prev_roi_cy = curr_roi_cy
        
        self._last_roi = roi  # Store for vignette
        return cam_now
