from typing import Optional, Tuple
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.analysis.analysis import _clamp

def _build_camera_rect(frame_w: int, frame_h: int, roi, cfg: AutoActionConfig,
                       floor_y_est: Optional[float] = None,
                       frame_top: float = 0.0,
                       face_priority_mode: bool = False,
                       effective_frame_left: int = 0,
                       effective_frame_w: Optional[int] = None,
                       effective_frame_top: float = 0.0,
                       effective_frame_h: Optional[int] = None):
    if effective_frame_w is None:
        effective_frame_w = frame_w
    if effective_frame_h is None:
        effective_frame_h = frame_h
    target_ratio = float(cfg.target_width) / cfg.target_height
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
        return max(crop_h / 2.0, frame_top + crop_h / 2.0)

    def _cy_max(crop_h: float) -> float:
        return float(frame_h) - crop_h / 2.0

    def _apply_bias(cy: float, crop_h: float) -> float:
        if abs(_bias) < 1e-4:
            return cy
        target_cy = _cy_max(crop_h) if _bias > 0 else _cy_min(crop_h)
        cy = cy + abs(_bias) * (target_cy - cy)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    def _apply_auto_floor(cy: float, floor_y: float, crop_h: float) -> float:
        cy = floor_y + crop_h * (0.5 - _FLOOR_RATIO)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    if roi is None:
        cx = effective_frame_left + effective_frame_w / 2.0
        cy = (frame_top + frame_h) / 2.0
        crop_w = float(effective_frame_w)
        crop_h = float(frame_w) / target_ratio
        cy = _apply_bias(cy, crop_h)
        return cx, cy, crop_w, crop_h

    x, y, w, h = roi

    # A small headroom above the roi top so the subject's head is not clipped.
    hair_headroom = h * 0.05
    ideal_top = max(0.0, y - hair_headroom)
    total_h = h + (y - ideal_top)
    cx = x + w / 2.0
    # cy starts at the centre of the roi (tracker already clipped to eye region
    # for close-ups in face_priority_mode, or to the head for normal shots).
    cy = y + h / 2.0

    # Calculate the ideal crop that perfectly frames the subject + headroom + padding
    ideal_crop_h = total_h * (1.0 + cfg.padding)
    
    if _auto or _platformer:
        # Prevent the camera from abandoning the floor tracking by ensuring crop_h is large enough
        # to fit both the character's full height AND the space reserved for the floor.
        # We need total_h to fit between the top padding (5%) and the floor (_FLOOR_RATIO).
        required_h = total_h / max(0.1, _FLOOR_RATIO - 0.05)
        ideal_crop_h = max(ideal_crop_h, required_h)
        
    ideal_crop_w = ideal_crop_h * target_ratio
    
    if ideal_crop_w < w * (1.0 + cfg.padding):
        ideal_crop_w = w * (1.0 + cfg.padding)
        ideal_crop_h = ideal_crop_w / target_ratio

    tight_w = ideal_crop_w
    loose_w = float(effective_frame_w)
    
    strength = _clamp(cfg.strength, 0.0, 1.0)
    # strength=1.0 -> tight framing. strength=0.0 -> loose framing (show context)
    crop_w = loose_w - strength * (loose_w - tight_w)

    # Enforce zoom_max (maximum zoom-in from full frame)
    current_zoom_max = getattr(cfg, "zoom_max", 1.8)
    if hasattr(cfg, "scene_profile") and cfg.scene_profile is not None:
        if cfg.scene_profile.max_zoom_override is not None:
            current_zoom_max = cfg.scene_profile.max_zoom_override

    min_allowed_w = loose_w / max(1.0, current_zoom_max)
    crop_w = max(crop_w, min_allowed_w)
    
    # Ensure we never crop tighter than the person's required bounding box
    crop_w = max(crop_w, tight_w)

    if _platformer:
        crop_w = min(float(effective_frame_w), crop_w * 1.5)

    # Prevent zooming out beyond the frame dimensions (avoid black bars)
    if crop_w > effective_frame_w:
        crop_w = float(effective_frame_w)

    crop_h = crop_w / target_ratio

    if crop_h > frame_h:
        crop_h = float(frame_h)
        crop_w = crop_h * target_ratio

    if face_priority_mode:
        # Centre the camera on the roi centre (y + h/2).
        # The tracker already clips the roi to the eye/face region for close-ups,
        # so y + h/2 targets the eyes rather than the top of the head.
        cy = y + h / 2.0
    elif _auto or _platformer:
        fy = floor_y_est if floor_y_est is not None else float(y + h)
        cy_floor = _apply_auto_floor(cy, fy, crop_h)
        
        # Keep head+hair visible over floor, even in platformer mode.
        # If the sprite is larger than the screen, prioritize the top of the character.
        if (cy_floor - crop_h / 2.0) > ideal_top:
            # If the bounding box is huge, it's likely tracking a flying platform/enemy
            # far above the character. In a platformer, we should NOT let this pull
            # the camera up and lose the floor.
            if _platformer and total_h > crop_h * 0.8:
                cy = cy_floor
            else:
                cy = ideal_top + crop_h / 2.0
        else:
            cy = cy_floor
    else:
        # Standard generic tracking (e.g. top-down games like Zelda).
        # Simply apply vertical bias. We do NOT force pin the camera to the top of the bounding box,
        # as a large motion bounding box (e.g. screen scrolling) would snap the camera to the HUD/ceiling.
        cy = _apply_bias(cy, crop_h)

    if crop_w >= effective_frame_w:
        cx = effective_frame_left + effective_frame_w / 2.0
    else:
        cx = _clamp(cx, effective_frame_left + crop_w / 2.0, effective_frame_left + float(effective_frame_w) - crop_w / 2.0)

    cy = _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))
    

    return cx, cy, crop_w, crop_h


def _smooth(prev, curr, smoothness: float):
    if prev is None:
        return curr
    a = _clamp(smoothness, 0.0, 0.98)
    return tuple((a * p) + ((1.0 - a) * c) for p, c in zip(prev, curr))


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

    return (cx, cy, cw, ch)
