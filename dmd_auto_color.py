#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dmd_auto_color — Heuristic Auto-Colorimetry Engine

Analyses a representative keyframe from any video/GIF source and computes
optimised colorimetry parameters (contrast, saturation, gamma, brightness)
tailored for HUB75 128×32 LED matrix panels.

Relies exclusively on OpenCV and NumPy — no additional dependencies.

Public API
----------
    ok, params, message = analyze_and_compensate(src_path)

    ok      : bool  — False if analysis failed (fallback to defaults)
    params  : dict  — contrast / saturation / brightness / gamma / …
    message : str   — human-readable summary for the conversion log
"""

from __future__ import annotations
import math
from typing import Tuple, Dict


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def analyze_and_compensate(src_path: str,
                            mid_pct: float = 0.50
                            ) -> Tuple[bool, Dict, str]:
    """Extract a keyframe and compute LED-optimised colorimetry.

    Parameters
    ----------
    src_path : str
        Path to the source video or GIF.
    mid_pct : float
        Relative position of the keyframe in the clip (default 0.50 = 50 %).

    Returns
    -------
    (ok, params, message)
        ok      : True on success, False on any failure (fallback to defaults).
        params  : dict with keys  contrast / saturation / brightness / gamma /
                  sharpen_lum / sharpen_chr / dither  — ready to merge into the
                  process_file params dict with mode="custom".
        message : one-line summary suitable for the conversion log.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return (False, {},
                "OpenCV/NumPy unavailable — install opencv-python for auto-colorimetry")

    # ── 1. Extract keyframe ───────────────────────────────────────────────────
    # Performance rules:
    #   • GIF  → sequential decode: seeking frame N requires decoding all
    #     previous frames.  Always read frame 0 to stay well under 0.5 s.
    #   • Video → time-based seek (CAP_PROP_POS_MSEC) is O(1) for most
    #     codecs; use it to land near mid_pct of the clip.
    src_str = str(src_path)
    is_gif  = src_str.lower().endswith(".gif")

    cap = cv2.VideoCapture(src_str)
    if not cap.isOpened():
        return False, {}, "Could not open source for colorimetry analysis"

    if not is_gif:
        # Time-based seek — safe and fast for MP4/MKV/MOV/AVI/WEBM…
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps_src      = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if total_frames > 2 and fps_src > 0:
            duration_ms = (total_frames / fps_src) * 1000.0
            cap.set(cv2.CAP_PROP_POS_MSEC,
                    duration_ms * _clamp(mid_pct, 0.0, 1.0))
    # For GIFs (and any failed seek) the first frame is read as-is.

    ok, frame = cap.read()
    cap.release()

    if not ok or frame is None:
        return False, {}, "Failed to extract keyframe for colorimetry analysis"

    # ── 2. Luminance analysis ─────────────────────────────────────────────────
    gray     = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype("float32")
    mean_lum = float(np.mean(gray))   # overall brightness  0-255
    std_lum  = float(np.std(gray))    # dynamic range proxy 0-127

    # ── 3. Saturation analysis (HSV S channel) ────────────────────────────────
    hsv      = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype("float32")
    mean_sat = float(np.mean(hsv[:, :, 1]))   # 0-255

    # ── 4. Gamma — luminance compensation ────────────────────────────────────
    # LED target: slightly sub-neutral brightness (~110/255) to avoid
    # blown-out highlights on diffuse LED panels.
    # Formula: gamma = log(mean/255) / log(target/255)
    #   > 1  → brightens mid-tones (dark source)
    #   < 1  → darkens  mid-tones (bright/washed source)
    TARGET_LUM = 110.0
    if mean_lum < 5.0:
        gamma = 1.30                                          # near-black → strong lift
    elif mean_lum > 200.0:
        gamma = 0.60                                          # very bright → pull down
    else:
        raw_gamma = math.log(mean_lum / 255.0) / math.log(TARGET_LUM / 255.0)
        gamma = _clamp(raw_gamma, 0.55, 1.40)

    # ── 5. Brightness — fine-tune residual offset ─────────────────────────────
    brightness = _clamp((TARGET_LUM - mean_lum) / 255.0 * 0.25, -0.15, 0.10)

    # ── 6. Contrast — std-dev compensation ───────────────────────────────────
    # Target std ≈ 60 px (good dynamic range for LED rendering).
    # LED panels always benefit from at least 1.2× contrast — even well-exposed
    # sources need a boost because LED diffusion reduces perceived contrast.
    TARGET_STD = 60.0
    raw_contrast = TARGET_STD / max(std_lum, 2.0)
    contrast = _clamp(raw_contrast, 1.20, 2.50)

    # ── 7. Saturation — LED vibrancy boost ───────────────────────────────────
    # Near-greyscale sources get maximum saturation; vivid sources still receive
    # the standard LED compensation (~1.5–2.0×).
    TARGET_SAT = 90.0   # S = 90/255 ≈ "averagely colourful" reference
    if mean_sat < 10.0:
        saturation = 3.00
    else:
        raw_sat = (TARGET_SAT / mean_sat) ** 0.5 * 2.0
        saturation = _clamp(raw_sat, 0.90, 3.50)

    # ── 8. Build result dict ──────────────────────────────────────────────────
    params: Dict = {
        "contrast":    round(contrast,   2),
        "saturation":  round(saturation, 2),
        "brightness":  round(brightness, 3),
        "gamma":       round(gamma,      2),
        "sharpen_lum": 1.8,    # keep standard sharpening
        "sharpen_chr": 0.5,
        "dither":      "none",
    }

    message = (
        f"auto-color: src lum={mean_lum:.0f} std={std_lum:.0f} sat={mean_sat:.0f} "
        f"→ contrast={params['contrast']} saturation={params['saturation']} "
        f"gamma={params['gamma']} brightness={params['brightness']:+.3f}"
    )
    return True, params, message

