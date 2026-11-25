import collections
from typing import Deque, Optional, Tuple
import numpy as np

def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class _FloorEstimator:
    """Stance-aware bidirectional floor/platform level estimator."""

    # α ∈ (0, 1] — higher = faster response
    _ALPHA_ATTACK         = 0.28   # smooth same-platform landing & unconfirmed drop step
    _ALPHA_DROP           = 0.58   # moderate step-down convergence (<= 14% frame height)
    _ALPHA_DROP_CONFIRMED = 0.80   # fast lock on 2nd+ consecutive lower-platform sample
    _ALPHA_RELEASE_JUMP   = 0.01   # rock-steady hold during transient jumps (<1px drift)
    _ALPHA_RELEASE_STANCE = 0.38   # brisk upward re-anchoring onto a confirmed upper platform

    def __init__(self, frame_h: int) -> None:
        self._frame_h: float = float(frame_h)
        self._floor_y: Optional[float] = None
        self._has_detection: bool = False
        self._window: Deque[float] = collections.deque(maxlen=12)
        self._consecutive_bottom_spikes: int = 0
        self._consecutive_elevated: int = 0
        self._consecutive_lower: int = 0
        self._reanchoring_up: bool = False

    def update(self, roi_bottom: Optional[float]) -> float:
        """Feed the latest fresh roi_bottom and return the current floor estimate."""
        if roi_bottom is None:
            self._consecutive_bottom_spikes = 0
            # No detection: keep last known floor (camera stays anchored).
            if self._floor_y is None:
                # Very first frame with no ROI → default to 80 % of frame.
                self._floor_y = self._frame_h * 0.80
            return self._floor_y

        rb = float(roi_bottom)
        if not self._has_detection or self._floor_y is None:
            self._floor_y = rb          # first real detection: snap immediately
            self._has_detection = True
            self._window.append(rb)
            self._consecutive_bottom_spikes = 0
            self._consecutive_elevated = 0
            self._reanchoring_up = False
            return self._floor_y

        # Reject isolated 1-frame downward spikes near the extreme frame bottom
        # (prevents single-frame bottom-border scroll noise from snapping _floor_y
        # to the bottom of a thick ground slab) unless corroborated by >= 2 samples.
        is_extreme_bottom_spike = (
            rb > self._floor_y + 0.12 * self._frame_h
            and rb >= 0.96 * self._frame_h
        )
        if is_extreme_bottom_spike:
            self._consecutive_bottom_spikes += 1
            if self._consecutive_bottom_spikes < 2:
                return self._floor_y
        else:
            self._consecutive_bottom_spikes = 0

        self._window.append(rb)

        # Normal downward landing or drop to lower platform
        if rb >= self._floor_y:
            self._consecutive_elevated = 0
            self._reanchoring_up = False
            drop_delta = rb - self._floor_y
            if drop_delta > 0.055 * self._frame_h and not is_extreme_bottom_spike:
                self._consecutive_lower += 1
                if self._consecutive_lower >= 2:
                    alpha_down = self._ALPHA_DROP_CONFIRMED
                elif drop_delta > 0.14 * self._frame_h:
                    # Require 2nd sample before aggressive plunge into deep ground slabs
                    alpha_down = self._ALPHA_ATTACK
                else:
                    alpha_down = self._ALPHA_DROP
            else:
                self._consecutive_lower = 0
                alpha_down = self._ALPHA_ATTACK
            self._floor_y += alpha_down * drop_delta
            return self._floor_y

        self._consecutive_lower = 0

        # Character is elevated above current floor (rb < self._floor_y)
        if rb <= self._floor_y - 0.05 * self._frame_h:
            self._consecutive_elevated += 1
        else:
            self._consecutive_elevated = 0

        recent = list(self._window)
        stance_detected = False
        stance_target = rb

        if len(recent) >= 4:
            recent_4 = recent[-4:]
            spread_4 = max(recent_4) - min(recent_4)
            if spread_4 <= 0.032 * self._frame_h:
                elev_thresh_4 = (
                    self._floor_y
                    if self._reanchoring_up
                    else (self._floor_y - 0.045 * self._frame_h)
                )
                if all(s <= elev_thresh_4 for s in recent_4):
                    stance_detected = True
                    stance_target = float(np.median(recent_4))

        if not stance_detected and len(recent) >= 6:
            recent_6 = recent[-6:]
            spread_6 = max(recent_6) - min(recent_6)
            if spread_6 > 0.055 * self._frame_h:
                self._reanchoring_up = False
            elif spread_6 <= 0.045 * self._frame_h:
                elev_thresh = (
                    self._floor_y
                    if self._reanchoring_up
                    else (self._floor_y - 0.045 * self._frame_h)
                )
                if all(s <= elev_thresh for s in recent_6):
                    stance_detected = True
                    stance_target = float(np.median(recent_6))

        if not stance_detected and self._consecutive_elevated >= 10 and len(recent) >= 10:
            recent_10 = recent[-10:]
            if (max(recent_10[-6:]) - min(recent_10[-6:])) <= 0.08 * self._frame_h:
                stance_detected = True
                stance_target = float(np.median(recent_10[-6:]))

        if stance_detected:
            self._reanchoring_up = True
            self._floor_y += self._ALPHA_RELEASE_STANCE * (stance_target - self._floor_y)
        elif (
            self._consecutive_elevated >= 5
            and len(recent) >= 5
            and all(s <= self._floor_y - 0.125 * self._frame_h for s in recent[-5:])
        ):
            # Sustained elevated chain-jumping / climbing / swimming across upper platforms:
            # follow the 80th-percentile lower foot envelope (upper platform contact tier,
            # never the jump apex) smoothly without waiting for the character to stand still.
            lower_envelope_target = float(np.percentile(recent[-5:], 80))
            self._floor_y += 0.24 * (lower_envelope_target - self._floor_y)
        else:
            self._floor_y += self._ALPHA_RELEASE_JUMP * (rb - self._floor_y)

        return self._floor_y

    @property
    def floor_y(self) -> Optional[float]:
        return self._floor_y

    @property
    def has_detection(self) -> bool:
        return self._has_detection


