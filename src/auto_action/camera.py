from typing import Optional, Tuple
from .config import AutoActionConfig
from .analysis import _clamp

def _build_camera_rect(frame_w: int, frame_h: int, roi, cfg: AutoActionConfig,
                       floor_y_est: Optional[float] = None,
                       frame_top: float = 0.0):
    target_ratio = float(cfg.target_width) / cfg.target_height
    _bias = _clamp(getattr(cfg, "vertical_bias", 0.0), -1.0, 1.0)
    _auto = getattr(cfg, "auto_vertical_bias", False)
    _platformer = getattr(cfg, "platformer_mode", False)

    _FLOOR_RATIO: float = getattr(cfg, "platformer_floor_ratio", 0.80) if _platformer else 0.93

    def _cy_min(crop_h: float) -> float:
        return max(crop_h / 2.0, frame_top + crop_h / 2.0)

    def _cy_max(crop_h: float) -> float:
        return float(frame_h) - crop_h / 2.0

    def _apply_bias(cy: float, crop_h: float) -> float:
        if abs(_bias) < 1e-4:
            return cy
        target_cy = _cy_max(crop_h) if _bias > 0 else _cy_min(crop_h)
        cy = cy + _bias * (target_cy - cy)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    def _apply_auto_floor(cy: float, floor_y: float, crop_h: float) -> float:
        cy = floor_y + crop_h * (0.5 - _FLOOR_RATIO)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    if roi is None:
        cx = frame_w / 2.0
        cy = (frame_top + frame_h) / 2.0
        crop_w = float(frame_w)
        crop_h = float(frame_w) / target_ratio
        if _auto or _platformer:
            if floor_y_est is not None:
                cy = _apply_auto_floor(cy, floor_y_est, crop_h)
            else:
                cy_max = _cy_max(crop_h)
                cy = cy + 0.65 * (cy_max - cy)
                cy = _clamp(cy, _cy_min(crop_h), cy_max)
        else:
            cy = _apply_bias(cy, crop_h)
        return cx, cy, crop_w, crop_h

    x, y, w, h = roi
    cx = x + w / 2.0
    cy = y + h / 2.0

    strength = _clamp(cfg.strength, 0.0, 1.0)
    zoom = 1.0 + strength * (max(1.0, cfg.zoom_max) - 1.0)

    roi_w = max(16.0, w * (1.0 + cfg.padding))
    roi_h = max(8.0,  h * (1.0 + cfg.padding))
    if roi_w / roi_h < target_ratio:
        roi_w = roi_h * target_ratio
    else:
        roi_h = roi_w / target_ratio

    crop_w = roi_w / zoom
    crop_h = roi_h / zoom

    if _platformer:
        crop_w = min(float(frame_w), crop_w * 1.5)
        crop_h = crop_w / target_ratio


    min_crop_w = max(float(cfg.target_width) / 4,
                     float(frame_w) / max(1.0, cfg.zoom_max))
    min_crop_h = min_crop_w / target_ratio
    crop_w = max(crop_w, min_crop_w)
    crop_h = max(crop_h, min_crop_h)

    crop_w = crop_h * target_ratio
    if crop_w > float(frame_w):
        crop_w = float(frame_w)
        crop_h = float(frame_w) / target_ratio

    if _auto or _platformer:
        fy = floor_y_est if floor_y_est is not None else float(y + h)
        cy = _apply_auto_floor(cy, fy, crop_h)
    else:
        cy = _apply_bias(cy, crop_h)

    cy = _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    return cx, cy, crop_w, crop_h


def _smooth(prev, curr, smoothness: float):
    if prev is None:
        return curr
    a = _clamp(smoothness, 0.0, 0.98)
    return tuple((a * p) + ((1.0 - a) * c) for p, c in zip(prev, curr))


def _crop_frame(frame, cam_rect):
    h, w = frame.shape[:2]
    cx, cy, cw, ch = cam_rect

    out_w = max(1, int(round(cw)))
    out_h = max(1, int(round(ch)))

    x1 = int(round(cx - cw / 2.0))
    y1 = int(round(cy - ch / 2.0))

    if x1 + out_w > w:
        x1 = w - out_w
    if x1 < 0:
        x1 = 0
    if y1 + out_h > h:
        y1 = h - out_h
    if y1 < 0:
        y1 = 0

    x2 = x1 + out_w
    y2 = y1 + out_h

    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return frame
    return frame[y1:y2, x1:x2]


def _apply_look_ahead(
    cam_rect: Tuple[float, float, float, float],
    prev_roi_cx: Optional[float],
    curr_roi_cx: Optional[float],
    prev_roi_cy: Optional[float],
    curr_roi_cy: Optional[float],
    frame_w: int,
    frame_h: int,
    look_ahead_factor: float,
) -> Tuple[float, float, float, float]:
    if look_ahead_factor <= 0.0 or prev_roi_cx is None or curr_roi_cx is None:
        return cam_rect

    cx, cy, cw, ch = cam_rect

    vx = curr_roi_cx - prev_roi_cx
    vy = (curr_roi_cy - prev_roi_cy) if (prev_roi_cy is not None and curr_roi_cy is not None) else 0.0

    # Smoothly scale offset with velocity (pixels per frame).
    # look_ahead_factor (0.0 - 1.0) determines responsiveness. We multiply by a constant
    # to project several frames ahead. Max offset is capped at 25% of crop width.
    max_offset_x = cw * 0.25
    max_offset_y = ch * 0.25
    
    offset_x = _clamp(vx * look_ahead_factor * 5.0, -max_offset_x, max_offset_x)
    offset_y = _clamp(vy * look_ahead_factor * 5.0, -max_offset_y, max_offset_y)

    cx = _clamp(cx + offset_x, cw / 2.0, float(frame_w) - cw / 2.0)
    cy = _clamp(cy + offset_y, ch / 2.0, float(frame_h) - ch / 2.0)

    return (cx, cy, cw, ch)
