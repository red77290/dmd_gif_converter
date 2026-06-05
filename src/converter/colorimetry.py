#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dmd_auto_color — Heuristic Auto-Colorimetry Engine

Analyses a representative keyframe from any video/GIF source and computes
optimised colorimetry parameters tailored for HUB75 128×32 LED matrix panels.

Design philosophy
-----------------
The pixel_art preset (contrast=1.6, saturation=2.2, gamma=0.85, brightness=-0.03)
is already hand-tuned for LED panels.  Smart Color Boost uses those values as a
*baseline* and applies ±delta corrections based on the keyframe analysis:

  • Luminance too dark  → gamma up,  brightness up   (dark scene, night, dungeon)
  • Luminance too bright→ gamma down, brightness down (over-exposed, washed-out)
  • Contrast too low    → contrast up                 (foggy, flat, hazy)
  • Saturation too low  → saturation up               (grey, near B&W)
  • Source already vivid→ slight saturation reduction  (avoid over-saturation)

Normal well-exposed content receives small adjustments around the baseline,
so the result is always at least as good as the standard pixel_art preset.

Delta functions use **continuous piecewise-linear interpolation** instead of
step-wise if/elif chains.  This ensures that structurally similar sources always
produce consistent, smoothly-varying parameters — no abrupt jumps at thresholds.

Relies exclusively on OpenCV and NumPy — no additional dependencies.

Public API
----------
    ok, params, message = analyze_and_compensate(src_path)