def _is_dark_frame(frame, threshold: float = 40.0) -> bool:
    """Return True if the frame is too dark to produce reliable detections."""
    try:
        import cv2 as _cv2
        gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
        return float(gray.mean()) < threshold
    except Exception:
        return False


# Shared face-priority height ratio: ROI height relative to the DMD crop window
# height that triggers face-priority mode. Must be consistent across all scan
# functions so both _compute_auto_crop_margins and _smart_auto_crop_decision
# agree on when a subject is "large enough" to be treated as a close-up.
_FACE_PRIORITY_H_RATIO: float = 0.80


def _compute_auto_crop_margins(  # noqa: C901
    src_path: str,
    detector,
    cfg,
    frame_w: int,
    frame_h: int,
    sample_count: int = 80,
) -> Tuple[float, float, bool]:
    import cv2  # already guaranteed imported by caller
    try:
        import numpy as np
    except ImportError:
        return 0.0, 0.0, False

    from src.engine.conversion.ffmpeg_utils import get_metadata
    from src.engine.auto_action.reader import FFmpegPipeReader
    
    w, h, fps_orig, duration_s = get_metadata(src_path)
    if not duration_s or duration_s <= 0:
        return 0.0, 0.0, False

    total_frames = int(duration_s * (fps_orig or 25.0))
    if duration_s < 10.0:
        sample_count = min(total_frames, int(duration_s * 5))
    elif duration_s < 60.0:
        sample_count = min(total_frames, int(duration_s * 2))
    else:
        sample_count = min(total_frames, int(duration_s * 1))
    sample_count = max(20, min(sample_count, 150))

    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio

    roi_tops: list[float]    = []
    roi_bottoms: list[float] = []
    roi_heights: list[float] = []
    roi_widths: list[float]  = []
    face_priority_count: int = 0

    target_fps = float(sample_count) / duration_s
    reader = FFmpegPipeReader(src_path)
    ok, _ = reader.open(target_fps=target_fps)
    if not ok:
        return 0.0, 0.0, False

    try:
        for _ in range(sample_count + 5):
            ok, frame = reader.read()
            if not ok or frame is None:
                break
            if _is_dark_frame(frame):
                continue
            roi = detector.detect_person(frame, is_batch=cfg.is_batch) if hasattr(detector, "detect_person") else detector.detect(frame, cfg.detector, is_batch=cfg.is_batch)
            if roi is not None:
                rx, ry, rw, rh = roi
                roi_tops.append(float(ry))
                roi_heights.append(float(rh))
                roi_widths.append(float(rw))
                roi_bottoms.append(float(ry + rh))
                if rh > dmd_crop_h * _FACE_PRIORITY_H_RATIO:
                    face_priority_count += 1
    finally:
        reader.release()

    if not roi_tops:
        return 0.0, 0.0, False

    is_platformer_cfg = getattr(cfg, "platformer_mode", False) is True
    face_priority = (face_priority_count > len(roi_tops) * 0.5) and not is_platformer_cfg
    median_h = float(np.median(roi_heights))
    median_w = float(np.median(roi_widths)) if roi_widths else max(1.0, median_h)
    aspect   = median_h / max(1.0, median_w)

    if face_priority:
        pad_top_px    = frame_h * 0.15
        pad_bottom_px = frame_h * 0.25
    else:
        if aspect < 1.3:
            pad_frac = 0.15
        elif aspect < 2.5:
            pad_frac = 0.10
        else:
            pad_frac = 0.06
        pad_top_px    = frame_h * pad_frac
        pad_bottom_px = frame_h * pad_frac

    top_y    = float(np.percentile(roi_tops,    5)) - pad_top_px
    bottom_y = float(np.percentile(roi_bottoms, 95)) + pad_bottom_px

    top_y    = max(0.0, top_y)
    bottom_y = min(float(frame_h), bottom_y)

    top_pct    = _clamp(top_y / frame_h, 0.0, 0.9)
    if face_priority:
        top_pct = 0.0
    bottom_pct = _clamp((frame_h - bottom_y) / frame_h, 0.0, 0.9)

    return top_pct, bottom_pct, face_priority


