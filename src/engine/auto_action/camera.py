from typing import Optional, Tuple
from src.engine.auto_action.interfaces import CamRect, BoundingBox
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.analysis.analysis import _clamp

def _compute_base_crop_dimensions(eff_w: float, eff_h: float, target_ratio: float) -> Tuple[float, float]:
    """Compute maximum crop window dimensions fitting within effective frame bounds for any aspect ratio."""
    if eff_h <= 0 or target_ratio <= 0:
        return max(1.0, eff_w), max(1.0, eff_h)
    
    if (eff_w / eff_h) >= target_ratio:
        # Height-limited (portrait or narrow target on wide source)
        crop_h = float(eff_h)
        crop_w = crop_h * target_ratio
    else:
        # Width-limited (landscape target on standard source)
        crop_w = float(eff_w)
        crop_h = crop_w / target_ratio
        
    if crop_w > eff_w:
        crop_w = float(eff_w)
        crop_h = crop_w / target_ratio
    if crop_h > eff_h:
        crop_h = float(eff_h)
        crop_w = crop_h * target_ratio
        
    return crop_w, crop_h


def _build_camera_rect(frame_w: int, frame_h: int, roi, cfg: AutoActionConfig,
                       floor_y_est: Optional[float] = None,
                       frame_top: float = 0.0,
                       face_priority_mode: bool = False,
                       effective_frame_left: int = 0,
                       effective_frame_w: Optional[int] = None,
                       effective_frame_top: float = 0.0,
                       effective_frame_h: Optional[int] = None,
                       locked_crop_size: Optional[Tuple[float, float]] = None):
    if effective_frame_top == 0.0 and frame_top != 0.0:
        effective_frame_top = frame_top
    if effective_frame_w is None:
        effective_frame_w = frame_w
    if effective_frame_h is None:
        effective_frame_h = max(1, frame_h - int(effective_frame_top))
    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    _bias = _clamp(getattr(cfg, "vertical_bias", 0.0), -1.0, 1.0)
    _auto = getattr(cfg, "auto_vertical_bias", False)
    _platformer = getattr(cfg, "platformer_mode", False)

    # Force bias for intro frame (roi=None) depending on tracking mode
    if roi is None:
        if _auto and abs(_bias) < 1e-4:
            _bias = -1.0  # person smart pushes up to ensure head is visible
        elif _platformer and abs(_bias) < 1e-4:
            _bias = 1.0   # platformer pushes down to ensure floor is visible

    _FLOOR_RATIO: float = getattr(cfg, "platformer_floor_ratio", 0.80) if _platformer else 0.93

    def _cy_min(crop_h: float) -> float:
        return effective_frame_top + crop_h / 2.0

    def _cy_max(crop_h: float) -> float:
        return effective_frame_top + float(effective_frame_h) - crop_h / 2.0

    def _apply_bias(cy: float, crop_h: float) -> float:
        if abs(_bias) < 1e-4:
            return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))
        target_cy = _cy_max(crop_h) if _bias > 0 else _cy_min(crop_h)
        cy = cy + abs(_bias) * (target_cy - cy)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    def _apply_auto_floor(cy: float, floor_y: float, crop_h: float) -> float:
        cy = floor_y + crop_h * (0.5 - _FLOOR_RATIO)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    # Base full-frame maximum bounding window for this aspect ratio
    max_w, max_h = _compute_base_crop_dimensions(float(effective_frame_w), float(effective_frame_h), target_ratio)

    if locked_crop_size is not None:
        crop_w, crop_h = locked_crop_size
        crop_w = min(crop_w, float(effective_frame_w))
        crop_h = min(crop_h, float(effective_frame_h))
    else:
        # DMD Invariant: Never zoom in on the action. The camera crop dimensions strictly
        # match the maximum bounding window fitting the target aspect ratio.
        crop_w = max_w
        crop_h = max_h


    if roi is None:
        cx = effective_frame_left + effective_frame_w / 2.0
        cy = effective_frame_top + effective_frame_h / 2.0
        cy = _apply_bias(cy, crop_h)
        return CamRect(cx, cy, crop_w, crop_h)

    x, y, w, h = roi
    hair_headroom = h * 0.05
    ideal_top = max(0.0, y - hair_headroom)
    total_h = h + (y - ideal_top)
    cx = x + w / 2.0
    cy = y + h / 2.0

    if face_priority_mode:
        cy = y + h / 2.0
        cy = min(cy, y + 0.25 * crop_h)
    elif _auto or _platformer:
        fy = floor_y_est if floor_y_est is not None else float(y + h)
        cy_floor = _apply_auto_floor(cy, fy, crop_h)
        
        if (cy_floor - crop_h / 2.0) > ideal_top:
            scene_type = getattr(cfg.scene_profile, "scene_type", "") if getattr(cfg, "scene_profile", None) else ""
            if scene_type == "platformer" and total_h > crop_h * 0.8:
                cy = cy_floor
            else:
                cy = ideal_top + crop_h / 2.0
        else:
            cy = cy_floor
    else:
        cy = _apply_bias(cy, crop_h)

    if crop_w >= effective_frame_w:
        cx = effective_frame_left + effective_frame_w / 2.0
    else:
        cx = _clamp(cx, effective_frame_left + crop_w / 2.0, effective_frame_left + float(effective_frame_w) - crop_w / 2.0)

    cy = _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    return CamRect(cx, cy, crop_w, crop_h)


