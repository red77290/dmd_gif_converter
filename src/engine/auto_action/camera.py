from typing import Optional, Tuple
from src.engine.auto_action.interfaces import CamRect, BoundingBox
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.analysis.analysis import _clamp

# Minimum source pixels per target DMD pixel to prevent upscaling / interpolation blur
_MIN_DETAIL_SRC_PER_DMD_PX = 1.75

# Canonical close-up eyes-to-mouth vertical band inside a YOLOv8 `person` close-up ROI.
# In real close-up / portrait shots (`aspect = rh / rw <= 1.4`), a `person` box spans from
# crown/hair (`0.00*rh`) down to the neck and upper shoulders at the frame bottom (`1.00*rh`):
#   - Hair & forehead: ~0.00 .. 0.22 * rh
#   - Eyes & eyebrows: ~0.25 .. 0.35 * rh
#   - Nose:            ~0.36 .. 0.46 * rh
#   - Mouth / lips:    ~0.48 .. 0.58 * rh
#   - Chin & neck:     ~0.64 .. 1.00 * rh
# Anchoring on `[0.23..0.61]*rh` (midpoint `0.42*rh`) centers wide DMD strips (4:1 / 2:1)
# across both the eyes and the mouth instead of framing eyes+forehead (~0.27*rh) or
# nose+chin (~0.57*rh).
_CLOSEUP_BASE_EYE_OFFSET = 0.23
_CLOSEUP_BASE_BAND_FRAC = 0.38
_CLOSEUP_DEFAULT_CENTER_FRAC = _CLOSEUP_BASE_EYE_OFFSET + (_CLOSEUP_BASE_BAND_FRAC / 2.0)  # 0.42


def closeup_eye_mouth_fractions(aspect: float) -> Tuple[float, float]:
    """Return `(eye_offset, head_frac)` for a close-up `person` ROI of `aspect = rh / rw`.

    For wide/square close-ups (`aspect <= 1.0`), returns `(0.23, 0.38)` (`[0.23..0.61]*rh`,
    centred at `0.42*rh`). For taller bust / head-and-shoulders close-ups (`1.0 < aspect <= 1.4`),
    additional upper chest enters the bottom of `rh` while shoulder width `rw` remains constant,
    so the eye-to-mouth band scales smoothly upward with `aspect`.
    """
    scale = 1.0 / (1.0 + 0.50 * max(0.0, float(aspect) - 1.0))
    return _CLOSEUP_BASE_EYE_OFFSET * scale, _CLOSEUP_BASE_BAND_FRAC * scale


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