def _measure_frame_pillarbox_bounds(frame: np.ndarray) -> Optional[Tuple[float, float]]:
    """
    Measure normalized `[left_edge, right_edge]` (`0.0 .. 1.0`) of active content in `frame`.

    Handles:
    - Full-range (`0..4`) and BT.601/BT.709 limited-range (`16..28`) black/charcoal side bars,
    - Corner watermarks / channel bugs / progress bars (analyzes central 76% vertical band),
    - 1-2px outer window borders or MPEG edge ringing,
    while preserving saturated dark gameplay colors (deep blue water / night skies via max-RGB
    and chroma gating) and starfields (98th-percentile column intensity).
    Returns `None` when the interior of the frame is dark (fade-to-black).
    """
    import cv2

    scan_w, scan_h = 256, 144
    small = cv2.resize(frame, (scan_w, scan_h), interpolation=cv2.INTER_AREA)
    if small.ndim == 2:
        val = small
        chroma = np.zeros_like(small, dtype=np.int16)
    else:
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        cmax = small.max(axis=2)
        cmin = small.min(axis=2)
        val = np.maximum(gray, cmax)
        chroma = cmax.astype(np.int16) - cmin.astype(np.int16)

    y0 = int(round(scan_h * 0.12))
    y1 = int(round(scan_h * 0.88))
    val_mid = val[y0:y1, :]
    chroma_mid = chroma[y0:y1, :]

    interior_ref = float(np.percentile(val_mid[:, 48:208], 98))
    if interior_ref < 45.0:
        return None

    col_p98 = np.percentile(val_mid, 98, axis=0)
    col_p15 = np.percentile(val_mid, 15, axis=0)
    col_span = col_p98 - col_p15
    col_chroma = np.percentile(chroma_mid, 90, axis=0)

    black_ceil = min(30.0, max(20.0, interior_ref * 0.22))
    is_bar = (col_p98 <= black_ceil) & (col_span <= 14.0) & (col_chroma <= 14.0)

    max_side_cols = int(scan_w * 0.42)

    x_left = 0
    if not is_bar[0] and bool(np.all(is_bar[2:5])):
        x_left = 2
    while x_left < max_side_cols:
        if is_bar[x_left]:
            x_left += 1
        elif (x_left + 2 < max_side_cols) and is_bar[x_left + 1] and is_bar[x_left + 2]:
            x_left += 1
        else:
            break

    x_right = scan_w - 1
    if not is_bar[scan_w - 1] and bool(np.all(is_bar[scan_w - 5 : scan_w - 2])):
        x_right = scan_w - 3
    min_right_col = scan_w - 1 - max_side_cols
    while x_right > min_right_col:
        if is_bar[x_right]:
            x_right -= 1
        elif (x_right - 2 > min_right_col) and is_bar[x_right - 1] and is_bar[x_right - 2]:
            x_right -= 1
        else:
            break

    if x_left >= x_right:
        return None
    return float(x_left) / float(scan_w), float(x_right + 1) / float(scan_w)