def _smooth(prev, curr, smoothness: float):
    if prev is None:
        return curr
    a = _clamp(smoothness, 0.0, 0.98)
    # Smooth ONLY camera translation (cx, cy). Keep camera crop dimensions (cw, ch) strictly static.
    cx = (a * prev[0]) + ((1.0 - a) * curr[0])
    cy = (a * prev[1]) + ((1.0 - a) * curr[1])
    cw = curr[2]
    ch = curr[3]
    return CamRect(cx, cy, cw, ch)


def _crop_frame(frame, cam_rect):
    import numpy as np
    h, w = frame.shape[:2]
    cx, cy, cw, ch = cam_rect

    out_w = max(1, int(round(cw)))
    out_h = max(1, int(round(ch)))

    x1 = int(round(cx - cw / 2.0))
    y1 = int(round(cy - ch / 2.0))
    x2 = x1 + out_w
    y2 = y1 + out_h

    # Create an empty black canvas
    if len(frame.shape) == 3:
        canvas = np.zeros((out_h, out_w, frame.shape[2]), dtype=frame.dtype)
    else:
        canvas = np.zeros((out_h, out_w), dtype=frame.dtype)

    # Calculate intersection between the requested crop box and the actual frame
    src_x1 = max(0, x1)
    src_y1 = max(0, y1)
    src_x2 = min(w, x2)
    src_y2 = min(h, y2)

    # If there is no overlap, return black canvas
    if src_x1 >= src_x2 or src_y1 >= src_y2:
        return canvas

    # Calculate where this intersection goes on the canvas
    dst_x1 = src_x1 - x1
    dst_y1 = src_y1 - y1
    dst_x2 = dst_x1 + (src_x2 - src_x1)
    dst_y2 = dst_y1 + (src_y2 - src_y1)

    canvas[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]

    return canvas


def _apply_look_ahead(
    cam_rect: Tuple[float, float, float, float],
    scroll_vx: float,
    scroll_vy: float,
    frame_w: int,
    frame_h: int,
    look_ahead_factor: float,
    roi_persistence: float = 1.0,
    effective_frame_left: int = 0,
    effective_frame_w: Optional[int] = None,
) -> Tuple[float, float, float, float]:
    if effective_frame_w is None:
        effective_frame_w = frame_w
        
    if look_ahead_factor <= 0.0 or (abs(scroll_vx) < 1e-3 and abs(scroll_vy) < 1e-3):
        return cam_rect

    cx, cy, cw, ch = cam_rect

    # VNext Priority 4: Adaptive Look Ahead
    # Smoothly scale offset with velocity (pixels per frame).
    # look_ahead_factor (0.0 - 1.0) determines responsiveness. We multiply by a constant
    # to project several frames ahead. Max offset is capped at 25% of crop width.
    max_offset_x = cw * 0.25
    max_offset_y = ch * 0.25
    
    # Adaptive multiplier based on speed
    speed = (scroll_vx**2 + scroll_vy**2)**0.5
    adaptive_factor = look_ahead_factor * (1.0 + min(1.5, speed / 15.0)) * roi_persistence
    
    offset_x = _clamp(scroll_vx * adaptive_factor * 5.0, -max_offset_x, max_offset_x)
    offset_y = _clamp(scroll_vy * adaptive_factor * 5.0, -max_offset_y, max_offset_y)

    if cw >= effective_frame_w:
        cx = effective_frame_left + effective_frame_w / 2.0
    else:
        cx = _clamp(cx + offset_x, effective_frame_left + cw / 2.0, effective_frame_left + float(effective_frame_w) - cw / 2.0)
        
    if ch >= frame_h:
        cy = frame_h / 2.0
    else:
        cy = _clamp(cy + offset_y, ch / 2.0, float(frame_h) - ch / 2.0)

    return CamRect(cx, cy, cw, ch)
