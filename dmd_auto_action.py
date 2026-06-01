#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto action framing preprocessor (outside ffmpeg pipeline).

This module detects action/person regions frame-by-frame and generates a
cinematic 4:1 intermediate video before the regular ffmpeg DMD conversion.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional, Tuple


def available_detectors() -> list[str]:
    """Return supported detector mode names."""
    return ["person", "motion", "hybrid", "center"]


@dataclass
class AutoActionConfig:
    detector: str = "person"          # person | motion | hybrid | center
    strength: float = 0.65             # 0..1, larger = tighter framing
    smoothness: float = 0.85           # 0..0.98, larger = smoother / slower
    zoom_max: float = 1.8              # max dynamic zoom factor
    padding: float = 0.20              # extra padding around ROI
    intro_duration: float = 1.5        # seconds of full-frame overview before focusing
    # out_w / out_h are no longer used for the actual output resolution.
    # The preprocessor always outputs at the source native width with a 4:1
    # crop ratio (= DMD ratio 128:32) so that ffmpeg receives full-quality input.
    # These fields are kept for API backward-compatibility only.
    out_w: int = 0
    out_h: int = 0
    start_s: Optional[float] = None
    end_s: Optional[float] = None


class _FrameDetector:
    """Detector backend for person/motion ROI extraction."""

    def __init__(self):
        import cv2  # local import: module remains importable without OpenCV

        self.cv2 = cv2
        self.prev_gray = None

        # Lightweight person detector (OpenCV HOG + SVM), no extra model files.
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        self.bg_sub = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=36)

    def detect_person(self, frame) -> Optional[Tuple[int, int, int, int]]:
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
    target_ratio = 4.0  # DMD is always 128×32 = 4:1

    if roi is None:
        # Keep source center when no ROI is available.
        cx = frame_w / 2.0
        cy = frame_h / 2.0
        # Fit widest 4:1 crop possible.
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

    # Keep inside frame bounds.
    crop_w = _clamp(crop_w, 32.0, float(frame_w))
    crop_h = _clamp(crop_h, 8.0, float(frame_h))

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

    # Output at native source resolution with 4:1 crop ratio (= DMD ratio 128:32).
    # Keeping the native resolution here means ffmpeg receives full-quality input
    # and performs the final downscale to 128×32 with all its colour filters.
    out_w = frame_w
    out_h = max(8, (frame_w // 4 // 2) * 2)   # even number, 4:1

    start_s = cfg.start_s if cfg.start_s is not None else 0.0
    end_s = cfg.end_s
    if start_s > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(start_s) * 1000.0)

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

    # Full-frame overview rect: widest 4:1 crop centred on the source.
    cam_full_view = _build_camera_rect(frame_w, frame_h, None, cfg)

    # Number of intro frames to prepend.
    intro_frames = max(0, int(round(cfg.intro_duration * fps)))

    last_frame = None
    frame_idx  = 0
    extra      = 0

    # ── Phase 1: Intro panoramic pan (frozen first frame, top → centre) ──────────
    # The first source frame is held for intro_frames while the camera pans
    # from the TOP of the frame down to the CENTRE (using smoothstep easing).
    # This ensures the top of the scene is always visible at the start, and
    # the pan ends at cam_full_view (centre) so Phase 2 transitions smoothly.
    # The source video is then rewound so Phase 2 replays ALL frames — no
    # source content is sacrificed to the intro.
    if intro_frames > 0:
        ok_first, first_frame = cap.read()
        if ok_first:
            # Decompose the full-view rect to get crop dimensions and centre cy.
            cx, cy_center, crop_w_full, crop_h_src = cam_full_view

            # Top of frame: smallest cy that keeps the crop fully inside.
            cy_top = crop_h_src / 2.0

            for i in range(intro_frames):
                # Smoothstep: t goes 0 → 1 over the intro duration.
                t_linear = i / max(1, intro_frames - 1)
                t = t_linear * t_linear * (3.0 - 2.0 * t_linear)
                cy = cy_top + t * (cy_center - cy_top)
                cam_intro = (cx, cy, crop_w_full, crop_h_src)
                crop = _crop_frame(first_frame, cam_intro)
                out_frame = cv2.resize(crop, (out_w, out_h),
                                       interpolation=cv2.INTER_LANCZOS4)
                writer.write(out_frame)
                frame_idx += 1

            # Rewind to the trim start so the action phase replays all frames.
            if start_s > 0:
                cap.set(cv2.CAP_PROP_POS_MSEC, float(start_s) * 1000.0)
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            last_frame = first_frame

    # ── Phase 2: Action tracking (full source from frame 0) ───────────────────
    # Camera starts at cam_full_view so the transition from the intro is smooth.
    cam_prev = cam_full_view
    cam_now  = cam_full_view
    src_idx  = 0     # independent counter for end_s trimming

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        t = src_idx / fps
        if end_s is not None and (start_s + t) >= float(end_s):
            break

        roi = detector.detect(frame, cfg.detector)
        cam_now = _build_camera_rect(frame_w, frame_h, roi, cfg)
        cam = _smooth(cam_prev, cam_now, cfg.smoothness)
        cam_prev = cam
        last_frame = frame

        crop = _crop_frame(frame, cam)
        out_frame = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
        writer.write(out_frame)
        frame_idx += 1
        src_idx   += 1

    # ── Tail extension: freeze last frame while camera settles ────────────────
    # If the source is too short the smooth camera may not have finished its
    # movement toward the final target position.  We keep writing the frozen
    # last frame while advancing the exponential smoothing until the per-frame
    # displacement drops below 0.5 px, capped at 3 seconds of extra content.
    if last_frame is not None and cam_prev is not None and cam_now is not None:
        max_extra = int(fps * 3)          # hard cap: 3 s worth of frames
        settle_px = 0.5                   # stop when camera moves < 0.5 px/frame
        extra = 0
        while extra < max_extra:
            cam_next = _smooth(cam_prev, cam_now, cfg.smoothness)
            # Max displacement across the four camera parameters (cx, cy, cw, ch)
            displacement = max(abs(cam_next[i] - cam_prev[i]) for i in range(4))
            cam_prev = cam_next
            crop = _crop_frame(last_frame, cam_next)
            out_frame = cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
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

