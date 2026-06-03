#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto action framing preprocessor (outside ffmpeg pipeline).

This module detects action/person regions frame-by-frame and generates a
cinematic 4:1 intermediate video before the regular ffmpeg DMD conversion.
"""

from __future__ import annotations

import os
import platform
import sys
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np # Import numpy

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
    bg_sub_enable: bool = False       # enable background subtraction (replaces background with black)
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
    """Detector backend for person/motion ROI extraction."""

    def __init__(self):
        import cv2  # local import: module remains importable without OpenCV

        self.cv2 = cv2
        self.prev_gray = None

        # HOGDescriptor.detectMultiScale crashes on macOS ARM64 (Apple Silicon)
        # with SIGBUS / KERN_PROTECTION_FAILURE in cv::HOGCache::getBlock.
        #
        # Root cause: OpenCV's internal cv::parallel_for_ uses Apple Grand
        # Central Dispatch (GCD) on macOS, which always dispatches multiple
        # worker threads regardless of cv2.setNumThreads().  The NEON-optimised
        # HOG code then hits a buffer-overflow past a MALLOC_SMALL heap boundary,
        # producing a hard crash that Python cannot catch.
        #
        # Fix: disable HOG entirely on macOS ARM64.  The motion detector is used
        # as sole fallback on that platform.
        self._hog_enabled = not (
            sys.platform == "darwin" and platform.machine() == "arm64"
        )

        # Lightweight person detector (OpenCV HOG + SVM), no extra model files.
        if self._hog_enabled:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        else:
            self.hog = None

        # MOG2 background subtractor for motion detection and background removal
        self.bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=36)

    def detect_person(self, frame) -> Optional[Tuple[int, int, int, int]]:
        # HOG disabled on macOS ARM64 — caller falls back to motion detection.
        if not self._hog_enabled:
            return None

        cv2 = self.cv2
        h, w = frame.shape[:2]
        scale = 0.5 if max(w, h) > 960 else 1.0
        if abs(scale - 1.0) > 1e-6:
            small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        else:
            small = frame

        boxes, weights = self.hog.detectMultiScale(
            small,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )

        if len(boxes) == 0:
            return None

        best_i = max(range(len(boxes)), key=lambda i: float(weights[i]))
        x, y, bw, bh = boxes[best_i]
        if abs(scale - 1.0) > 1e-6:
            x = int(x / scale)
            y = int(y / scale)
            bw = int(bw / scale)
            bh = int(bh / scale)
        return (x, y, bw, bh)

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


def _build_camera_rect(frame_w: int, frame_h: int, roi, cfg: AutoActionConfig):
    """Compute target camera rect at 4:1 ratio based on ROI + user strength."""
    target_ratio = float(cfg.target_width) / cfg.target_height

    if roi is None:
        # Keep source center when no ROI is available.
        cx = frame_w / 2.0
        cy = frame_h / 2.0
        # Fit widest target_ratio crop possible.
        crop_h = min(frame_h, frame_w / target_ratio)
        crop_w = crop_h * target_ratio
        return cx, cy, crop_w, crop_h

    x, y, w, h = roi
    cx = x + w / 2.0
    cy = y + h / 2.0

    # Convert detector strength into zoom demand.
    # 0.0 => very loose framing, 1.0 => tight framing (up to zoom_max)
    strength = _clamp(cfg.strength, 0.0, 1.0)
    zoom = 1.0 + strength * (max(1.0, cfg.zoom_max) - 1.0)

    # Start from ROI bounds with extra padding.
    roi_w = max(16.0, w * (1.0 + cfg.padding))
    roi_h = max(8.0, h * (1.0 + cfg.padding))

    # Expand to target aspect ratio.
    if roi_w / roi_h < target_ratio:
        roi_w = roi_h * target_ratio
    else:
        roi_h = roi_w / target_ratio

    # Apply zoom factor (higher zoom -> smaller crop window).
    crop_w = roi_w / zoom
    crop_h = roi_h / zoom

    # Keep inside frame bounds — and enforce zoom_max as a hard minimum crop
    # size so the camera never zooms in beyond zoom_max times regardless of
    # how small the detected ROI is (e.g. distant face, tiny sprite).
    # min_crop_h is derived from min_crop_w at target_ratio to keep the constraints
    # coherent and avoid the aspect-ratio fixup widening the crop back out.
    min_crop_w = max(float(cfg.target_width) / 4, float(frame_w) / max(1.0, cfg.zoom_max))
    min_crop_h = max(float(cfg.target_height) / 4,  min_crop_w / target_ratio)
    crop_w = _clamp(crop_w, min_crop_w, float(frame_w))
    crop_h = _clamp(crop_h, min_crop_h, float(frame_h))

    if crop_w / crop_h < target_ratio:
        crop_w = min(frame_w, crop_h * target_ratio)
    else:
        crop_h = min(frame_h, crop_w / target_ratio)

    return cx, cy, crop_w, crop_h


def _smooth(prev, curr, smoothness: float):
    if prev is None:
        return curr
    a = _clamp(smoothness, 0.0, 0.98)
    return tuple((a * p) + ((1.0 - a) * c) for p, c in zip(prev, curr))


def _crop_frame(frame, cam_rect):
    h, w = frame.shape[:2]
    cx, cy, cw, ch = cam_rect

    x1 = int(round(cx - cw / 2.0))
    y1 = int(round(cy - ch / 2.0))
    x2 = int(round(cx + cw / 2.0))
    y2 = int(round(cy + ch / 2.0))

    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > w:
        x1 -= (x2 - w)
        x2 = w
    if y2 > h:
        y1 -= (y2 - h)
        y2 = h

    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(w, x2)
    y2 = min(h, y2)

    if x2 <= x1 or y2 <= y1:
        return frame
    return frame[y1:y2, x1:x2]


def preprocess_video_for_dmd(src_path: str, cfg: AutoActionConfig):
    """Create an auto-framed temporary MP4 and return (ok, out_path, message).

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
    out_h = max(8, (frame_w // int(target_aspect_ratio) // 2) * 2) # even number, matching target aspect ratio

    initial_start_s = cfg.start_s if cfg.start_s is not None else 0.0
    if initial_start_s > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    tmpdir = tempfile.mkdtemp(prefix="dmd_action_")
    out_path = os.path.join(tmpdir, "action_pre.mp4")
    writer = cv2.VideoWriter(
        out_path,
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (out_w, out_h),
    )

    if not writer.isOpened():
        cap.release()
        return False, None, "Could not create intermediate action video."

    detector = _FrameDetector()

    # Full-frame overview rect: widest target_width:target_height crop centred on the source.
    cam_full_view = _build_camera_rect(frame_w, frame_h, None, cfg)

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

    # Read the very first frame of the segment for intro (if any).
    # This advances the cap pointer by one frame.
    ok_first, first_frame_for_intro = cap.read()
    if not ok_first:
        cap.release()
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
    if intro_frames > 0:
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
            writer.write(out_frame)
            frame_idx += 1

        last_frame = first_frame_for_intro  # last_frame for tail extension

    # Ensure the capture is at the correct start_s for the main tracking phase.
    # This is crucial to ensure the main loop starts from the correct frame, regardless of intro being played or not.
    cap.set(cv2.CAP_PROP_POS_MSEC, float(initial_start_s) * 1000.0)

    # ── Phase 2: Action tracking (full source from frame 0) ───────────────────
    # Camera starts at cam_full_view so the transition from the intro is smooth.
    cam_prev = cam_full_view
    cam_now  = cam_full_view
    src_idx  = 0     # independent counter for end_s trimming
    # No need to adjust src_idx here, as cap.set() above resets the pointer.

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t = src_idx / fps
        if cfg.end_s is not None and (initial_start_s + t) >= float(cfg.end_s):
            break

        # Detect ROI on the original frame
        roi = detector.detect(frame, cfg.detector)
        cam_now = _build_camera_rect(frame_w, frame_h, roi, cfg)
        cam = _smooth(cam_prev, cam_now, cfg.smoothness)
        cam_prev = cam
        last_frame = frame

        cropped_frame = _crop_frame(frame, cam) # Crop original frame

        # Apply background subtraction if enabled
        if cfg.bg_sub_enable:
            # Scale cropped_frame for MOG2 analysis if needed
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
        writer.write(out_frame)
        frame_idx += 1
        src_idx   += 1

    # ── Tail extension: freeze last frame while camera settles ────────────────
    # Kept intentionally short (≤ 0.3 s) because this output is a looping GIF:
    # long tails create a visible freeze before the loop restarts.
    # The exponential smoothing in the main loop already decelerates the camera
    # naturally; the tail only catches the very last frame's residual movement.
    # NOTE: background subtraction is skipped here — applying MOG2 to a repeated
    # static frame would progressively darken the output as the model reclassifies
    # the content as background.
    if last_frame is not None and cam_prev is not None and cam_now is not None:
        max_extra = max(1, int(fps * 0.3))   # hard cap: 0.3 s (was 3 s)
        settle_px = 1.0                       # stop when camera moves < 1 px/frame (was 0.5)
        extra = 0
        while extra < max_extra:
            cam_next = _smooth(cam_prev, cam_now, cfg.smoothness)
            # Max displacement across the four camera parameters (cx, cy, cw, ch)
            displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
            cam_prev = cam_next
            cropped_frame = _crop_frame(last_frame, cam_next)

            out_frame = cv2.resize(cropped_frame, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
            writer.write(out_frame)
            frame_idx += 1
            extra += 1
            if displacement < settle_px:
                break   # camera has settled — no more extension needed

    writer.release()
    cap.release()

    if frame_idx <= 0 or not os.path.isfile(out_path):
        return False, None, "No frames generated by action preprocessing."

    tail_info  = f" +{extra}t"     if extra > 0       else ""
    intro_info = f" +{intro_frames}i" if intro_frames > 0 else ""
    return True, out_path, (
        f"Auto action OK ({frame_idx} frames{intro_info}{tail_info}, "
        f"{out_w}×{out_h}, detector={cfg.detector})."
    )