"""

from __future__ import annotations
import math
from typing import Tuple, Dict


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Smooth piecewise-linear interpolation (no NumPy required) ────────────────

def _linear_interp(x: float, xp: "list[float]", fp: "list[float]") -> float:
    """Piecewise linear interpolation between (xp[i], fp[i]) knot pairs.

    Replaces step-wise if/elif chains with a continuous mapping:
    structurally similar inputs always produce consistent, smoothly-varying
    output values — no abrupt jumps at threshold boundaries.

    Parameters
    ----------
    x  : query value
    xp : sorted list of x knot positions (must be strictly increasing)
    fp : list of f(x) values at each knot

    Returns f(x) clamped to [fp[0], fp[-1]] range at extrapolation boundaries.
    """
    if x <= xp[0]:
        return float(fp[0])
    if x >= xp[-1]:
        return float(fp[-1])
    for i in range(len(xp) - 1):
        if xp[i] <= x < xp[i + 1]:
            t = (x - xp[i]) / (xp[i + 1] - xp[i])
            return float(fp[i]) + t * float(fp[i + 1] - fp[i])
    return float(fp[-1])


# ── LED baseline (= pixel_art preset) ────────────────────────────────────────
# These are the hand-tuned defaults for LED rendering.  The heuristic only
# moves away from these when the source clearly needs it.
_BASE_CONTRAST   = 1.60
_BASE_SATURATION = 2.20
_BASE_GAMMA      = 0.85
_BASE_BRIGHTNESS = -0.03
_BASE_SHARPEN_L  = 1.80
_BASE_SHARPEN_C  = 0.50


# ── Delta helpers — continuous piecewise-linear mappings ─────────────────────

def _gamma_delta(mean_lum: float) -> float:
    """Luminance → gamma correction delta (continuous interpolation).

    Knots are placed at the original if/elif threshold boundaries so the
    curve passes through the same anchor values while being smooth in between.
    """
    xp = [  0,  40,  75, 100, 140, 175, 210, 255]
    fp = [+0.40, +0.40, +0.20, +0.08, 0.00, -0.10, -0.20, -0.30]
    return _linear_interp(mean_lum, xp, fp)


def _contrast_delta(std_lum: float) -> float:
    """Dynamic range → contrast correction delta (continuous interpolation)."""
    xp = [  0,  20,  35,  50,  70, 255]
    fp = [+0.70, +0.70, +0.45, +0.20, 0.00, -0.15]
    return _linear_interp(std_lum, xp, fp)


def _saturation_delta(mean_sat: float) -> float:
    """Colour vibrancy → saturation correction delta (continuous interpolation)."""
    xp = [  0,  10,  40,  80, 130, 180, 255]
    fp = [+1.10, +1.10, +0.70, +0.30, 0.00, -0.30, -0.60]
    return _linear_interp(mean_sat, xp, fp)


def _sample_frames(src_str: str, is_gif: bool, cv2) -> list:
    """Open the source and return a list of BGR frames sampled at key positions.

    GIF  → frame 0 only  (sequential decode is O(N), keep it cheap).
    Video → frames at 25 %, 50 %, 75 % of duration.
    """
    cap = cv2.VideoCapture(src_str)
    if not cap.isOpened():
        return []
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps_src      = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    duration_ms  = (
        (total_frames / fps_src) * 1000.0
        if (not is_gif and total_frames > 2 and fps_src > 0) else 0.0
    )
    sample_pcts = [0.0] if is_gif else [0.25, 0.50, 0.75]
    frames: list = []
    for pct in sample_pcts:
        if duration_ms > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, duration_ms * pct)
        ok_f, frame = cap.read()
        if ok_f and frame is not None:
            frames.append(frame)
    cap.release()
    return frames


def _average_metrics(frames: list, cv2, np) -> Tuple[float, float, float]:
    """Return (mean_lum, std_lum, mean_sat) averaged across all frames."""
    mean_lums, std_lums, mean_sats = [], [], []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype("float32")
        mean_lums.append(float(np.mean(gray)))
        std_lums.append(float(np.std(gray)))
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype("float32")
        mean_sats.append(float(np.mean(hsv[:, :, 1])))
    n = len(frames)
    return sum(mean_lums) / n, sum(std_lums) / n, sum(mean_sats) / n


def analyze_and_compensate(src_path: str,
                             mid_pct: float = 0.50
                             ) -> Tuple[bool, Dict, str]:
    """Extract representative keyframes and compute LED-optimised colorimetry.

    Parameters
    ----------
    src_path : str
        Path to the source video or GIF.
    mid_pct : float
        Unused — kept for backward compatibility.  Videos are always sampled
        at three fixed positions (25 %, 50 %, 75 %); GIFs use frame 0.

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

    src_str = str(src_path)
    is_gif  = src_str.lower().endswith(".gif")

    sampled_frames = _sample_frames(src_str, is_gif, cv2)
    if not sampled_frames:
        return False, {}, "Failed to extract keyframe(s) for colorimetry analysis"

    mean_lum, std_lum, mean_sat = _average_metrics(sampled_frames, cv2, np)
    n_frames = len(sampled_frames)

    # ── 3. Gamma + brightness corrections ────────────────────────────────────
    gamma      = _clamp(_BASE_GAMMA      + _gamma_delta(mean_lum),    0.55, 1.40)
    bri_delta  = _clamp((110.0 - mean_lum) / 255.0 * 0.20,          -0.10, 0.08)
    brightness = _clamp(_BASE_BRIGHTNESS  + bri_delta,               -0.15, 0.10)

    # ── 4. Contrast + saturation corrections ─────────────────────────────────
    contrast   = _clamp(_BASE_CONTRAST   + _contrast_delta(std_lum),  1.40, 2.50)
    saturation = _clamp(_BASE_SATURATION + _saturation_delta(mean_sat), 0.90, 3.50)

    # ── 5. Build result ───────────────────────────────────────────────────────
    params: Dict = {
        "contrast":    round(contrast,   2),
        "saturation":  round(saturation, 2),
        "brightness":  round(brightness, 3),
        "gamma":       round(gamma,      2),
        "sharpen_lum": _BASE_SHARPEN_L,
        "sharpen_chr": _BASE_SHARPEN_C,
        "dither":      "none",
    }

    frame_label = f"{n_frames} frame{'s' if n_frames > 1 else ''}"
    delta_c = round(contrast   - _BASE_CONTRAST,   2)
    delta_s = round(saturation - _BASE_SATURATION, 2)
    message = (
        f"auto-color ({frame_label}): lum={mean_lum:.0f} std={std_lum:.0f} sat={mean_sat:.0f} "
        f"→ contrast={params['contrast']} ({delta_c:+.2f})  "
        f"sat={params['saturation']} ({delta_s:+.2f})  "
        f"gamma={params['gamma']}  bri={params['brightness']:+.3f}"
    )
    return True, params, message
