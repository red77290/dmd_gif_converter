#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto action framing preprocessor (outside ffmpeg pipeline).

This module detects action/person regions frame-by-frame and generates a
cinematic 4:1 intermediate video before the regular ffmpeg DMD conversion.

Detection backend: ONNX YOLOv8 nano (~6 MB, CPU-only via onnxruntime).
Falls back to MOG2 motion detection when ONNX/onnxruntime is unavailable.

Intermediate encoding: raw frames are piped directly to an FFmpeg subprocess
(H.264, ultrafast preset) — no cv2.VideoWriter, no bulky mp4v temp file.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np  # Import numpy

# ── ONNX YOLOv8n model settings ───────────────────────────────────────────────
_YOLO_MODEL_URL = (
    "https://github.com/ultralytics/assets/releases/download/v0.0.0/yolov8n.onnx"
)
_YOLO_MODEL_FILENAME = "yolov8n.onnx"
# Confidence threshold for person detection (class 0 in COCO)
_YOLO_CONF_THRESH = 0.30


def _get_model_path() -> str:
    """Return the local cache path for the ONNX model (creates dirs if needed)."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "dmd_gif_converter")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, _YOLO_MODEL_FILENAME)


def _ensure_yolo_model() -> Optional[str]:
    """Download YOLOv8n ONNX model if absent; return its local path or None on failure."""
    path = _get_model_path()
    if os.path.isfile(path):
        return path
    try:
        urllib.request.urlretrieve(_YOLO_MODEL_URL, path)
        return path
    except Exception:
        return None


def available_detectors() -> list[str]:
    """Return supported detector mode names."""
    return ["person", "motion", "hybrid", "center"]


@dataclass
class AutoActionConfig:
    detector: str = "person"          # person | motion | hybrid | center
    strength: float = 0.65             # 0..1, larger = tighter framing
    smoothness: float = 0.85           # 0..0.98, larger = smoother / slower
    zoom_max: float = 2.0              # max dynamic zoom factor (hard limit)
    padding: float = 0.20              # extra padding around ROI
    intro_duration: float = 1.5        # seconds of full-frame overview before focusing
    bg_sub_enable: bool = False        # enable background subtraction (replaces background with black)
    bottom_crop_pct: float = 0.0       # fraction of image bottom to exclude from framing (0 = disabled)
    top_crop_pct: float = 0.0          # fraction of image top to exclude from framing (0 = disabled)
    auto_bottom_crop: bool = False     # auto-detect bottom crop boundary from ROI analysis
    auto_top_crop: bool = False        # auto-detect top crop boundary from ROI analysis
    vertical_bias: float = 0.0        # shift camera center: +1.0 = down (show floor), -1.0 = up (show sky)
    auto_vertical_bias: bool = False  # auto floor detection: places ROI bottom (floor) at ~85 % of crop height
    smart_auto_crop: bool = False      # let the engine choose the optimal crop/tracking combination
    # out_w / out_h are no longer used for the actual output resolution.
    # The preprocessor always outputs at the source native width with a 4:1
    # crop ratio (= DMD ratio 128:32) so that ffmpeg receives full-quality input.
    # These fields are kept for API backward-compatibility only.
    out_w: int = 0
    out_h: int = 0
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    target_width: int = 128           # Target output width for DMD
    target_height: int = 32          # Target output height for DMD


class _FrameDetector:
    """Detector backend for person/motion ROI extraction.

    Person detection uses ONNX YOLOv8 nano (class 0 = person in COCO).
    Automatically downloads the ~6 MB model to ~/.cache/dmd_gif_converter/
    on first use.  Falls back to motion-only detection when onnxruntime is
    unavailable or the model cannot be downloaded.

    Motion detection uses MOG2 background subtraction + optical flow.
    MOG2 is also used by the bg_sub_enable background-replacement feature.
    """

    def __init__(self):
        import cv2  # local import: module remains importable without OpenCV

        self.cv2 = cv2
        self.prev_gray = None

        # ── ONNX YOLOv8n person detector ──────────────────────────────────────
        # Resolves the macOS ARM64 crash that plagued the old HOG backend:
        # YOLOv8n runs through onnxruntime (CPUExecutionProvider) which does not
        # use Apple GCD parallelism and is safe on all architectures.
        self._onnx_session = None
        self._try_load_onnx()

        # MOG2 background subtractor for motion detection and background removal
        self.bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=36)

    # ── ONNX helpers ──────────────────────────────────────────────────────────

    def _try_load_onnx(self) -> None:
        """Load the ONNX YOLOv8n session; silently skips on any failure."""
        try:
            import onnxruntime as ort  # optional dependency
            model_path = _ensure_yolo_model()
            if model_path is None:
                return
            self._onnx_session = ort.InferenceSession(
                model_path, providers=["CPUExecutionProvider"]
            )
        except Exception:
            self._onnx_session = None

    def _detect_yolo(self, frame) -> Optional[Tuple[int, int, int, int]]:
        """Run YOLOv8n inference; return best person box (x, y, w, h) or None.

        The frame is resized to 640×640 (YOLOv8 native input) for inference and
        the resulting bounding box is scaled back to the original frame dimensions.
        Only the highest-confidence "person" (COCO class 0) detection is returned.
        """
        cv2 = self.cv2
        h, w = frame.shape[:2]

        # Preprocess: BGR→RGB, resize to 640×640, normalize 0→1, NCHW layout
        img = cv2.resize(frame, (640, 640), interpolation=cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[np.newaxis]  # HWC → NCHW

        input_name = self._onnx_session.get_inputs()[0].name
        pred = self._onnx_session.run(None, {input_name: img})[0][0]  # [84, 8400]

        # YOLOv8 output layout: rows [cx, cy, w, h, class_0..class_79], 8 400 proposals
        boxes_raw  = pred[:4].T          # [8400, 4] — cx/cy/w/h in 640-px space
        class_prob = pred[4:].T          # [8400, 80] — direct class probabilities
        person_scores = class_prob[:, 0]  # COCO class 0 = person

        mask = person_scores > _YOLO_CONF_THRESH
        if not np.any(mask):
            return None

        best_i = int(np.argmax(person_scores * mask))
        cx, cy, bw, bh = boxes_raw[best_i]

        # Scale box from 640×640 space back to original frame dimensions
        sx, sy = w / 640.0, h / 640.0
        x  = int((cx - bw / 2) * sx)
        y  = int((cy - bh / 2) * sy)
        bw = int(bw * sx)
        bh = int(bh * sy)

        # Clamp to frame boundaries
        x  = max(0, x)
        y  = max(0, y)
        bw = min(bw, w - x)
        bh = min(bh, h - y)
        if bw < 8 or bh < 8:
            return None
        return (x, y, bw, bh)

    # ── Public detection methods ──────────────────────────────────────────────

    def detect_person(self, frame) -> Optional[Tuple[int, int, int, int]]:
        """Return best person bounding box via ONNX YOLOv8n, or None."""
        if self._onnx_session is None:
            # onnxruntime not installed or model unavailable — caller falls back.
            return None
        return self._detect_yolo(frame)

    def detect_motion(self, frame) -> Optional[Tuple[int, int, int, int]]:
        cv2 = self.cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if self.prev_gray is None:
            self.prev_gray = gray
            return None

        diff = cv2.absdiff(gray, self.prev_gray)
        self.prev_gray = gray
        blur = cv2.GaussianBlur(diff, (7, 7), 0)
        _, mask = cv2.threshold(blur, 24, 255, cv2.THRESH_BINARY)

        fg = self.bg_sub.apply(frame)
        mask = cv2.bitwise_and(mask, fg)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_DILATE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        c = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(c)
        if area < 120.0:
            return None

        x, y, w, h = cv2.boundingRect(c)
        return (int(x), int(y), int(w), int(h))

    def detect(self, frame, mode: str) -> Optional[Tuple[int, int, int, int]]:
        mode = (mode or "person").lower()
        if mode not in available_detectors():
            mode = "person"

        if mode == "center":
            return None

        if mode == "person":
            p = self.detect_person(frame)
            if p is not None:
                return p
            return self.detect_motion(frame)

        if mode == "motion":
            m = self.detect_motion(frame)
            if m is not None:
                return m
            return self.detect_person(frame)

        # hybrid
        p = self.detect_person(frame)
        m = self.detect_motion(frame)
        if p and m:
            # Merge boxes for broader action framing.
            x1 = min(p[0], m[0])
            y1 = min(p[1], m[1])
            x2 = max(p[0] + p[2], m[0] + m[2])
            y2 = max(p[1] + p[3], m[1] + m[3])
            return (x1, y1, x2 - x1, y2 - y1)
        return p or m


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class _FloorEstimator:
    """Asymmetric exponential moving average for floor/ground level estimation.

    Designed for 2-D platformer content where the floor height changes between
    platforms and the character regularly jumps off the ground.

    Behaviour
    ---------
    • *Attack* (roi_bottom **increases** → character descends / lands lower):
      fast update — the camera follows new lower platforms quickly.
    • *Release* (roi_bottom **decreases** → character jumps / ascends):
      very slow update — the camera ignores short-lived aerial positions and
      stays anchored to the last known ground level.

    The result: during a jump the floor estimate barely moves; when the
    character lands on a new (possibly lower) platform the estimate adapts
    within roughly 10–15 frames (~0.5–1 s at 12 fps).
    """

    # α ∈ (0, 1] — higher = faster response
    _ALPHA_ATTACK  = 0.28   # fast: character lands lower / new lower platform
    _ALPHA_RELEASE = 0.02   # very slow: character in the air / moving upward

    def __init__(self, frame_h: int) -> None:
        self._frame_h: float = float(frame_h)
        self._floor_y: Optional[float] = None

    def update(self, roi_bottom: Optional[float]) -> float:
        """Feed the latest roi_bottom and return the current floor estimate."""
        if roi_bottom is None:
            # No detection: keep last known floor (camera stays anchored).
            if self._floor_y is None:
                # Very first frame with no ROI → default to 80 % of frame.
                self._floor_y = self._frame_h * 0.80
            return self._floor_y

        rb = float(roi_bottom)
        if self._floor_y is None:
            self._floor_y = rb          # first detection: snap immediately
            return self._floor_y

        # Asymmetric update
        alpha = self._ALPHA_ATTACK if rb >= self._floor_y else self._ALPHA_RELEASE
        self._floor_y += alpha * (rb - self._floor_y)
        return self._floor_y

    @property
    def floor_y(self) -> Optional[float]:
        return self._floor_y


def _compute_auto_crop_margins(
    cap,
    detector: "_FrameDetector",
    cfg: "AutoActionConfig",
    frame_w: int,
    frame_h: int,
    sample_count: int = 40,
) -> Tuple[float, float]:
    """Sample frames to compute optimal top/bottom crop percentages.

    Analyses ``sample_count`` evenly-spaced frames, collects bounding-box
    edges from the detector, and returns (top_pct, bottom_pct) as fractions
    of *frame_h* that are safe to exclude.

    Content-type inference & face priority
    ---------------------------------------
    The aspect ratio of the median detected bounding box determines whether
    the subject is a **face/close-up** (roughly square ROI → tight padding)
    or a **full body** (tall narrow ROI → looser padding).

    **Face priority mode** (new):
    When the subject's bounding-box height exceeds the DMD window height
    (``frame_w / target_ratio``), the whole body cannot fit on screen at once.
    In this case the system automatically prioritises the **face / head region**
    by treating only the top ``FACE_FRAC`` fraction of the body ROI as the
    effective "content bottom".  This guarantees the face is always fully
    visible within the DMD strip, regardless of how tall the character is.

    Face priority activates whenever the majority (> 50 %) of sampled frames
    have a ROI taller than ``DMD_CROP_H_FACTOR × dmd_window_h``.

    Returns
    -------
    (top_pct, bottom_pct) : both in [0, 0.9].  Values of 0.0 mean no crop.
    """
    import cv2  # already guaranteed imported by caller
    try:
        import numpy as np
    except ImportError:
        return 0.0, 0.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        return 0.0, 0.0

    # Height of the DMD crop window in source pixels (at native source width).
    # If the ROI is taller than this, the whole body cannot fit in one frame.
    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio

    # ── Face-priority constants ───────────────────────────────────────────────
    # DMD_CROP_H_FACTOR: body must be at least this multiple of dmd_crop_h
    # before face priority kicks in.  0.80 means "at least 80 % as tall as the
    # DMD window" — catches characters that would be cropped even slightly.
    DMD_CROP_H_FACTOR: float = 0.80
    # FACE_FRAC: fraction of body height estimated to contain the face + head
    # (head + neck + upper shoulders).  0.32 works well for both realistic and
    # anime/game characters where the head is relatively large.
    FACE_FRAC: float = 0.32

    step = max(1, total_frames // sample_count)
    roi_tops: list[float]    = []
    roi_bottoms: list[float] = []   # may be face-bottom when face priority
    roi_heights: list[float] = []
    roi_widths: list[float]  = []
    face_priority_count: int = 0    # frames where body > DMD window

    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

    for i in range(0, min(total_frames - 1, sample_count * step), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        roi = detector.detect(frame, cfg.detector)
        if roi is not None:
            rx, ry, rw, rh = roi
            roi_tops.append(float(ry))
            roi_heights.append(float(rh))
            roi_widths.append(float(rw))

            # Face priority check: is the body taller than the DMD window?
            if rh > dmd_crop_h * DMD_CROP_H_FACTOR:
                # Body too tall — only include the head/face region (top FACE_FRAC)
                # as the effective content bottom for this frame.
                roi_bottoms.append(float(ry + rh * FACE_FRAC))
                face_priority_count += 1
            else:
                # Body fits — include actual feet.
                roi_bottoms.append(float(ry + rh))

    # Restore capture position
    cap.set(cv2.CAP_PROP_POS_FRAMES, saved_pos)

    if not roi_tops:
        return 0.0, 0.0

    # ── Face priority mode decision ───────────────────────────────────────────
    # Activated when the majority of sampled frames have a body that is too
    # tall for the DMD window.
    face_priority = face_priority_count > len(roi_tops) * 0.5

    # ── Content-type inference ────────────────────────────────────────────────
    # Face/close-up: median aspect ratio (h/w) close to 1.0  → subject is compact.
    # Full body:     median aspect ratio >> 1 (tall & narrow) → need more headroom.
    median_h = float(np.median(roi_heights))
    median_w = float(np.median(roi_widths)) if roi_widths else max(1.0, median_h)
    aspect   = median_h / max(1.0, median_w)

    # Padding multiplier
    # Face priority mode → treat as face content regardless of raw aspect ratio
    # (the effective content is now the head region).
    if face_priority:
        # Generous head-region padding — ensure forehead is not clipped.
        pad_frac = 0.12
    elif aspect < 1.3:
        # Close-up / face-like ROI
        pad_frac = 0.15
    elif aspect < 2.5:
        # Intermediate (bust / upper body)
        pad_frac = 0.10
    else:
        # Full body (very tall ROI) that still fits in DMD window
        pad_frac = 0.06

    pad_px = frame_h * pad_frac

    # ── Percentile boundaries ─────────────────────────────────────────────────
    # 5th percentile of tops → where the subject reliably starts (head).
    # 95th percentile of bottoms → where the effective content ends.
    #   In face priority mode "bottom" is the estimated face-bottom, not the feet.
    top_y    = float(np.percentile(roi_tops,    5)) - pad_px
    bottom_y = float(np.percentile(roi_bottoms, 95)) + pad_px

    top_y    = max(0.0, top_y)
    bottom_y = min(float(frame_h), bottom_y)

    top_pct    = _clamp(top_y / frame_h, 0.0, 0.9)
    bottom_pct = _clamp((frame_h - bottom_y) / frame_h, 0.0, 0.9)

    return top_pct, bottom_pct


def _build_camera_rect(frame_w: int, frame_h: int, roi, cfg: AutoActionConfig,
                       floor_y_est: Optional[float] = None,
                       frame_top: float = 0.0):
    """Compute target camera rect at target_ratio based on ROI + user strength.

    Always returns a rect where cw / ch == target_ratio exactly so that the
    subsequent cv2.resize(cropped, (out_w, out_h)) never stretches the image.

    Vertical positioning priority (highest → lowest):
      1. auto_vertical_bias=True + floor_y_est provided
                               → dynamic floor-aware placement via _FloorEstimator
      2. auto_vertical_bias=True (no floor_y_est)
                               → per-frame roi bottom at ~93 % of crop (fallback)
      3. vertical_bias != 0    → manual lerp toward top/bottom edge
      4. neither               → follow ROI center (or frame center when no ROI)

    Parameters
    ----------
    frame_top : float
        Y-coordinate of the top boundary for camera motion (pixels).
        Set to ``frame_h * top_crop_pct`` so the camera never pans above the
        top-crop line.  Default 0.0 = no top restriction.
    """
    target_ratio = float(cfg.target_width) / cfg.target_height
    _bias = _clamp(getattr(cfg, "vertical_bias", 0.0), -1.0, 1.0)
    _auto = getattr(cfg, "auto_vertical_bias", False)

    # Fraction of crop height at which the estimated floor should appear.
    # 0.93 means the floor is 93 % down from the top of the visible strip
    # (≈ 7 % margin at the bottom) — aggressive enough to show the ground in
    # most 2-D platformers without risking clipping below the frame.
    _FLOOR_RATIO: float = 0.93

    def _cy_min(crop_h: float) -> float:
        """Minimum camera centre y: never pan above the top-crop line."""
        return max(crop_h / 2.0, frame_top + crop_h / 2.0)

    def _cy_max(crop_h: float) -> float:
        return float(frame_h) - crop_h / 2.0

    def _apply_bias(cy: float, crop_h: float) -> float:
        """Lerp camera center toward frame top (-) or bottom (+).
        bias=+1.0 → camera as low as possible (floor visible).
        bias=-1.0 → camera as high as possible.
        Expressed as fraction of available vertical travel so it works
        independently of zoom level.
        """
        if abs(_bias) < 1e-4:
            return cy
        target_cy = _cy_max(crop_h) if _bias > 0 else _cy_min(crop_h)
        cy = cy + _bias * (target_cy - cy)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    def _apply_auto_floor(cy: float, floor_y: float, crop_h: float) -> float:
        """Place floor_y at _FLOOR_RATIO from the top of the crop window.

        floor_y = cy - crop_h/2 + floor_ratio * crop_h
        → cy     = floor_y + crop_h * (0.5 - floor_ratio)
        """
        cy = floor_y + crop_h * (0.5 - _FLOOR_RATIO)
        return _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    if roi is None:
        # No ROI — full-frame overview centered.
        cx = frame_w / 2.0
        cy = (frame_top + frame_h) / 2.0
        crop_h = min(float(frame_h) - frame_top, float(frame_w) / target_ratio)
        crop_w = crop_h * target_ratio
        if _auto:
            if floor_y_est is not None:
                # We have a memorised floor level: use it even without a live ROI
                # so the camera stays anchored when the subject briefly leaves frame.
                cy = _apply_auto_floor(cy, floor_y_est, crop_h)
            else:
                # No estimate yet: lean aggressively downward (65 % toward bottom).
                cy_max = _cy_max(crop_h)
                cy = cy + 0.65 * (cy_max - cy)
                cy = _clamp(cy, _cy_min(crop_h), cy_max)
        else:
            cy = _apply_bias(cy, crop_h)
        return cx, cy, crop_w, crop_h

    x, y, w, h = roi
    cx = x + w / 2.0
    cy = y + h / 2.0

    # Convert detector strength into zoom demand.
    strength = _clamp(cfg.strength, 0.0, 1.0)
    zoom = 1.0 + strength * (max(1.0, cfg.zoom_max) - 1.0)

    # Start from ROI bounds with extra padding, expanded to target aspect ratio.
    roi_w = max(16.0, w * (1.0 + cfg.padding))
    roi_h = max(8.0,  h * (1.0 + cfg.padding))
    if roi_w / roi_h < target_ratio:
        roi_w = roi_h * target_ratio
    else:
        roi_h = roi_w / target_ratio

    # Apply zoom factor (higher zoom → smaller crop window).
    crop_w = roi_w / zoom
    crop_h = roi_h / zoom

    # Hard minimum: never zoom beyond zoom_max regardless of ROI size.
    min_crop_w = max(float(cfg.target_width) / 4,
                     float(frame_w) / max(1.0, cfg.zoom_max))
    min_crop_h = min_crop_w / target_ratio
    crop_w = max(crop_w, min_crop_w)
    crop_h = max(crop_h, min_crop_h)

    # ── Enforce exact aspect ratio ──────────────────────────────────────────
    # Derive crop_w from crop_h. If that exceeds frame_w, cap at frame_w and
    # recompute crop_h — this guarantees cw/ch == target_ratio always.
    crop_w = crop_h * target_ratio
    if crop_w > float(frame_w):
        crop_w = float(frame_w)
        crop_h = float(frame_w) / target_ratio

    # ── Vertical positioning ────────────────────────────────────────────────
    if _auto:
        # Use the pre-smoothed floor estimate when available (supplied by the
        # main loop via _FloorEstimator); fall back to raw roi bottom otherwise.
        fy = floor_y_est if floor_y_est is not None else float(y + h)
        cy = _apply_auto_floor(cy, fy, crop_h)
    else:
        cy = _apply_bias(cy, crop_h)

    # Final safety clamp: ensures cy stays within the effective vertical range
    # [frame_top + ch/2, frame_h - ch/2] regardless of ROI position.
    cy = _clamp(cy, _cy_min(crop_h), _cy_max(crop_h))

    return cx, cy, crop_w, crop_h


def _smooth(prev, curr, smoothness: float):
    if prev is None:
        return curr
    a = _clamp(smoothness, 0.0, 0.98)
    return tuple((a * p) + ((1.0 - a) * c) for p, c in zip(prev, curr))


def _crop_frame(frame, cam_rect):
    """Crop frame to cam_rect, always returning a region of exactly
    round(cw) × round(ch) pixels (no dimension drift from push-back)."""
    h, w = frame.shape[:2]
    cx, cy, cw, ch = cam_rect

    # Pin output dimensions first — avoid the dimension-drift that occurs when
    # independent rounding of (cx±cw/2) produces a width ≠ round(cw).
    out_w = max(1, int(round(cw)))
    out_h = max(1, int(round(ch)))

    # Top-left corner from centre.
    x1 = int(round(cx - cw / 2.0))
    y1 = int(round(cy - ch / 2.0))

    # Push-back: move the window (not resize) to stay inside the frame.
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

    # Safety clamp (only needed when out_w > w or out_h > h).
    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return frame
    return frame[y1:y2, x1:x2]


def _smart_auto_crop_decision(
    cap,
    cfg: "AutoActionConfig",
    frame_w: int,
    frame_h: int,
    sample_count: int = 25,
) -> dict:
    """Analyse video context and decide which crop/tracking combination to activate.

    Scans ``sample_count`` evenly-spaced frames, collects ROI metrics, and returns
    a ready-to-use decision dict.  The decision logic handles the key contradiction:

    • **Tall character** (face priority zone) → **no** floor-tracking (we want the
      face, not the floor).  auto_bottom_crop is enabled to trigger face-priority;
      auto_vertical_bias is kept OFF so the camera stays on the head region.
    • **Normal-height character on a floor** → auto_bottom_crop (HUD/tile exclusion)
      + auto_vertical_bias (asymmetric EMA floor anchor).
    • **Blank top space** (sky / ceiling / HUD) → auto_top_crop.

    This function **also pre-computes the crop percentages** (top_pct, bottom_pct)
    using the same percentile logic as ``_compute_auto_crop_margins`` so that the
    caller can skip the second scan entirely.  The pre-computed values are only
    meaningful when the corresponding auto flag is True.

    Parameters
    ----------
    cap           : cv2.VideoCapture (already open — position will be restored)
    cfg           : AutoActionConfig
    frame_w / frame_h : source frame dimensions
    sample_count  : frames to analyse (default 25 — fast, ~0.3 s extra)

    Returns
    -------
    dict with keys:
        auto_bottom_crop   : bool
        auto_top_crop      : bool
        auto_vertical_bias : bool
        top_pct            : float  — pre-computed top crop percentage   (0..0.9)
        bottom_pct         : float  — pre-computed bottom crop percentage (0..0.9)
        reasons            : list[str]  — human-readable log entries
    """
    _EMPTY = {"auto_bottom_crop": False, "auto_top_crop": False,
              "auto_vertical_bias": False, "top_pct": 0.0, "bottom_pct": 0.0}

    try:
        import cv2
        import numpy as np
    except ImportError:
        return {**_EMPTY, "reasons": ["OpenCV/NumPy unavailable — smart auto skipped"]}

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total_frames <= 0:
        return {**_EMPTY, "reasons": ["no frames available — smart auto skipped"]}

    # Height of the DMD crop window in source pixels (same formula as the main loop).
    target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
    dmd_crop_h   = frame_w / target_ratio  # pixels

    step      = max(1, total_frames // sample_count)
    saved_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)
    try:
        detector = _FrameDetector()
    except Exception:
        # Detector init failed (e.g. OpenCV issue): return safe defaults.
        return {**_EMPTY, "reasons": ["detector init failed — smart auto skipped"]}

    roi_tops:         list[float] = []
    roi_bottoms_feet: list[float] = []   # actual feet (used for floor/gap signals)
    roi_bottoms_fp:   list[float] = []   # face-priority adjusted bottom (for crop margin)
    roi_heights:      list[float] = []
    roi_widths:       list[float] = []

    # ── Face-priority constants (same as _compute_auto_crop_margins) ──────────
    DMD_CROP_H_FACTOR: float = 0.80   # body must be ≥ 80 % of dmd window to trigger
    FACE_FRAC:         float = 0.32   # top fraction of body estimated to be head/face

    for i in range(0, min(total_frames - 1, sample_count * step), step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(i))
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        roi = detector.detect(frame, cfg.detector)
        if roi is not None:
            _rx, ry, rw, rh = roi
            roi_tops.append(float(ry))
            roi_bottoms_feet.append(float(ry + rh))
            roi_heights.append(float(rh))
            roi_widths.append(float(rw))
            # Face-priority adjusted bottom (same logic as _compute_auto_crop_margins)
            if rh > dmd_crop_h * DMD_CROP_H_FACTOR:
                roi_bottoms_fp.append(float(ry + rh * FACE_FRAC))
            else:
                roi_bottoms_fp.append(float(ry + rh))

    cap.set(cv2.CAP_PROP_POS_FRAMES, saved_pos)

    if not roi_tops:
        return {**_EMPTY, "reasons": ["no detections in scan — all manual"]}

    arr_tops       = np.array(roi_tops)
    arr_btm_feet   = np.array(roi_bottoms_feet)
    arr_btm_fp     = np.array(roi_bottoms_fp)
    arr_heights    = np.array(roi_heights)
    arr_widths     = np.array(roi_widths) if roi_widths else arr_heights

    median_top    = float(np.median(arr_tops))
    median_bottom = float(np.median(arr_btm_feet))   # feet for floor/gap signals
    median_height = float(np.median(arr_heights))
    std_bottom    = float(np.std(arr_btm_feet))

    # ── Decision thresholds ───────────────────────────────────────────────────
    # TOP_SPACE: fraction of frame height blank above the subject → auto-top-crop.
    TOP_SPACE_THRESH  = 0.08   # 8 % blank at top
    # BOTTOM_GAP: fraction below feet → HUD / floor tiles → auto-bottom-crop.
    BOTTOM_GAP_THRESH = 0.08   # 8 % blank below feet
    # TALL_FACTOR: char height / dmd_crop_h — above = face priority needed.
    TALL_FACTOR       = 0.70
    # FLOOR_LOWER: subject bottom must be in the lower 50 % for floor-tracking.
    FLOOR_LOWER       = 0.50
    # FLOOR_VAR: std(floor_y) / frame_h — above = very dynamic (lots of jumping),
    # still trackable thanks to the asymmetric EMA.
    FLOOR_VAR_MAX     = 0.25   # above 25 % variance = extremely chaotic → skip

    # ── Derived signals ───────────────────────────────────────────────────────
    top_space       = median_top    / frame_h
    bottom_gap      = (frame_h - median_bottom) / frame_h
    tall_ratio      = median_height / max(1.0, dmd_crop_h)
    floor_in_lower  = (median_bottom / frame_h) > FLOOR_LOWER
    floor_var_score = std_bottom / frame_h

    # ── Decision ──────────────────────────────────────────────────────────────
    reasons:     list[str] = []
    auto_bottom  = False
    auto_top     = False
    auto_floor   = False

    # 1. Top space → auto-top-crop
    if top_space > TOP_SPACE_THRESH:
        auto_top = True
        reasons.append(
            f"top-space {top_space*100:.0f}% > {TOP_SPACE_THRESH*100:.0f}% "
            f"→ auto-top-crop ✓"
        )

    # 2a. Tall character (face priority zone)
    #     Contradiction: floor-tracking anchors to feet; face-priority needs the
    #     camera on the head → disable floor-tracking when face priority triggers.
    if tall_ratio > TALL_FACTOR:
        auto_bottom = True
        reasons.append(
            f"tall-char {tall_ratio*100:.0f}% of DMD window "
            f"→ auto-bottom-crop + face-priority ✓  /  floor-track ✗ (contradictory)"
        )
        # auto_floor intentionally stays False

    else:
        # 2b. Normal-height subject: bottom clutter → auto-bottom-crop
        if bottom_gap > BOTTOM_GAP_THRESH:
            auto_bottom = True
            reasons.append(
                f"bottom-gap {bottom_gap*100:.0f}% > {BOTTOM_GAP_THRESH*100:.0f}% "
                f"(floor/HUD) → auto-bottom-crop ✓"
            )

        # 3. Floor is in the lower half and variance is manageable → floor-tracking.
        #    Asymmetric EMA resists upward jumps and follows landings — works for
        #    both stable floors and dynamic platformers.
        if floor_in_lower and floor_var_score <= FLOOR_VAR_MAX:
            auto_floor = True
            stability = "stable" if floor_var_score < 0.10 else "dynamic"
            reasons.append(
                f"floor@{median_bottom/frame_h*100:.0f}% "
                f"var={floor_var_score*100:.0f}% ({stability}) "
                f"→ auto-floor-tracking ✓"
            )
        elif floor_in_lower and floor_var_score > FLOOR_VAR_MAX:
            reasons.append(
                f"floor@{median_bottom/frame_h*100:.0f}% "
                f"var={floor_var_score*100:.0f}% (too chaotic) "
                f"→ floor-track ✗ (high variance)"
            )

    if not reasons:
        reasons.append(
            f"centered subject — no clutter detected "
            f"(top={top_space*100:.0f}% bot={bottom_gap*100:.0f}% "
            f"h={tall_ratio*100:.0f}%) → all manual"
        )

    # ── Pre-compute crop percentages (same percentile logic as _compute_auto_crop_margins)
    # This lets the caller skip the second scan entirely when smart_auto_crop=True.
    # Aspect-ratio-based padding (mirrors _compute_auto_crop_margins).
    median_w   = float(np.median(arr_widths)) if len(arr_widths) > 0 else max(1.0, median_height)
    aspect     = median_height / max(1.0, median_w)
    face_priority = tall_ratio > TALL_FACTOR
    if face_priority:
        pad_frac = 0.12
    elif aspect < 1.3:
        pad_frac = 0.15
    elif aspect < 2.5:
        pad_frac = 0.10
    else:
        pad_frac = 0.06
    pad_px = frame_h * pad_frac

    # Use face-priority-adjusted bottoms for margin computation.
    top_y    = float(np.percentile(arr_tops,    5))  - pad_px
    bottom_y = float(np.percentile(arr_btm_fp, 95))  + pad_px
    top_y    = max(0.0,          top_y)
    bottom_y = min(float(frame_h), bottom_y)

    pre_top_pct    = _clamp(top_y    / frame_h,              0.0, 0.9)
    pre_bottom_pct = _clamp((frame_h - bottom_y) / frame_h,  0.0, 0.9)

    return {
        "auto_bottom_crop":   auto_bottom,
        "auto_top_crop":      auto_top,
        "auto_vertical_bias": auto_floor,
        "top_pct":            pre_top_pct,
        "bottom_pct":         pre_bottom_pct,
        "reasons":            reasons,
    }


def preprocess_video_for_dmd(src_path: str, cfg: AutoActionConfig):
    """Create an auto-framed temporary MP4 and return (ok, out_path, message).

    Frames are processed by OpenCV and piped directly to an FFmpeg subprocess
    via stdin as raw BGR24 video — no cv2.VideoWriter, no bulky mp4v temp file.
    The intermediate MP4 is encoded with H.264 (ultrafast preset), which is
    ~5–10× smaller than the old mp4v output and ~30 % faster to produce.

    Returns:
      - ok=True: out_path is an existing intermediate video.
      - ok=False: out_path is None, message explains fallback reason.
    """
    try:
        import cv2
    except Exception:
        return False, None, "OpenCV not installed (install opencv-python to enable auto action framing)."

    if cfg.detector.lower() not in available_detectors():
        cfg.detector = "person"

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        return False, None, "Could not open source for action preprocessing."

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fps = max(1.0, float(fps))
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if frame_w <= 0 or frame_h <= 0:
        cap.release()
        return False, None, "Invalid source dimensions for action preprocessing."

    # Output at native source resolution with target_width:target_height crop ratio.
    # Keeping the native resolution here means ffmpeg receives full-quality input
    # and performs the final downscale to target_width x target_height with all its colour filters.
    out_w = frame_w
    # Calculate out_h based on the desired target aspect ratio
    target_aspect_ratio = float(cfg.target_width) / cfg.target_height
    out_h = max(8, (frame_w // int(target_aspect_ratio) // 2) * 2)  # even number, matching target aspect ratio
    # This avoids framing being dragged down by feet/floor/subtitles/HUD elements.
    _bcp = _clamp(getattr(cfg, "bottom_crop_pct", 0.0), 0.0, 0.9)
    _tcp = _clamp(getattr(cfg, "top_crop_pct", 0.0), 0.0, 0.9)

    # ── Auto crop margins ─────────────────────────────────────────────────────
    # When auto_bottom_crop or auto_top_crop is enabled, sample the video to
    # compute the tightest crop that still contains the full subject (face or
    # full body), then override the manual crop percentages.
    _auto_bc = getattr(cfg, "auto_bottom_crop", False)
    _auto_tc = getattr(cfg, "auto_top_crop", False)
    _smart_reasons: list[str] = []

    # ── Smart Auto Crop decision (overrides individual flags) ─────────────────
    # When smart_auto_crop=True the engine analyses 25 frames to decide which
    # combination of auto_bottom_crop / auto_top_crop / auto_vertical_bias to
    # activate, AND pre-computes the crop percentages in the same pass so that
    # the second _compute_auto_crop_margins scan is skipped entirely.
    # This halves the scanning overhead compared to running two separate scans.
    # The entire block is wrapped in a try/except so that any unexpected error
    # (ONNX load failure, network timeout, OpenCV issue) degrades gracefully to
    # "all manual" instead of propagating an exception to the preview thread.
    _smart_crop_margins: Optional[tuple] = None   # (top_pct, bottom_pct) or None
    if getattr(cfg, "smart_auto_crop", False):
        try:
            _decision = _smart_auto_crop_decision(cap, cfg, frame_w, frame_h)
            _auto_bc                  = _decision["auto_bottom_crop"]
            _auto_tc                  = _decision["auto_top_crop"]
            cfg.auto_vertical_bias    = _decision["auto_vertical_bias"]
            _smart_reasons            = _decision["reasons"]
            # Use pre-computed margins from the smart scan — no second pass needed.
            _smart_crop_margins = (_decision["top_pct"], _decision["bottom_pct"])
        except Exception as _e:
            # Graceful fallback: smart scan failed — keep individual manual flags.
            _smart_reasons = [f"smart scan error ({_e!r}) → all manual"]

    _face_priority_mode = False  # will be set True if face priority was triggered
    if _auto_bc or _auto_tc:
        try:
            if _smart_crop_margins is not None:
                # Smart scan already computed the margins — reuse them directly.
                computed_top, computed_bottom = _smart_crop_margins
            else:
                # Individual auto flags (no smart scan): run the dedicated margin scan.
                detector_for_scan = _FrameDetector()
                computed_top, computed_bottom = _compute_auto_crop_margins(
                    cap, detector_for_scan, cfg, frame_w, frame_h
                )
            if _auto_tc:
                _tcp = computed_top
            if _auto_bc:
                _bcp = computed_bottom
                # Face priority detection: if the effective visible height is
                # significantly smaller than the DMD window height, the auto-scan
                # must have applied face priority (body was too tall to fit).
                _target_ratio = float(cfg.target_width) / max(1, cfg.target_height)
                _dmd_window_h = frame_w / _target_ratio
                _effective_h  = frame_h * (1.0 - _bcp) - frame_h * _tcp
                _face_priority_mode = _effective_h < _dmd_window_h * 0.75
        except Exception as _e:
            # Graceful fallback: crop margin scan failed — use manual values.
            pass

    effective_frame_top = int(frame_h * _tcp)
    effective_frame_h   = max(cfg.target_height, int(frame_h * (1.0 - _bcp)))

    initial_start_s = cfg.start_s if cfg.start_s is not None else 0.0
    if initial_start_s > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    # ── FFmpeg rawvideo pipe — replaces cv2.VideoWriter ───────────────────────
    # Frames are sent as BGR24 rawvideo to FFmpeg's stdin.  FFmpeg encodes them
    # to H.264/MP4 directly, eliminating all intermediate disk I/O for raw frames
    # and producing a temp file ~5–10× smaller than the old mp4v output.
    tmpdir   = tempfile.mkdtemp(prefix="dmd_action_")
    out_path = os.path.join(tmpdir, "action_pre.mp4")

    _fps_str = f"{fps:.6f}"
    _pipe_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{out_w}x{out_h}",
        "-r", _fps_str,
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    try:
        ffmpeg_proc = subprocess.Popen(
            _pipe_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        cap.release()
        return False, None, f"Could not start FFmpeg pipe for action preprocessing: {exc}"

    # Helper: write a frame to the pipe; returns False on broken pipe (FFmpeg died).
    def _write_frame(f) -> bool:
        try:
            ffmpeg_proc.stdin.write(f.tobytes())
            return True
        except (BrokenPipeError, OSError):
            return False

    detector = _FrameDetector()

    # Full-frame overview rect: widest target_width:target_height crop centred on the source.
    # Uses effective_frame_h so the intro never pans into the bottom-cropped region.
    # Uses effective_frame_top so the intro never pans above the top-cropped region.
    cam_full_view = _build_camera_rect(frame_w, effective_frame_h, None, cfg,
                                       frame_top=float(effective_frame_top))

    # ── Intro frame count — capped relative to source length ─────────────────
    # A fixed intro_duration can dominate very short sources (e.g. a 0.5 s GIF
    # would get a 1.5 s frozen intro = 3× the source length).
    # Cap intro to at most 40 % of total source frames so the action-tracking
    # phase always has the majority of the output.
    total_frames_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    intro_frames = max(0, int(round(cfg.intro_duration * fps)))
    if total_frames_src > 0:
        max_intro = max(1, int(total_frames_src * 0.40))
        intro_frames = min(intro_frames, max_intro)

    last_frame = None
    frame_idx  = 0
    extra      = 0
    _pipe_alive = True  # tracks whether the FFmpeg pipe is still writable

    # Read the very first frame of the segment for intro (if any).
    ok_first, first_frame_for_intro = cap.read()
    if not ok_first:
        cap.release()
        try:
            ffmpeg_proc.stdin.close()
            ffmpeg_proc.wait()
        except Exception:
            pass
        return False, None, "Could not read first frame for intro."

    # ── Background subtractor warm-up ─────────────────────────────────────────
    # MOG2 starts with no background model: the very first frames it processes
    # either return an all-foreground mask (everything visible) or an all-zero
    # mask (black flash), depending on the internal state of the Gaussian mixture.
    #
    # Fix: before outputting a single frame, prime the model by replaying the
    # first frame 30× at a high learning-rate (0.5).  After this the model has
    # a solid estimate of the static background and produces clean masks from
    # frame 1 of the actual output.
    if cfg.bg_sub_enable:
        _wf = first_frame_for_intro
        if max(_wf.shape[0], _wf.shape[1]) > 512:
            _sf = 512 / max(_wf.shape[0], _wf.shape[1])
            _wf = cv2.resize(
                _wf,
                (int(_wf.shape[1] * _sf), int(_wf.shape[0] * _sf)),
                interpolation=cv2.INTER_AREA,
            )
        _BG_WARMUP_ITERS = 30
        for _ in range(_BG_WARMUP_ITERS):
            detector.bg_sub.apply(_wf, learningRate=0.5)

    # ── Phase 1: Intro panoramic pan (frozen first frame, top → centre) ──────
    # The first source frame is held for intro_frames while the camera pans
    # from the TOP of the frame down to the CENTRE (smoothstep easing).
    # NOTE: background subtraction is intentionally skipped here — the intro
    # is a static frozen frame, so MOG2 would just darken it progressively as
    # the model learns the content as "background".  Full frame shown instead.
    if intro_frames > 0 and _pipe_alive:
        cx, cy_center, crop_w_full, crop_h_src = cam_full_view
        cy_top = crop_h_src / 2.0

        for i in range(intro_frames):
            t_linear = i / max(1, intro_frames - 1)
            t = t_linear * t_linear * (3.0 - 2.0 * t_linear)
            cy = cy_top + t * (cy_center - cy_top)
            cam_intro = (cx, cy, crop_w_full, crop_h_src)
            cropped_frame = _crop_frame(first_frame_for_intro, cam_intro)

            out_frame = cv2.resize(cropped_frame, (out_w, out_h),
                                   interpolation=cv2.INTER_LANCZOS4)
            if not _write_frame(out_frame):
                _pipe_alive = False
                break
            frame_idx += 1

        last_frame = first_frame_for_intro  # last_frame for tail extension

    # Ensure the capture is at the correct start_s for the main tracking phase.
    cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    # ── Phase 2: Action tracking (full source from frame 0) ───────────────────
    # Camera starts at cam_full_view so the transition from the intro is smooth.
    cam_prev = cam_full_view
    cam_now  = cam_full_view
    src_idx  = 0

    # Dynamic floor estimator: active only when auto_vertical_bias is on.
    _floor_est: Optional[_FloorEstimator] = (
        _FloorEstimator(effective_frame_h) if cfg.auto_vertical_bias else None
    )

    while _pipe_alive:
        ok, frame = cap.read()
        if not ok:
            break

        t = src_idx / fps
        if cfg.end_s is not None and (initial_start_s + t) >= float(cfg.end_s):
            break

        # Detect ROI on the original frame, restricted to the non-cropped area.
        detect_frame = frame[effective_frame_top:effective_frame_h, :]
        roi = detector.detect(detect_frame, cfg.detector)

        # Translate ROI y-coordinate back into original frame space.
        if roi is not None and effective_frame_top > 0:
            rx, ry, rw, rh = roi
            roi = (rx, ry + effective_frame_top, rw, rh)

        # Update floor estimate (asymmetric EMA) and forward it to the camera.
        floor_y_est: Optional[float] = None
        if _floor_est is not None:
            roi_bottom = float(roi[1] + roi[3]) if roi is not None else None
            floor_y_est = _floor_est.update(roi_bottom)

        cam_now = _build_camera_rect(frame_w, effective_frame_h, roi, cfg,
                                     floor_y_est=floor_y_est,
                                     frame_top=float(effective_frame_top))
        cam = _smooth(cam_prev, cam_now, cfg.smoothness)
        cam_prev = cam
        last_frame = frame

        cropped_frame = _crop_frame(frame, cam)

        # Apply background subtraction if enabled
        if cfg.bg_sub_enable:
            bs_frame = cropped_frame
            if max(cropped_frame.shape[0], cropped_frame.shape[1]) > 512:
                scale_factor_bs = 512 / max(cropped_frame.shape[0], cropped_frame.shape[1])
                bs_frame = cv2.resize(cropped_frame, (int(cropped_frame.shape[1] * scale_factor_bs), int(cropped_frame.shape[0] * scale_factor_bs)), interpolation=cv2.INTER_AREA)

            fg_mask = detector.bg_sub.apply(bs_frame)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
            fg_mask = cv2.resize(fg_mask, (cropped_frame.shape[1], cropped_frame.shape[0]), interpolation=cv2.INTER_LINEAR)
            cropped_frame = cv2.bitwise_and(cropped_frame, cropped_frame, mask=fg_mask)

        out_frame = cv2.resize(cropped_frame, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        if not _write_frame(out_frame):
            _pipe_alive = False
            break
        frame_idx += 1
        src_idx   += 1

    # ── Tail extension: freeze last frame while camera settles ────────────────
    # Kept intentionally short (≤ 0.3 s) because this output is a looping GIF:
    # long tails create a visible freeze before the loop restarts.
    # NOTE: background subtraction is skipped here — applying MOG2 to a repeated
    # static frame would progressively darken the output as the model reclassifies
    # the content as background.
    if last_frame is not None and cam_prev is not None and cam_now is not None and _pipe_alive:
        max_extra = max(1, int(fps * 0.3))   # hard cap: 0.3 s
        settle_px = 1.0                       # stop when camera moves < 1 px/frame
        extra = 0
        while extra < max_extra:
            cam_next = _smooth(cam_prev, cam_now, cfg.smoothness)
            displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
            cam_prev = cam_next
            cropped_frame = _crop_frame(last_frame, cam_next)

            out_frame = cv2.resize(cropped_frame, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            if not _write_frame(out_frame):
                break
            frame_idx += 1
            extra += 1
            if displacement < settle_px:
                break   # camera has settled — no more extension needed

    # ── Finalise FFmpeg pipe ───────────────────────────────────────────────────
    try:
        ffmpeg_proc.stdin.close()
    except Exception:
        pass
    ffmpeg_rc = ffmpeg_proc.wait()
    cap.release()

    if ffmpeg_rc != 0 or frame_idx <= 0 or not os.path.isfile(out_path):
        return False, None, "FFmpeg pipe encoding failed during action preprocessing."

    tail_info  = f" +{extra}t"     if extra > 0       else ""
    intro_info = f" +{intro_frames}i" if intro_frames > 0 else ""
    crop_info  = ""
    if _tcp > 0.0 or _bcp > 0.0:
        auto_suffix_t = "▲auto" if _auto_tc else "▲manual"
        auto_suffix_b = "▼auto" if _auto_bc else "▼manual"
        face_info = " [face priority 👤]" if _face_priority_mode else ""
        crop_info = (
            f", top={_tcp:.0%}{auto_suffix_t}"
            f" bot={_bcp:.0%}{auto_suffix_b}{face_info}"
        )
    onnx_tag = " [ONNX]" if detector._onnx_session is not None else " [motion]"
    smart_tag = ""
    if getattr(cfg, "smart_auto_crop", False) and _smart_reasons:
        smart_tag = " [smart:" + " / ".join(_smart_reasons) + "]"
    return True, out_path, (
        f"Auto action OK ({frame_idx} frames{intro_info}{tail_info}, "
        f"{out_w}×{out_h}, detector={cfg.detector}{onnx_tag}{crop_info}{smart_tag})."
    )