def _compute_detail_preserving_crop_dimensions(
    eff_w: float,
    eff_h: float,
    cfg: AutoActionConfig,
    median_h: Optional[float] = None,
    median_w: Optional[float] = None,
) -> Tuple[float, float]:
    """
    Compute static, shot-locked crop dimensions (crop_w, crop_h) that zoom in
    just enough to make a small subject readable on the DMD while strictly
    preserving native pixel detail (never dropping below _MIN_DETAIL_SRC_PER_DMD_PX
    source pixels per DMD pixel).
    """
    target_w = max(1, int(getattr(cfg, "target_width", 128)))
    target_h = max(1, int(getattr(cfg, "target_height", 32)))
    target_ratio = float(target_w) / float(target_h)

    max_w, max_h = _compute_base_crop_dimensions(float(eff_w), float(eff_h), target_ratio)

    cfg_zoom_max = max(1.0, float(getattr(cfg, "zoom_max", 1.45)))
    effective_zoom_max = cfg_zoom_max
    scene_profile = getattr(cfg, "scene_profile", None)
    if scene_profile is not None and getattr(scene_profile, "max_zoom_override", None) is not None:
        effective_zoom_max = min(effective_zoom_max, max(1.0, float(scene_profile.max_zoom_override)))

    strength = _clamp(float(getattr(cfg, "strength", 0.65)), 0.0, 1.0)
    if effective_zoom_max <= 1.001 or strength <= 1e-4:
        return max_w, max_h

    # Detail-preservation floor: require at least _MIN_DETAIL_SRC_PER_DMD_PX source pixels
    # per DMD pixel so low-res pixel art and video detail never blur or shimmer.
    min_detail_w = min(max_w, float(target_w) * _MIN_DETAIL_SRC_PER_DMD_PX)
    min_detail_h = min(max_h, float(target_h) * _MIN_DETAIL_SRC_PER_DMD_PX)
    detail_zoom_cap = min(
        max_w / max(1.0, min_detail_w),
        max_h / max(1.0, min_detail_h),
    )
    effective_zoom_max = min(effective_zoom_max, max(1.0, detail_zoom_cap))
    if effective_zoom_max <= 1.001:
        return max_w, max_h

    # Only zoom when subject dimensions were measured; never blind-zoom unknown shots
    if median_h is None or median_h <= 0:
        return max_w, max_h

    padding = _clamp(float(getattr(cfg, "padding", 0.20)), 0.0, 1.0)
    _platformer = getattr(cfg, "platformer_mode", False)
    _auto = getattr(cfg, "auto_vertical_bias", False)
    _floor_ratio = getattr(cfg, "platformer_floor_ratio", 0.90) if _platformer else 0.93

    ideal_h = float(median_h) * (1.0 + padding)
    if _auto or _platformer:
        required_h = float(median_h) / max(0.1, _floor_ratio - 0.05)
        ideal_h = max(ideal_h, required_h)
    ideal_w = ideal_h * target_ratio

    if median_w is not None and median_w > 0:
        min_sub_w = float(median_w) * (1.0 + padding)
        if ideal_w < min_sub_w:
            ideal_w = min_sub_w
            ideal_h = ideal_w / target_ratio

    # If the subject already fills or exceeds the unzoomed window, keep wide shot (1.0x)
    if ideal_w >= max_w:
        return max_w, max_h

    crop_w = max_w - strength * (max_w - ideal_w)
    min_allowed_w = max(min_detail_w, max_w / effective_zoom_max)
    crop_w = _clamp(crop_w, min_allowed_w, max_w)
    crop_h = crop_w / target_ratio

    if crop_h > max_h:
        crop_h = max_h
        crop_w = crop_h * target_ratio
    elif crop_h < min_detail_h:
        crop_h = min_detail_h
        crop_w = min(max_w, crop_h * target_ratio)

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
        if _platformer and abs(_bias) < 1e-4:
            _bias = 1.0   # platformer pushes down to ensure floor is visible
        elif _auto and abs(_bias) < 1e-4:
            _bias = -1.0  # person smart pushes up to ensure head is visible

    _FLOOR_RATIO: float = getattr(cfg, "platformer_floor_ratio", 0.90) if _platformer else 0.93

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
        scene_type_none = getattr(cfg.scene_profile, "scene_type", "") if getattr(cfg, "scene_profile", None) else ""
        if face_priority_mode and scene_type_none == "talking_closeup" and abs(_bias) < 1e-4:
            cy = effective_frame_top + effective_frame_h * _CLOSEUP_DEFAULT_CENTER_FRAC
        else:
            cy = effective_frame_top + effective_frame_h / 2.0
        if floor_y_est is not None and (_platformer or _auto) and not face_priority_mode:
            med_h = float(getattr(cfg, "median_subject_height", 0.0) or 0.0)
            max_fit_h = crop_h * (_FLOOR_RATIO - 0.06)
            if _platformer and med_h > max_fit_h:
                # Tall sprite (VS Fighting / large-sprite platformer): hold camera at estimated
                # head/upper-half height on missed frames instead of plunging onto the feet/floor.
                est_top = floor_y_est - med_h
                cy = _clamp((est_top - crop_h * 0.06) + crop_h / 2.0, _cy_min(crop_h), _cy_max(crop_h))
            else:
                cy = _apply_auto_floor(cy, floor_y_est, crop_h)
        else:
            cy = _apply_bias(cy, crop_h)
        return CamRect(cx, cy, crop_w, crop_h)

    x, y, w, h = roi
    hair_headroom = h * 0.05
    ideal_top = max(0.0, y - hair_headroom)
    cx = x + w / 2.0
    cy = y + h / 2.0

    roi_aspect = float(h) / max(1.0, float(w))
    is_implicit_closeup = (
        not face_priority_mode
        and not _platformer
        and target_ratio >= 1.2
        and abs(_bias) < 1e-4
        and float(h) >= crop_h * 0.85
        and float(h) >= float(effective_frame_h) * 0.45
        and roi_aspect <= 1.4
    )

    if face_priority_mode:
        # `roi` has already been clipped to the expressive eye-to-mouth region
        # (for close-ups) or head region (for full-body). Center directly on it
        # without clamping upward toward the hairline/forehead.
        cy = y + h / 2.0
    elif is_implicit_closeup:
        # Mid-video cut or unclipped close-up portrait when face_priority_mode is off:
        # anchor on the expressive eye-to-mouth band (~0.42*h for wide/square close-ups,
        # scaled for bust shots) instead of floor-tracking onto forehead or sinking to chin.
        eye_off, band_frac = closeup_eye_mouth_fractions(roi_aspect)
        cy = y + (eye_off + band_frac / 2.0) * h
    elif _auto or _platformer:
        fy = floor_y_est if floor_y_est is not None else float(y + h)
        cy_floor = _apply_auto_floor(cy, fy, crop_h)
        if _platformer:
            cy = cy_floor
            # Only intervene on `cy_floor` as an outer anti-clipping safety boundary
            # when a non-explosion sprite genuinely crosses outside the floor-anchored window
            # (normal standing, walking, and jumps within the window stay 100% locked on `cy_floor`).
            is_scene_explosion = (
                floor_y_est is not None
                and float(w) > float(effective_frame_w) * 0.65
                and float(h) > float(effective_frame_h) * 0.58
            )
            if not is_scene_explosion:
                cam_top_floor = cy_floor - crop_h / 2.0
                cam_bottom_floor = cy_floor + crop_h / 2.0
                head_pad = crop_h * 0.06
                floor_ratio = _clamp(float(getattr(cfg, "platformer_floor_ratio", 0.90)), 0.50, 0.96)
                foot_pad = crop_h * (1.0 - floor_ratio)
                max_fit_h = crop_h * max(0.20, floor_ratio - 0.06)
                if float(h) > max_fit_h:
                    # Unified Tall-Sprite Rule (VS Fighting & large-sprite platformers):
                    # When the sprite cannot fit between head_pad and the floor line, prioritize
                    # the upper half of the character with its head/face anchored near the top
                    # of the DMD strip, allowing the floor line and lower legs to go below frame.
                    cy = (float(y) - head_pad) + crop_h / 2.0
                elif float(y) < cam_top_floor + head_pad:
                    cy = (float(y) - head_pad) + crop_h / 2.0
                elif float(y + h) + foot_pad > cam_bottom_floor + 0.5:
                    cy = (float(y + h) + foot_pad) - crop_h / 2.0
        elif (cy_floor - crop_h / 2.0) > ideal_top:
            scene_type = getattr(cfg.scene_profile, "scene_type", "") if getattr(cfg, "scene_profile", None) else ""
            if scene_type in ("platformer", "fighting_2d", "action_horizontal"):
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