def _resolve_pillarbox_margins(
    frame_lefts: list[float],
    frame_rights: list[float],
    frame_w: int,
    enabled: bool,
) -> Tuple[float, float, str]:
    """
    Resolve static `(left_pct, right_pct, status_code)` horizontal crop margins from sampled frames.

    Detects both wide 4:3-in-16:9 pillarbox bars (~12.5%+) and thin hardware overscan blanking
    strips (e.g. NES/SMS 8px left blanking ~2.5%-4.5%) by requiring temporal lock around a
    fixed geometric X wall, plus a compact YUV420p/ringing safety margin so side borders never
    intrude or visibly slide during horizontal camera pans.
    """
    if not enabled:
        return 0.0, 0.0, "disabled"
    n = len(frame_lefts)
    if n == 0 or len(frame_rights) != n:
        return 0.0, 0.0, "none"

    min_bar = max(0.012, 3.0 / max(128.0, float(frame_w)))

    def _lock_side_wall(bars: np.ndarray) -> float:
        pos = bars[bars >= min_bar]
        if pos.size == 0 or (pos.size / float(n)) < 0.50:
            return 0.0
        # Use conservative 20th percentile of positive detections so dark space scenes
        # adjacent to a pillarbox lock onto the outer geometric bar wall rather than
        # eating into dark gameplay interiors.
        wall_ref = float(np.percentile(pos, 20))
        wall_hits = int(np.sum((bars >= wall_ref - 0.008) & (bars <= wall_ref + 0.018)))
        support = wall_hits / float(n)
        req_support = 0.50 if wall_ref >= 0.045 else 0.65
        if support < req_support:
            return 0.0
        safety = max(2.0 / max(128.0, float(frame_w)), min(0.016, wall_ref * 0.08 + 0.004))
        return _clamp(wall_ref + safety, 0.0, 0.42)

    left_pct = _lock_side_wall(np.asarray(frame_lefts, dtype=np.float64))
    right_pct = _lock_side_wall(1.0 - np.asarray(frame_rights, dtype=np.float64))
    code = "detected" if (left_pct > 0.0 or right_pct > 0.0) else "none"
    return left_pct, right_pct, code


def _smart_auto_crop_decision(src_path: str, cfg, frame_w: int, frame_h: int, sample_count: int = 80) -> dict:
    from src.plugins.detectors.detector import _FrameDetector
    try:
        detector = _FrameDetector()
    except Exception as e:
        return {
            "auto_bottom_crop":   False,
            "auto_top_crop":      False,
            "auto_vertical_bias": False,
            "top_pct":            0.0,
            "bottom_pct":         0.0,
            "left_pct":           0.0,
            "right_pct":          0.0,
            "face_priority":      False,
            "reasons":            [f"detector init failed: {e!r}"],
        }
    _EMPTY = {
        "auto_bottom_crop":   False,
        "auto_top_crop":      False,
        "auto_vertical_bias": False,
        "top_pct":            0.0,
        "bottom_pct":         0.0,
        "left_pct":           0.0,
        "right_pct":          0.0,
        "face_priority":      False,
        "reasons":            [],
    }
    if not (
        bool(cfg.smart_auto_crop)
        or getattr(cfg, "auto_strength", False) is True
        or getattr(cfg, "auto_smoothness", False) is True
        or getattr(cfg, "auto_pillarbox_crop", False) is True
        or getattr(cfg, "auto_scene_type", False) is True
    ):
        return {**_EMPTY, "reasons": ["smart features disabled in config"]}

    from src.engine.conversion.ffmpeg_utils import get_metadata
    from src.engine.auto_action.reader import FFmpegPipeReader
    
    w, h, fps_orig, duration_s = get_metadata(src_path)
    if not duration_s or duration_s <= 0:
        return {**_EMPTY, "reasons": ["could not determine duration"]}

    total_frames = int(duration_s * (fps_orig or 25.0))
    if duration_s < 10.0:
        sample_count = min(total_frames, int(duration_s * 5))
    elif duration_s < 60.0:
        sample_count = min(total_frames, int(duration_s * 2))
    else:
        sample_count = min(total_frames, int(duration_s * 1))
    sample_count = max(20, min(sample_count, 150))

    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio
    DMD_CROP_H_FACTOR = _FACE_PRIORITY_H_RATIO
    FACE_FRAC = 0.28
    
    target_fps = float(sample_count) / duration_s
    check_pillarbox = getattr(cfg, "auto_pillarbox_crop", False) is True

    _explicit_scene_cfg = str(getattr(cfg, "scene_type", "") or "").strip()
    initial_scan_plat = bool(
        getattr(cfg, "platformer_mode", False) is True
        or _explicit_scene_cfg in ("platformer", "fighting_2d")
    )

    def _run_scan(det_type: str, force_platformer: bool = False):
        _roi_tops: list[float]         = []
        _roi_bottoms_feet: list[float] = []
        _roi_bottoms_fp: list[float]   = []
        _roi_heights: list[float]      = []
        _roi_widths: list[float]       = []
        _x_centers: list[float]        = []
        _y_centers: list[float]        = []
        _fill_ratios: list[float]      = []
        _frame_lefts: list[float]      = []
        _frame_rights: list[float]     = []
        
        reader = FFmpegPipeReader(src_path)
        ok, _ = reader.open(target_fps=target_fps)
        if not ok:
            return [], [], [], [], [], [], [], [], [], []
            
        _scan_plat = bool(force_platformer or initial_scan_plat)
        try:
            for _ in range(sample_count + 5):
                ok, frame = reader.read()
                if not ok or frame is None: break

                if check_pillarbox:
                    pb_bounds = _measure_frame_pillarbox_bounds(frame)
                    if pb_bounds is not None:
                        _frame_lefts.append(pb_bounds[0])
                        _frame_rights.append(pb_bounds[1])

                if _is_dark_frame(frame): continue
                
                if _scan_plat:
                    roi = detector.detect(
                        frame, det_type, platformer_mode=True, is_batch=cfg.is_batch
                    )
                elif det_type == "person" and hasattr(detector, "detect_person"):
                    roi = detector.detect_person(frame, is_batch=cfg.is_batch)
                else:
                    roi = detector.detect(frame, det_type, is_batch=cfg.is_batch)
                    
                if roi is not None:
                    rx, ry, rw, rh = roi
                    _roi_tops.append(float(ry))
                    _roi_bottoms_feet.append(float(ry + rh))
                    _roi_heights.append(float(rh))
                    _roi_widths.append(float(rw))
                    _x_centers.append(float(rx + rw / 2.0))
                    _y_centers.append(float(ry + rh / 2.0))
                    _fill_ratios.append(float(rh) / max(1.0, float(frame_h)))
                    _roi_bottoms_fp.append(float(ry + rh))
        finally:
            reader.release()
            
        return _roi_tops, _roi_bottoms_feet, _roi_bottoms_fp, _roi_heights, _roi_widths, _x_centers, _y_centers, _fill_ratios, _frame_lefts, _frame_rights

    best_detector = cfg.detector
    (roi_tops, roi_bottoms_feet, roi_bottoms_fp, roi_heights, roi_widths, 
     x_centers, y_centers, fill_ratios, frame_lefts, frame_rights) = _run_scan(best_detector)
     
    if not roi_tops and getattr(cfg, "auto_detector_fallback", False) and best_detector == "person":
        best_detector = "hybrid"
        (roi_tops, roi_bottoms_feet, roi_bottoms_fp, roi_heights, roi_widths, 
         x_centers, y_centers, fill_ratios, fb_lefts, fb_rights) = _run_scan(best_detector)
        if fb_lefts:
            frame_lefts, frame_rights = fb_lefts, fb_rights

    left_pct, right_pct, pillarbox_code = _resolve_pillarbox_margins(
        frame_lefts, frame_rights, frame_w, check_pillarbox
    )

    _explicit_scene = str(getattr(cfg, "scene_type", "") or "").strip()
    _auto_scene = getattr(cfg, "auto_scene_type", False)
    if not roi_tops:
        # No detections: honor explicit scene_type first, otherwise assign safe default profile
        # while still preserving detected pillarbox crop margins!
        from src.engine.analysis.scene_types import SCENE_PROFILES, SceneType
        base_out = {
            **_EMPTY,
            "left_pct": left_pct,
            "right_pct": right_pct,
            "decision_codes": {"pillarbox": pillarbox_code},
            "best_detector": best_detector,
        }
        if _explicit_scene and _explicit_scene in SCENE_PROFILES:
            _fallback_profile = SCENE_PROFILES[_explicit_scene]
            return {
                **base_out,
                "auto_vertical_bias": _fallback_profile.auto_vertical_bias,
                "face_priority": _fallback_profile.face_priority,
                "reasons": [f"no detections in scan → explicit scene '{_explicit_scene}'"],
                "scene_profile": _fallback_profile,
                "suggested_strength": _fallback_profile.suggested_strength,
                "suggested_smoothness": _fallback_profile.suggested_smoothness,
                "scoreboard_lines": [],
                "scene_scores": {},
            }
        if _auto_scene:
            _fallback_profile = SCENE_PROFILES.get(SceneType.ACTION_MOVING)
            return {
                **base_out,
                "reasons": ["no detections in scan → fallback to action_moving"],
                "scene_profile": _fallback_profile,
                "suggested_strength": _fallback_profile.suggested_strength if _fallback_profile else 0.65,
                "suggested_smoothness": _fallback_profile.suggested_smoothness if _fallback_profile else 0.85,
                "scoreboard_lines": [],
                "scene_scores": {},
            }
        return {**base_out, "reasons": ["no detections in scan — all manual"]}

    arr_tops       = np.array(roi_tops)
    arr_btm_feet   = np.array(roi_bottoms_feet)
    arr_btm_fp     = np.array(roi_bottoms_fp)
    arr_heights    = np.array(roi_heights)
    arr_widths     = np.array(roi_widths) if roi_widths else arr_heights

    median_top    = float(np.median(arr_tops))
    median_bottom = float(np.median(arr_btm_feet))
    median_height = float(np.median(arr_heights))
    std_bottom    = float(np.std(arr_btm_feet))

    TOP_SPACE_THRESH  = 0.08
    BOTTOM_GAP_THRESH = 0.08
    # face_priority triggers when the median ROI height exceeds this fraction of the
    # DMD crop window height.  MUST stay in sync with _FACE_PRIORITY_H_RATIO above so
    # that _smart_auto_crop_decision and _compute_auto_crop_margins agree.
    # History: was accidentally raised to 1.30 in fix/2921a4d, which caused regression
    # where face-priority never triggered for normal close-up shots.
    TALL_FACTOR       = _FACE_PRIORITY_H_RATIO  # 0.80 — restored to match DMD_CROP_H_FACTOR
    FLOOR_LOWER       = 0.50
    FLOOR_VAR_MAX     = 0.25

    top_space       = median_top    / frame_h
    bottom_gap      = (frame_h - median_bottom) / frame_h
    tall_ratio      = median_height / max(1.0, dmd_crop_h)
    p75_bottom      = float(np.percentile(arr_btm_feet, 75))
    floor_in_lower  = bool(
        (median_bottom / frame_h) > FLOOR_LOWER
        or (
            len(arr_btm_feet) >= 4
            and (median_height / frame_h) < 0.30
            and (p75_bottom / frame_h) > 0.55
            and (median_bottom / frame_h) > 0.32
            and (std_bottom / frame_h) <= 0.34
        )
    )
    floor_var_score = std_bottom / frame_h

    # Additional signals for scene classification
    median_w       = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
    body_aspect    = median_height / max(1.0, median_w)
    median_fill    = float(np.median(fill_ratios)) if fill_ratios else 0.0
    x_var          = float(np.var(x_centers)) / max(1.0, float(frame_w) ** 2) if x_centers else 0.0
    y_var          = float(np.var(y_centers)) / max(1.0, float(frame_h) ** 2) if y_centers else 0.0

    # ── Scene classification (auto_scene_type or smart_auto_crop) ────────────
    scene_profile = None
    scene_scores = {}
    scene_signals = {
        "tall_ratio":      tall_ratio,
        "fill_ratio":      median_fill,
        "body_aspect":     body_aspect,
        "floor_in_lower":  floor_in_lower,
        "floor_var_score": floor_var_score,
        "x_variance":      x_var,
        "y_variance":      y_var,
    }
    
    _explicit_scene = str(getattr(cfg, "scene_type", "") or "").strip()
    _auto_scene = getattr(cfg, "auto_scene_type", False)
    if _explicit_scene:
        from src.engine.analysis.scene_types import SCENE_PROFILES
        if _explicit_scene in SCENE_PROFILES:
            scene_profile = SCENE_PROFILES[_explicit_scene]
            scoreboard_lines = [f"Explicit scene_type='{_explicit_scene}' honored"]
        elif _auto_scene:
            from src.engine.analysis.scene_types import classify_scene
            scene_profile, scoreboard_lines, scene_scores = classify_scene(scene_signals)
        else:
            scoreboard_lines = []
    elif _auto_scene:
        from src.engine.analysis.scene_types import classify_scene
        scene_profile, scoreboard_lines, scene_scores = classify_scene(scene_signals)
    else:
        scoreboard_lines = []

    if (
        not initial_scan_plat
        and scene_profile is not None
        and scene_profile.platformer_mode
        and (best_detector in ("hybrid", "motion") or median_w > frame_w * 0.36)
    ):
        try:
            (p_tops, p_btm_feet, p_btm_fp, p_heights, p_widths,
             _, _, _, _, _) = _run_scan(best_detector, force_platformer=True)
            if p_tops and p_heights:
                arr_tops = np.array(p_tops)
                arr_btm_feet = np.array(p_btm_feet)
                arr_btm_fp = np.array(p_btm_fp)
                arr_heights = np.array(p_heights)
                arr_widths = np.array(p_widths) if p_widths else arr_heights
                median_top = float(np.median(arr_tops))
                median_bottom = float(np.median(arr_btm_feet))
                median_height = float(np.median(arr_heights))
                median_w = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
                body_aspect = median_height / max(1.0, median_w)
        except Exception:
            pass

    reasons = []
    auto_bottom = False
    auto_top    = False
    auto_floor  = False

    decision_codes = {}
    
    is_platformer_cfg = getattr(cfg, "platformer_mode", False) is True
    if scene_profile is not None:
        # Scene profile drives crop/tracking decisions
        auto_floor  = scene_profile.auto_vertical_bias
        auto_top    = scene_profile.face_priority  # narrow to head when face-aware
        auto_bottom = scene_profile.face_priority or (bottom_gap > BOTTOM_GAP_THRESH)
        if scene_profile.platformer_mode:
            # Never amputate the lower playfield in platformer/fighting_2d modes:
            # if the player starts on upper platforms during scan frames, cropping bottom_gap
            # creates an artificial floor ceiling that loses the character when descending!
            auto_top    = False
            auto_bottom = False
        suggested_strength   = scene_profile.suggested_strength
        suggested_smoothness = scene_profile.suggested_smoothness
        reasons.append(f"SCENE={scene_profile.scene_type} → face_clip={scene_profile.face_clip_mode} floor={scene_profile.auto_vertical_bias}")
        decision_codes["driver"] = "scene_profile"
        
    elif tall_ratio > TALL_FACTOR and not is_platformer_cfg:
        auto_bottom = True
        auto_floor  = False
        auto_top    = True
        suggested_strength = 0.55
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 1 — tall-char {tall_ratio*100:.0f}% of DMD window → bottom-crop+face-priority ✓ / top-crop ✓ (narrows to head) / floor-track ✗ (contradictory)")
        decision_codes["driver"] = "tall_subject"
        
    elif is_platformer_cfg or (floor_in_lower and floor_var_score <= FLOOR_VAR_MAX):
        auto_floor  = True
        auto_top    = False
        auto_bottom = False if is_platformer_cfg else (bottom_gap > BOTTOM_GAP_THRESH)
        stability   = "stable" if floor_var_score < 0.10 else "dynamic"
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 2 — floor@{median_bottom/frame_h*100:.0f}% var={floor_var_score*100:.0f}% ({stability}) → floor-tracking ✓ / top-crop ✗ (redundant)")
        decision_codes["driver"] = "floor_tracking"
        
    else:
        auto_floor  = False
        auto_top    = top_space > TOP_SPACE_THRESH
        auto_bottom = (bottom_gap > BOTTOM_GAP_THRESH) or auto_top
        suggested_strength = 0.65
        suggested_smoothness = 0.85
        reasons.append(f"GROUP 3 — no trackable floor")
        decision_codes["driver"] = "fallback"

    face_priority = (
        scene_profile.face_priority
        if scene_profile is not None
        else (tall_ratio > TALL_FACTOR and not is_platformer_cfg)
    )
    aspect        = body_aspect
    if face_priority:
        # Protect both tall hair above and the lower face/mouth/chin below
        pad_top_px    = frame_h * 0.35
        pad_bottom_px = frame_h * 0.25
    else:
        if aspect < 1.3:
            pad_frac = 0.15
        elif aspect < 2.5:
            pad_frac = 0.10
        else:
            pad_frac = 0.06
        pad_top_px    = frame_h * pad_frac
        pad_bottom_px = frame_h * pad_frac

    top_y    = float(np.percentile(arr_tops,    5))  - pad_top_px
    bottom_y = float(np.percentile(arr_btm_feet, 95))  + pad_bottom_px
    top_y    = max(0.0,          top_y)
    bottom_y = min(float(frame_h), bottom_y)

    pre_top_pct    = _clamp(top_y    / frame_h,              0.0, 0.9)
    if face_priority:
        pre_top_pct = 0.0
    pre_bottom_pct = _clamp((frame_h - bottom_y) / frame_h,  0.0, 0.9)

    decision_codes["pillarbox"] = pillarbox_code

    return {
        "best_detector":      best_detector,
        "auto_bottom_crop":   auto_bottom,
        "auto_top_crop":      auto_top,
        "auto_vertical_bias": auto_floor,
        "top_pct":            pre_top_pct,
        "bottom_pct":         pre_bottom_pct,
        "left_pct":           left_pct,
        "right_pct":          right_pct,
        "face_priority":      face_priority,
        "reasons":            reasons,
        "decision_codes":     decision_codes,
        "suggested_strength": suggested_strength,
        "suggested_smoothness": suggested_smoothness,
        "scene_profile":      scene_profile,
        "scene_scores":       scene_scores,
        "scene_signals":      scene_signals,
        "scoreboard_lines":   scoreboard_lines,
        "median_height":      median_height,
        "median_width":       median_w,
    }



