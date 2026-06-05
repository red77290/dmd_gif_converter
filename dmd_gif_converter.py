#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dmd_gif_converter — Conversion engine for 128×32 DMD LED panels.

Can be imported as a module (process_file / process_folder) or run directly
from the command line for backward-compatible CLI usage.
"""
import os
import sys
import subprocess
import math
import argparse
import concurrent.futures
import json
import logging
from pathlib import Path

from dmd_auto_action import AutoActionConfig, preprocess_video_for_dmd

try:
    from dmd_auto_color import analyze_and_compensate as _analyze_and_compensate
except Exception:
    _analyze_and_compensate = None

# ── drawtext availability (cached at first use) ────────────────────────────────
_drawtext_available = None  # bool or None (None = not yet checked)

def _check_drawtext() -> bool:
    """Return True if the installed ffmpeg has the drawtext filter (requires libfreetype)."""
    global _drawtext_available
    if _drawtext_available is None:
        try:
            r = subprocess.run(
                ["ffmpeg", "-filters"],
                capture_output=True, text=True, timeout=10
            )
            _drawtext_available = "drawtext" in (r.stdout + r.stderr)
        except Exception:
            _drawtext_available = False
    return _drawtext_available


# ── Pillow text overlay fallback ───────────────────────────────────────────────
_TEXT_COLOR_MAP = {
    "white":  (255, 255, 255, 255),
    "yellow": (255, 255,   0, 255),
    "red":    (255,   0,   0, 255),
    "green":  (  0, 255,   0, 255),
    "blue":   (  0,   0, 255, 255),
}

def _apply_text_overlay_pillow(
    gif_path: str,
    text: str,
    font_path_str: str,
    font_size: int,
    color_name: str,
    position: str,
    style: str = "outline",
    bg: bool = False,
    bg_opacity: int = 60,
) -> tuple[bool, str]:
    """Burn text onto every frame of an existing GIF using Pillow.

    Used as a fallback when ffmpeg is built without libfreetype (no drawtext filter).

    Supported styles:
        none    – plain text
        bold    – 1 px same-colour stroke (fatter text, good contrast on dark backgrounds)
        outline – 1 px black stroke (maximum readability on any background)
        shadow  – offset drop-shadow (depth effect)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False, "Pillow not available"

    try:
        img = Image.open(gif_path)
    except Exception as e:
        return False, "Cannot open GIF: %s" % e

    # ── Collect all frames as RGBA ─────────────────────────────────────────────
    frames_rgba: list = []
    durations:   list = []
    try:
        while True:
            durations.append(int(img.info.get("duration", 80)))
            frames_rgba.append(img.copy().convert("RGBA"))
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    if not frames_rgba:
        return False, "GIF has no frames"

    # ── Load font (fall back to Pillow default) ────────────────────────────────
    try:
        font = ImageFont.truetype(font_path_str, font_size)
    except Exception:
        font = ImageFont.load_default()

    rgba_color  = _TEXT_COLOR_MAP.get(color_name.lower(), (255, 255, 255, 255))
    black_opaque = (0, 0, 0, 255)
    shadow_color = (0, 0, 0, 200)
    margin = 2

    # Stroke width used for bounding-box calculation (so text does not get clipped)
    stroke_w = 1 if style in ("bold", "outline") else 0

    # ── Draw text on every frame ───────────────────────────────────────────────
    out_frames: list = []
    for frame in frames_rgba:
        draw = ImageDraw.Draw(frame)
        w, h = frame.size

        # Bounding box including optional stroke so position maths is correct
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        if   position == "top_left":      x, y = margin,            margin
        elif position == "top_center":    x, y = (w - tw) // 2,     margin
        elif position == "top_right":     x, y = w - tw - margin,   margin
        elif position == "middle_left":   x, y = margin,            (h - th) // 2
        elif position == "middle_center": x, y = (w - tw) // 2,     (h - th) // 2
        elif position == "middle_right":  x, y = w - tw - margin,   (h - th) // 2
        elif position == "bottom_left":   x, y = margin,            h - th - margin
        elif position == "bottom_right":  x, y = w - tw - margin,   h - th - margin
        else:                             x, y = (w - tw) // 2,     h - th - margin  # bottom_center

        # ── Optional background box ────────────────────────────────────────────
        if bg:
            text_bbox = draw.textbbox((x, y), text, font=font, stroke_width=stroke_w)
            pad = 2
            box_coords = (
                text_bbox[0] - pad, text_bbox[1] - pad,
                text_bbox[2] + pad, text_bbox[3] + pad,
            )
            alpha_val = max(0, min(255, int(bg_opacity * 255 / 100)))
            overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rectangle(box_coords, fill=(0, 0, 0, alpha_val))
            frame = Image.alpha_composite(frame, overlay)
            draw = ImageDraw.Draw(frame)

        # ── Text rendering (style-dependent) ──────────────────────────────────
        if style == "bold":
            # Stroke in the same colour → fatter glyph without a visible border
            draw.text((x, y), text, font=font, fill=rgba_color,
                      stroke_width=1, stroke_fill=rgba_color)
        elif style == "outline":
            # Black stroke → readable on any background
            draw.text((x, y), text, font=font, fill=rgba_color,
                      stroke_width=1, stroke_fill=black_opaque)
        elif style == "shadow":
            # Drop shadow 1 px down-right, then main text on top
            draw.text((x + 1, y + 1), text, font=font, fill=shadow_color)
            draw.text((x, y),         text, font=font, fill=rgba_color)
        else:
            # style == "none"
            draw.text((x, y), text, font=font, fill=rgba_color)

        out_frames.append(frame.convert("RGB"))

    # ── Re-encode as GIF ──────────────────────────────────────────────────────
    # Save directly from RGB: Pillow auto-quantises for GIF output.
    # Using a single save_all call preserves all frames and their durations.
    try:
        out_frames[0].save(
            gif_path,
            format="GIF",
            save_all=True,
            append_images=out_frames[1:],
            loop=0,
            duration=durations,
            optimize=False,
        )
    except Exception as e:
        return False, "Failed to save GIF with text: %s" % e

    return True, "text overlay (%s) applied via Pillow (ffmpeg drawtext unavailable)" % style

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ── Supported input formats ────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {
    ".gif", ".mp4", ".avi", ".mkv", ".mov", ".webm",
    ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"
}

# ── Default parameters ─────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    # Parallelism
    "max_workers": 2,
    # Source folder auto-detection (CLI mode only)
    "folder_prefix": "gifs_",
    # Scroll
    "scroll_speed": 24.0,        # pixels per second
    "bottom_crop_pct": 0.15,     # fraction of image bottom to ignore
    "top_crop_pct": 0.0,         # fraction of image top to ignore
    #
    # scroll_cycles: number of round-trips + fractional stop position.
    #   integer part  = number of complete down→up cycles
    #   fractional part × scroll_dist = y position where the image stops and holds
    #
    #   Examples (scroll_dist = 64 px):
    #     1.0  → 1 full round-trip, holds at top     (y = 0)
    #     1.5  → 1 full round-trip, holds at centre  (y = 32 px)
    #     1.75 → 1 full round-trips, holds at ¾       (y = 48 px)
    #     2.0  → 2 full round-trips, holds at top    (y = 0)
    #     0.5  → no round-trip, holds at centre      (y = 32 px)
    #
    "scroll_cycles": 1.5,
    # FPS
    "fps_min": 10.0,
    "fps_max": 25.0,
    # Content mode: "pixel_art" | "anime" | "cinema" | "custom"
    "mode": "pixel_art",
    # Custom colorimetry (only used when mode="custom")
    "contrast": 1.6,
    "saturation": 2.2,
    "brightness": -0.03,
    "gamma": 0.85,
    "sharpen_lum": 1.8,
    "sharpen_chr": 0.5,
    "dither": "none",
    # ── Advanced: Positioning ──────────────────────────────────────────────────
    # scroll_enabled=True  → default vertical auto-scroll behaviour (unchanged)
    "scroll_enabled": True,
    "zoom":           1.0,   # scale multiplier (1.0 = fit to 128 px width)
    "manual_x":       0,     # horizontal crop offset in pixels (manual mode)
    "manual_y":       0,     # vertical   crop offset in pixels (manual mode)
    # ── Advanced: Visual effects (all default to "no change") ─────────────────
    "hue_shift":       0.0,   # hue rotation in degrees, -180 … +180
    "noise_reduction": 0.0,   # hqdn3d strength, 0 = disabled
    "film_grain":      0,     # additive noise amount, 0 = disabled
    "vignette":        False, # apply a vignette darkening at the edges
    # ── Duration cap ──────────────────────────────────────────────────────
    # 0.0 = no limit; >0 = hard cap in seconds applied after trim_start.
    # Useful for batch processing: clips longer than max_duration are
    # trimmed from trim_start to trim_start + max_duration.
    "max_duration": 0.0,
    # ── Advanced: Auto action framing (pre-ffmpeg stage) ─────────────────
    "auto_action_enabled": False,
    "action_detector":     "person",   # person | motion | hybrid | center
    "action_strength":     0.65,       # 0..1 tighter framing around action
    "action_smoothness":   0.85,       # 0..0.98 camera smoothing
    "action_zoom_max":     2.0,        # max dynamic zoom factor (hard limit)
    "action_padding":      0.20,       # ROI padding before aspect crop
    "action_intro":        1.5,        # seconds of full-frame overview before zoom-in
    "bg_sub_enable":       False,      # enable background subtraction (replaces background with black)
    # ── Crop & vertical bias (individual manual/auto controls) ────────────
    "action_bottom_crop":         0.0,
    "action_auto_bottom_crop":    False,
    "action_top_crop":            0.0,
    "action_auto_top_crop":       False,
    "action_vertical_bias":       0.0,
    "action_auto_vertical_bias":  False,
    # ── Smart Auto Crop — engine-driven combination selector ──────────────
    # When True the engine scans 25 frames and decides which of the 3 options
    # above (auto_bottom, auto_top, auto_vertical) to activate based on the
    # detected context (floor, clutter, character height).  All individual
    # flags above are ignored while this is ON.
    "action_smart_auto_crop":     False,
    # ── Multi-dalle / Tiling ─────────────────────────────────────────────────
    "target_width":  128,
    "target_height": 32,
    # ── Text Overlay ─────────────────────────────────────────────────────────
    "text_overlay_enabled": False,
    "text_content":         "",
    "text_font_size":       8,
    "text_color":           "white",
    "text_position":        "bottom_center", # top_left, top_center, top_right, middle_left, middle_center, middle_right, bottom_left, bottom_center, bottom_right
    "text_font_file":       "HelvetiPixel.ttf",  # Default font file (see media/fonts/)
    "text_style":           "outline",  # none | bold | outline | shadow
    "text_bg":              False,      # draw a dark background box behind text
    "text_bg_opacity":      60,         # background box opacity 0-100
}

_PRESETS = {
    #               contrast  sat    bright  gamma  sh_lum sh_chr  dither
    "pixel_art": (  1.6,      2.2,  -0.03,  0.85,  1.8,   0.5,   "none" ),
    "anime":     (  1.5,      1.9,  -0.02,  0.87,  1.3,   0.3,   "none" ),
    "cinema":    (  1.4,      1.3,  -0.01,  0.90,  0.8,   0.2,   "none" ),
}

_CLEAN_GIF_FPS = [10.0, 12.5, 20.0, 25.0]


def snap_to_clean_fps(fps: float, fps_min: float = 10.0, fps_max: float = 25.0) -> float:
    """Round fps to the nearest clean GIF value (avoids judder from centisecond quantization)."""
    fps_clamped = max(fps_min, min(fps_max, fps))
    return min(_CLEAN_GIF_FPS, key=lambda f: abs(f - fps_clamped))


def get_metadata(file_path: str):
    """Extract width, height, playback FPS and duration from any video using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames",
        "-show_entries", "format=duration",
        "-of", "json", str(file_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(res.stdout.strip())
        stream = data["streams"][0]
        fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate", "25/1")
        num, den = map(int, fps_str.split("/"))
        fps_src = (num / den) if (den and num) else 25.0
        fps_src = max(1.0, min(100.0, fps_src))
        duration = float(data.get("format", {}).get("duration", 0) or 0)
        if duration <= 0 and stream.get("nb_frames", "N/A") != "N/A":
            duration = int(stream["nb_frames"]) / fps_src
        return int(stream["width"]), int(stream["height"]), fps_src, duration
    except Exception as e:
        logger.warning(f"Could not read metadata ({file_path}): {e}")
        return None, None, 25.0, 0.0


def process_file(src_path, out_path, params=None, start_s=None, end_s=None, callback=None):
    """
    Convert any video / GIF to 128×32 DMD format.

    Args:
        src_path:  Path to source file (any format supported by ffmpeg).
        out_path:  Path to output .gif file.
        params:    Conversion parameters dict (merged with DEFAULT_PARAMS).
        start_s:   Clip start time in seconds (None = beginning of file).
        end_s:     Clip end time in seconds   (None = end of file).
        callback:  Optional callable(message: str, level: str) for progress.

    Returns:
        (success: bool, message: str)
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    src_path = str(src_path)
    out_path = str(out_path)
    filename = os.path.basename(src_path)

    def log(msg, level="info"):
        getattr(logger, level)(msg)
        if callback:
            callback(msg, level)

    # Optional preprocessor temp dir (auto action mode).
    temp_pre_src = None
    # Keep a reference to the original source for keyframe analysis (auto-color
    # must analyse the original colours, not the auto-action crop).
    original_src = src_path

    # Get target dimensions
    target_width = p["target_width"]
    target_height = p["target_height"]

    # ── Auto action preprocessor (outside ffmpeg pipeline) ───────────────────
    # Default is disabled, so this block has zero effect unless explicitly enabled.
    auto_action_enabled = bool(p.get("auto_action_enabled", False))
    if auto_action_enabled:
        cfg = AutoActionConfig(
            detector=str(p.get("action_detector", "person") or "person"),
            strength=float(p.get("action_strength", 0.65)),
            smoothness=float(p.get("action_smoothness", 0.85)),
            zoom_max=float(p.get("action_zoom_max", 1.8)),
            padding=float(p.get("action_padding", 0.20)),
            intro_duration=float(p.get("action_intro", 1.5)),
            bg_sub_enable=bool(p.get("bg_sub_enable", False)),
            bottom_crop_pct=float(p.get("action_bottom_crop", 0.0)),
            auto_bottom_crop=bool(p.get("action_auto_bottom_crop", False)),
            top_crop_pct=float(p.get("action_top_crop", 0.0)),
            auto_top_crop=bool(p.get("action_auto_top_crop", False)),
            vertical_bias=float(p.get("action_vertical_bias", 0.0)),
            auto_vertical_bias=bool(p.get("action_auto_vertical_bias", False)),
            smart_auto_crop=bool(p.get("action_smart_auto_crop", False)),
            start_s=float(start_s) if start_s is not None else None,
            end_s=float(end_s) if end_s is not None else None,
            target_width=target_width, # Pass target dimensions to auto_action
            target_height=target_height, # Pass target dimensions to auto_action
        )
        ok_pre, pre_src, pre_msg = preprocess_video_for_dmd(src_path, cfg)
        if ok_pre and pre_src:
            src_path = pre_src
            temp_pre_src = os.path.dirname(pre_src)
            # Trim already applied during preprocessor stage.
            start_s = None
            end_s = None
            log(f"[ACTION ] {filename} — {pre_msg}")
        else:
            # Fall back to normal pipeline when dependency/tooling is unavailable.
            log(f"[ACTION ] {filename} — disabled fallback: {pre_msg}", "warning")

    # ── Auto-colorimetry (heuristic keyframe analysis) ───────────────────────
    # Analyses the original source at 50 % duration and injects computed
    # contrast / saturation / gamma / brightness — overrides any preset/manual.
    if bool(p.get("auto_color_enabled", False)):
        if _analyze_and_compensate is not None:
            ok_c, color_params, color_msg = _analyze_and_compensate(original_src)
            if ok_c:
                p = {**p, "mode": "custom", **color_params}
                log(f"[COLOR  ] {filename} — {color_msg}")
            else:
                log(f"[COLOR  ] {filename} — fallback to defaults: {color_msg}", "warning")
        else:
            log(f"[COLOR  ] {filename} — OpenCV unavailable, skipping auto-colorimetry", "warning")

    src_w, src_h, fps_src, duration_full = get_metadata(src_path)
    if not src_w:
        if temp_pre_src and os.path.isdir(temp_pre_src):
            import shutil
            shutil.rmtree(temp_pre_src, ignore_errors=True)
        log(f"[ERROR] {filename} — could not read metadata", "error")
        return False, f"[ERROR] {filename} — metadata unreadable"

    # ── Clip timing ───────────────────────────────────────────────────────
    trim_start   = float(start_s) if start_s is not None else 0.0
    trim_end     = float(end_s)   if end_s   is not None else duration_full

    # Apply max_duration cap: trim_end = min(trim_end, trim_start + max_duration)
    max_dur = float(p.get("max_duration", 0.0))
    if max_dur > 0.0:
        trim_end = min(trim_end, trim_start + max_dur)
        log(f"[MAXDUR ] {filename} — cap {max_dur:.0f}s → [{trim_start:.1f}s … {trim_end:.1f}s]")

    duration_src = max(0.1, trim_end - trim_start)

    # ── Colorimetry preset ────────────────────────────────────────────────────
    mode = p["mode"]
    if mode in _PRESETS:
        c, s, b, g, sl, sc, dither = _PRESETS[mode]
    else:
        c  = p["contrast"];  s  = p["saturation"]; b = p["brightness"]
        g  = p["gamma"];     sl = p["sharpen_lum"]; sc = p["sharpen_chr"]
        dither = p["dither"]

    fps_render = snap_to_clean_fps(fps_src, p["fps_min"], p["fps_max"])

    # ── Advanced parameters ────────────────────────────────────────────────────
    scroll_enabled  = bool(p.get("scroll_enabled", True))
    zoom            = max(0.25, float(p.get("zoom", 1.0)))
    manual_x        = int(p.get("manual_x", 0))
    manual_y        = int(p.get("manual_y", 0))
    hue_shift       = float(p.get("hue_shift", 0.0))
    noise_reduction = float(p.get("noise_reduction", 0.0))
    film_grain      = int(p.get("film_grain", 0))
    vignette_on     = bool(p.get("vignette", False))

    # ── Text Overlay parameters ───────────────────────────────────────────────
    text_overlay_enabled = bool(p.get("text_overlay_enabled", False))
    text_content_raw     = str(p.get("text_content", ""))           # original (for Pillow)
    text_content         = text_content_raw.replace(":", "\\:")     # escaped (for ffmpeg)
    text_font_size       = int(p.get("text_font_size", 8))
    text_color           = str(p.get("text_color", "white"))
    text_position        = str(p.get("text_position", "bottom_center"))
    text_font_file       = str(p.get("text_font_file", "HelvetiPixel.ttf"))
    text_style           = str(p.get("text_style", "outline"))         # none | bold | outline | shadow
    text_bg              = bool(p.get("text_bg", False))
    text_bg_opacity      = int(p.get("text_bg_opacity", 60))

    # Resolve font path
    script_dir = Path(__file__).parent
    font_path = script_dir / "media" / "fonts" / text_font_file
    if not font_path.exists():
        font_path = script_dir / "media" / text_font_file
        if not font_path.exists():
            font_path = script_dir / text_font_file
            if not font_path.exists():
                log(f"[TEXT  ] Font file '{text_font_file}' not found. Text overlay disabled.", "error")
                text_overlay_enabled = False

    font_path_str = str(font_path).replace("\\", "/")  # FFmpeg prefers forward slashes

    # Decide which text-overlay backend to use:
    #   • ffmpeg drawtext  — requires libfreetype in the ffmpeg build
    #   • Pillow fallback  — always available, applied as a post-processing step
    _text_active      = text_overlay_enabled and bool(text_content_raw) and font_path.exists()
    _use_ffmpeg_text  = _text_active and _check_drawtext()
    _use_pillow_text  = _text_active and not _use_ffmpeg_text
    if _text_active and not _use_ffmpeg_text:
        log(f"[TEXT  ] {filename} — ffmpeg drawtext unavailable (no libfreetype); "
            "using Pillow fallback", "warning")

    # ── Scale (zoom-aware) ────────────────────────────────────────────────────
    # When zoom=1.0 (default), target_w=128 — identical to previous behaviour.
    target_w_scaled = max(target_width, round(target_width * zoom / 2) * 2)   # even, ≥ target_width
    scaled_h = math.ceil(((target_w_scaled / src_w) * src_h) / 2.0) * 2

    if scroll_enabled:
        # ── Auto-scroll (default behaviour, unchanged) ────────────────────────
        # Top crop: ignore the top fraction of the scaled image (e.g. title bars).
        # top_offset is always an even number (ffmpeg requires even crop coordinates).
        top_crop_pct = float(p.get("top_crop_pct", 0.0))
        top_offset   = math.floor(scaled_h * top_crop_pct / 2) * 2

        effective_h = math.floor(scaled_h * (1.0 - p["bottom_crop_pct"]) / 2) * 2
        effective_h = max(effective_h - top_offset, target_height)
        scroll_dist = effective_h - target_height
        # Horizontal: centered when zoomed (= "0" for default zoom=1.0)
        crop_x = str((target_w_scaled - target_width) // 2) if target_w_scaled > target_width else "0"

        if scroll_dist > 0:
            step = max(1, round(p["scroll_speed"] / fps_render))

            # ── Cycle decomposition ───────────────────────────────────────────
            cycles   = float(p.get("scroll_cycles", 1.5))
            full_cyc = int(cycles)
            frac     = round(cycles - full_cyc, 10)

            frames_one_way    = math.ceil(scroll_dist / step)
            frames_full_cycle = 2 * frames_one_way

            stop_pos       = min(round(frac * scroll_dist), scroll_dist)
            frames_partial = math.ceil(stop_pos / step) if stop_pos > 0 else 0

            n_cyc_end    = full_cyc * frames_full_cycle
            frames_move  = n_cyc_end + frames_partial
            frames_src   = max(1, round(duration_src * fps_render)) if duration_src > 0 else 1
            frames_total = max(frames_move + 1, frames_src)
            duration_out = str(frames_total / fps_render)

            # ── FFmpeg crop_y expression (relative to start of usable area) ───
            if full_cyc > 0:
                n_seq   = f"mod(n,{frames_full_cycle})"
                cycle_y = (
                    f"if(lte({n_seq},{frames_one_way}),"
                    f"min({n_seq}*{step},{scroll_dist}),"
                    f"max({scroll_dist}-({n_seq}-{frames_one_way})*{step},0))"
                )
                if frac > 0:
                    pn = f"(n-{n_cyc_end})"
                    crop_y = (
                        f"if(lt(n,{n_cyc_end}),"
                        f"{cycle_y},"
                        f"if(lt(n,{frames_move}),"
                        f"min({pn}*{step},{stop_pos}),"
                        f"{stop_pos}))"
                    )
                else:
                    crop_y = f"if(lt(n,{n_cyc_end}),{cycle_y},0)"
            else:
                if frac > 0:
                    crop_y = (
                        f"if(lt(n,{frames_partial}),"
                        f"min(n*{step},{stop_pos}),"
                        f"{stop_pos})"
                    )
                else:
                    crop_y = "0"

            # Apply top offset: shift the whole scroll window down by top_offset px
            if top_offset > 0:
                crop_y = f"({top_offset}+{crop_y})" if crop_y != "0" else str(top_offset)

            log(
                f"[SCROLL ] {filename} | src {src_w}x{src_h} → {target_w_scaled}x{effective_h} "
                f"| scroll_dist={scroll_dist}px | top_off={top_offset}px | cycles={cycles} "
                f"(full={full_cyc} frac={frac:.2f} stop={stop_pos}px) "
                f"| fps={fps_render} | step={step}px | total={float(duration_out):.2f}s"
            )
        else:
            duration_out = str(max(duration_src, 1.0))
            # Center within the usable (non-cropped) area
            crop_y = str(top_offset) if top_offset > 0 else "(in_h-out_h)/2"
            log(
                f"[CENTER ] {filename} | src {src_w}x{src_h} → {target_w_scaled}x{effective_h} (centered) "
                f"| top_off={top_offset}px | fps_src={fps_src:.1f} → render={fps_render} | duration={float(duration_out):.2f}s"
            )
    else:
        # ── Manual positioning mode ───────────────────────────────────────────
        max_x      = max(0, target_w_scaled - target_width)
        max_y      = max(0, scaled_h - target_height)
        crop_x_val = max(0, min(manual_x, max_x))
        crop_y_val = max(0, min(manual_y, max_y))
        crop_x       = str(crop_x_val)
        crop_y       = str(crop_y_val)
        duration_out = str(max(duration_src, 1.0))
        log(
            f"[MANUAL ] {filename} | src {src_w}x{src_h} → {target_w_scaled}x{scaled_h} "
            f"| zoom={zoom:.2f} | pos=({crop_x_val},{crop_y_val}px) "
            f"| fps={fps_render} | dur={float(duration_out):.2f}s"
        )

    # ── Extra visual-effects filters (all inactive at default values) ──────────
    extras = []
    if abs(hue_shift) > 0.1:
        extras.append(f"hue=h={hue_shift:.1f}")
    if noise_reduction > 0.05:
        nr = noise_reduction
        extras.append(f"hqdn3d={nr:.1f}:{nr * 0.75:.1f}:{nr * 4:.1f}:{nr * 3:.1f}")
    if film_grain > 0:
        extras.append(f"noise=alls={film_grain}:allf=t+u")
    if vignette_on:
        extras.append("vignette=PI/4")

    # Build the middle filter chain (eq + unsharp + optional extras)
    # When all advanced params are at default this produces the same string as v2.0.
    mid_filters = (
        f"eq=contrast={c}:saturation={s}:brightness={b}:gamma={g},"
        f"unsharp=5:5:{sl}:3:3:{sc}"
    )
    if extras:
        mid_filters += "," + ",".join(extras)

    # Conditionally apply scale and crop based on auto_action_enabled
    if auto_action_enabled:
        # If auto_action is enabled, dmd_auto_action.py has already handled scaling and cropping
        # The input `src_path` is already a 4:1 aspect ratio video with the correct framing.
        # We just need to scale it down to target_width x target_height and apply colorimetry.
        filter_graph_base = (
            f"[0:v]setpts=PTS-STARTPTS,fps={fps_render},scale={target_width}:{target_height}:flags=lanczos,format=rgb24,"
            f"{mid_filters}"
        )
    else:
        # Original filter graph with scaling and cropping
        filter_graph_base = (
            f"color=black:s={target_w_scaled}x{scaled_h}:r={fps_render}[bg];"
            f"[0:v]setpts=PTS-STARTPTS,fps={fps_render},scale={target_w_scaled}:-2:flags=lanczos[fg];"
            f"[bg][fg]overlay=0:0:shortest=1,format=rgb24,"
            f"{mid_filters},"
            f"crop={target_width}:{target_height}:{crop_x}:'{crop_y}'"
        )

    # ── Build filter graph (text via ffmpeg drawtext when available) ──────────
    if _use_ffmpeg_text:
        # Map position name → ffmpeg x/y expressions
        _pos_map = {
            "top_left":      ("2",              "2"),
            "top_center":    ("(w-text_w)/2",   "2"),
            "top_right":     ("w-text_w-2",     "2"),
            "middle_left":   ("2",              "(h-text_h)/2"),
            "middle_center": ("(w-text_w)/2",   "(h-text_h)/2"),
            "middle_right":  ("w-text_w-2",     "(h-text_h)/2"),
            "bottom_left":   ("2",              "h-text_h-2"),
            "bottom_center": ("(w-text_w)/2",   "h-text_h-2"),
            "bottom_right":  ("w-text_w-2",     "h-text_h-2"),
        }
        x_pos, y_pos = _pos_map.get(text_position, ("(w-text_w)/2", "h-text_h-2"))

        # Style modifiers (border = stroke, shadow = offset)
        if text_style == "bold":
            style_extra = f":borderw=1:bordercolor={text_color}"
        elif text_style == "outline":
            style_extra = ":borderw=1:bordercolor=black"
        elif text_style == "shadow":
            style_extra = ":shadowx=1:shadowy=1:shadowcolor=black@0.8"
        else:
            style_extra = ""

        # Background box
        if text_bg:
            bg_alpha = max(0.0, min(1.0, text_bg_opacity / 100.0))
            bg_extra = f":box=1:boxcolor=black@{bg_alpha:.2f}:boxborderw=2"
        else:
            bg_extra = ""

        drawtext_filter = (
            f"drawtext=fontfile='{font_path_str}':text='{text_content}':"
            f"fontsize={text_font_size}:fontcolor={text_color}:"
            f"x={x_pos}:y={y_pos}:fix_bounds=1"
            f"{style_extra}{bg_extra}"
        )
        filter_graph = f"{filter_graph_base},{drawtext_filter}[v_final];"
    else:
        filter_graph = f"{filter_graph_base}[v_final];"

    filter_graph += (
        "[v_final]split[v1][v2];"
        "[v1]palettegen=max_colors=256:reserve_transparent=0[pal];"
        f"[v2][pal]paletteuse=dither={dither}"
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # ── FFmpeg command ────────────────────────────────────────────────────────
    # When auto_action is enabled the preprocessed MP4 already has the exact
    # right duration (intro + tracking + short tail).  Playing it once
    # (-stream_loop 0) avoids ffmpeg padding the last frame to fill duration_out.
    # For all other modes we keep -stream_loop -1 so the scroll filter can run
    # longer than the source clip.
    stream_loop = "0" if auto_action_enabled else "-1"
    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    cmd += ["-stream_loop", stream_loop, "-t", duration_out, "-i", src_path]
    cmd += [
        "-filter_complex", filter_graph,
        "-gifflags", "-offsetting-transdiff",
        out_path
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if temp_pre_src and os.path.isdir(temp_pre_src):
        import shutil
        shutil.rmtree(temp_pre_src, ignore_errors=True)

    if result.returncode != 0:
        err = result.stderr.decode(errors="replace").strip().splitlines()
        last_line = err[-1] if err else "unknown error"
        log(f"[ERROR ] {filename} — ffmpeg: {last_line}", "error")
        return False, f"[ERROR] {filename} — {last_line}"

    # ── Pillow text overlay (post-processing fallback) ────────────────────────
    if _use_pillow_text:
        ok_txt, txt_msg = _apply_text_overlay_pillow(
            out_path, text_content_raw, font_path_str,
            text_font_size, text_color, text_position,
            style=text_style, bg=text_bg, bg_opacity=text_bg_opacity,
        )
        if ok_txt:
            log(f"[TEXT  ] {filename} — {txt_msg}")
        else:
            log(f"[TEXT  ] {filename} — Pillow text overlay failed: {txt_msg}", "warning")

    log(f"[OK    ] {filename}")
    return True, f"[OK] {filename}"


def process_folder(folder_in, folder_out, params=None, callback=None, progress_callback=None):
    """Batch-convert all supported video files in a folder to DMD GIFs.

    Args:
        folder_in:          Source folder path.
        folder_out:         Output folder path (created if absent).
        params:             Conversion parameters dict (merged with DEFAULT_PARAMS).
        callback:           Optional callable(message, level) for per-file log lines.
        progress_callback:  Optional callable(done: int, total: int) called after
                            each file completes — useful for progress bars.

    When auto_action is enabled the pipeline is split into two parallelised
    phases to avoid CPU over-subscription:

      Phase 1 — OpenCV preprocessing (all files, N workers)
        Each file gets a native-resolution 4:1 cropped intermediate MP4.

      Phase 2 — ffmpeg conversion (all files, N workers)
        ffmpeg processes the preprocessed MP4 (or original when phase 1 is
        skipped) to produce the final 128×32 DMD GIF.

    When auto_action is disabled the two phases are merged into a single pass
    (identical behaviour to the previous single-phase pipeline).
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    os.makedirs(str(folder_out), exist_ok=True)

    files = [
        f for f in os.listdir(str(folder_in))
        if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not files:
        logger.warning(f"No supported files found in {folder_in}")
        return []

    max_workers = p["max_workers"]
    auto_enabled = bool(p.get("auto_action_enabled", False))

    # ── Single-phase path (auto_action disabled — unchanged behaviour) ─────────
    if not auto_enabled:
        total = len(files)
        done_count = [0]
        done_lock  = __import__("threading").Lock()

        def _one(filename):
            src = os.path.join(str(folder_in), filename)
            out = os.path.join(str(folder_out), Path(filename).stem + ".gif")
            result = process_file(src, out, params=p, callback=callback)
            with done_lock:
                done_count[0] += 1
                current = done_count[0]
            if progress_callback:
                try:
                    progress_callback(current, total)
                except Exception:
                    pass
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(_one, files))

    # ── Two-phase path (auto_action enabled) ──────────────────────────────────
    # Phase 1: run OpenCV preprocessing for all files in parallel.
    # This avoids interleaving heavy HOG detection with ffmpeg on the same cores.
    def log(msg, level="info"):
        getattr(logger, level)(msg)
        if callback:
            callback(msg, level)

    action_cfg = AutoActionConfig(
        detector=str(p.get("action_detector", "person") or "person"),
        strength=float(p.get("action_strength", 0.65)),
        smoothness=float(p.get("action_smoothness", 0.85)),
        zoom_max=float(p.get("action_zoom_max", 1.8)),
        padding=float(p.get("action_padding", 0.20)),
        intro_duration=float(p.get("action_intro", 1.5)),
        bg_sub_enable=bool(p.get("bg_sub_enable", False)),
        bottom_crop_pct=float(p.get("action_bottom_crop", 0.0)),
        auto_bottom_crop=bool(p.get("action_auto_bottom_crop", False)),
        top_crop_pct=float(p.get("action_top_crop", 0.0)),
        auto_top_crop=bool(p.get("action_auto_top_crop", False)),
        vertical_bias=float(p.get("action_vertical_bias", 0.0)),
        auto_vertical_bias=bool(p.get("action_auto_vertical_bias", False)),
        smart_auto_crop=bool(p.get("action_smart_auto_crop", False)),
        target_width=p["target_width"],
        target_height=p["target_height"],
    )

    def _preprocess(filename):
        src = os.path.join(str(folder_in), filename)
        cfg = AutoActionConfig(
            detector=action_cfg.detector,
            strength=action_cfg.strength,
            smoothness=action_cfg.smoothness,
            zoom_max=action_cfg.zoom_max,
            padding=action_cfg.padding,
            intro_duration=action_cfg.intro_duration,
            bg_sub_enable=action_cfg.bg_sub_enable,
            bottom_crop_pct=action_cfg.bottom_crop_pct,
            auto_bottom_crop=action_cfg.auto_bottom_crop,
            top_crop_pct=action_cfg.top_crop_pct,
            auto_top_crop=action_cfg.auto_top_crop,
            vertical_bias=action_cfg.vertical_bias,
            auto_vertical_bias=action_cfg.auto_vertical_bias,
            smart_auto_crop=action_cfg.smart_auto_crop,
            target_width=action_cfg.target_width,
            target_height=action_cfg.target_height,
        )
        ok, pre_src, msg = preprocess_video_for_dmd(src, cfg)
        if ok and pre_src:
            log(f"[ACTION ] {filename} — {msg}")
            return filename, pre_src, os.path.dirname(pre_src)
        else:
            log(f"[ACTION ] {filename} — fallback: {msg}", "warning")
            return filename, src, None   # use original on failure

    log(f"[BATCH  ] Phase 1/2 — auto_action preprocessing ({len(files)} files, {max_workers} workers)")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        pre_results = list(ex.map(_preprocess, files))

    # Phase 2: run ffmpeg on all (pre-processed or original) sources in parallel.
    # Build a params copy with auto_action disabled so process_file skips
    # the preprocessor stage (it already ran in phase 1).
    p_no_action = {**p, "auto_action_enabled": False}

    log(f"[BATCH  ] Phase 2/2 — ffmpeg conversion ({len(files)} files, {max_workers} workers)")

    total_2     = len(files)
    done_count2 = [0]
    done_lock2  = __import__("threading").Lock()

    def _convert(item):
        filename, pre_src, tmpdir = item
        out = os.path.join(str(folder_out), Path(filename).stem + ".gif")
        success, msg = process_file(pre_src, out, params=p_no_action, callback=callback)
        if tmpdir and os.path.isdir(tmpdir):
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        with done_lock2:
            done_count2[0] += 1
            current = done_count2[0]
        if progress_callback:
            try:
                progress_callback(current, total_2)
            except Exception:
                pass
        return success, msg

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_convert, pre_results))

    return results


# ── CLI entry point ───────────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dmd_gif_converter.py",
        description=(
            "Convert any video/GIF to 128×32 DMD LED panel format.\n"
            "Without arguments, scans folders prefixed with 'gifs_' in the current\n"
            "directory and writes output to the matching folder without the prefix.\n\n"
            "Examples:\n"
            "  ./dmd_gif_converter.py\n"
            "  ./dmd_gif_converter.py --mode anime --workers 4\n"
            "  ./dmd_gif_converter.py gifs_Arcade gifs_Consoles\n"
            "  ./dmd_gif_converter.py --mode custom --saturation 2.8 --contrast 1.7\n"
            "  ./dmd_gif_converter.py --scroll-speed 32 --scroll-cycles 1.5\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p.add_argument(
        "folders", nargs="*", metavar="FOLDER",
        help="Source folder(s) to process (must start with --prefix). "
             "Default: all matching folders in current directory.",
    )

    # ── Preset ────────────────────────────────────────────────────────────────
    p.add_argument(
        "--mode", choices=["pixel_art", "anime", "cinema", "custom"],
        default=DEFAULT_PARAMS["mode"],
        help="Colorimetry preset. pixel_art=max saturation/sharpening (default), "
             "anime=softer, cinema=natural, custom=manual sliders.",
    )
    p.add_argument(
        "--prefix", default=DEFAULT_PARAMS["folder_prefix"], metavar="STR",
        help=f"Source folder prefix (default: '{DEFAULT_PARAMS['folder_prefix']}').",
    )
    p.add_argument(
        "--workers", type=int, default=DEFAULT_PARAMS["max_workers"], metavar="N",
        help=f"Parallel ffmpeg processes (default: {DEFAULT_PARAMS['max_workers']}). "
             "SSD+8 cores → 6–8, HDD/laptop → 2.",
    )

    # ── Scroll ────────────────────────────────────────────────────────────────
    p.add_argument(
        "--scroll-speed", type=float,
        default=DEFAULT_PARAMS["scroll_speed"], metavar="F",
        help=f"Scroll speed in px/s (default: {DEFAULT_PARAMS['scroll_speed']}).",
    )
    p.add_argument(
        "--scroll-cycles", type=float,
        default=DEFAULT_PARAMS["scroll_cycles"], metavar="F",
        help="Scroll cycle count + fractional stop position.\n"
             "  1.0  = 1 round-trip, stops at top\n"
             "  1.5  = 1 round-trip + stops at centre (default)\n"
             "  1.75 = 1 round-trip + stops at ¾\n"
             "  2.0  = 2 round-trips, stops at top",
    )
    p.add_argument(
        "--bottom-crop", type=float,
        default=DEFAULT_PARAMS["bottom_crop_pct"], metavar="F",
        help=f"Fraction of image bottom to ignore, 0–0.5 "
             f"(default: {DEFAULT_PARAMS['bottom_crop_pct']}).",
    )
    p.add_argument(
        "--top-crop", type=float,
        default=DEFAULT_PARAMS["top_crop_pct"], metavar="F",
        help=f"Fraction of image top to ignore, 0–0.5 "
             f"(default: {DEFAULT_PARAMS['top_crop_pct']}). "
             "Useful to skip title bars or top watermarks.",
    )

    # ── FPS ───────────────────────────────────────────────────────────────────
    p.add_argument(
        "--fps-min", type=float,
        default=DEFAULT_PARAMS["fps_min"], metavar="F",
        help=f"Minimum render FPS (default: {DEFAULT_PARAMS['fps_min']}).",
    )
    p.add_argument(
        "--fps-max", type=float,
        default=DEFAULT_PARAMS["fps_max"], metavar="F",
        help=f"Maximum render FPS / ESP32 cap (default: {DEFAULT_PARAMS['fps_max']}).",
    )

    # ── Custom colorimetry ────────────────────────────────────────────────────
    grp = p.add_argument_group("Custom colorimetry (only used with --mode custom)")
    grp.add_argument("--contrast",    type=float, default=DEFAULT_PARAMS["contrast"],    metavar="F")
    grp.add_argument("--saturation",  type=float, default=DEFAULT_PARAMS["saturation"],  metavar="F")
    grp.add_argument("--brightness",  type=float, default=DEFAULT_PARAMS["brightness"],  metavar="F")
    grp.add_argument("--gamma",       type=float, default=DEFAULT_PARAMS["gamma"],       metavar="F")
    grp.add_argument("--sharpen-lum", type=float, default=DEFAULT_PARAMS["sharpen_lum"], metavar="F")
    grp.add_argument("--sharpen-chr", type=float, default=DEFAULT_PARAMS["sharpen_chr"], metavar="F")
    grp.add_argument(
        "--dither", default=DEFAULT_PARAMS["dither"],
        choices=["none", "bayer:bayer_scale=1", "bayer:bayer_scale=2", "sierra2_4a"],
        metavar="STR",
        help="GIF dithering (default: none — use bayer only for static content).",
    )

    # ── Auto action framing (experimental pre-ffmpeg stage) ─────────────
    ag = p.add_argument_group("Auto action framing (experimental)")
    ag.add_argument(
        "--max-duration", type=float, default=DEFAULT_PARAMS["max_duration"], metavar="F",
        help="Hard cap on clip length in seconds (0 = no limit, default). "
             "Combined with trim-start to place the window anywhere in the source.",
    )
    ag.add_argument(
        "--auto-action", action="store_true", default=DEFAULT_PARAMS["auto_action_enabled"],
        help="Enable pre-ffmpeg cinematic auto framing (default: disabled).",
    )
    ag.add_argument(
        "--action-detector", default=DEFAULT_PARAMS["action_detector"],
        choices=["person", "motion", "hybrid", "center"],
        metavar="STR",
        help="Auto framing detector mode (default: person).",
    )
    ag.add_argument("--action-strength", type=float, default=DEFAULT_PARAMS["action_strength"], metavar="F")
    ag.add_argument("--action-smoothness", type=float, default=DEFAULT_PARAMS["action_smoothness"], metavar="F")
    ag.add_argument("--action-zoom-max", type=float, default=DEFAULT_PARAMS["action_zoom_max"], metavar="F")
    ag.add_argument("--action-padding", type=float, default=DEFAULT_PARAMS["action_padding"], metavar="F")
    ag.add_argument(
        "--bg-sub-enable", action="store_true", default=DEFAULT_PARAMS["bg_sub_enable"],
        help="Enable background subtraction (replaces background with black) (default: disabled).",
    )
    ag.add_argument(
        "--smart-auto-crop", action="store_true", default=DEFAULT_PARAMS["action_smart_auto_crop"],
        help="Smart Auto Crop: engine analyses context and activates the optimal combination of "
             "auto-bottom-crop, auto-top-crop and auto-floor-tracking (default: disabled).",
    )

    # ── Multi-dalle / Tiling ─────────────────────────────────────────────────
    mg = p.add_argument_group("Multi-dalle / Tiling")
    mg.add_argument(
        "--target-width", type=int, default=DEFAULT_PARAMS["target_width"], metavar="PX",
        help=f"Target output width in pixels (default: {DEFAULT_PARAMS['target_width']}).",
    )
    mg.add_argument(
        "--target-height", type=int, default=DEFAULT_PARAMS["target_height"], metavar="PX",
        help=f"Target output height in pixels (default: {DEFAULT_PARAMS['target_height']}).",
    )

    # ── Text Overlay ─────────────────────────────────────────────────────────
    tg = p.add_argument_group("Text Overlay")
    tg.add_argument(
        "--text-overlay", action="store_true", default=DEFAULT_PARAMS["text_overlay_enabled"],
        help="Enable text overlay on the output GIF (default: disabled).",
    )
    tg.add_argument(
        "--text-content", type=str, default=DEFAULT_PARAMS["text_content"], metavar="STR",
        help="Text content to overlay.",
    )
    tg.add_argument(
        "--text-font-size", type=int, default=DEFAULT_PARAMS["text_font_size"], metavar="PX",
        help="Font size for the text overlay (default: 8).",
    )
    tg.add_argument(
        "--text-color", type=str, default=DEFAULT_PARAMS["text_color"], metavar="COLOR",
        help="Color of the text (e.g., 'white', 'yellow', '#RRGGBB') (default: white).",
    )
    tg.add_argument(
        "--text-position", type=str, default=DEFAULT_PARAMS["text_position"], metavar="POS",
        choices=["top_left", "top_center", "top_right", "middle_left", "middle_center", "middle_right", "bottom_left", "bottom_center", "bottom_right"],
        help="Position of the text overlay (default: bottom_center).",
    )
    tg.add_argument(
        "--text-font-file", type=str, default=DEFAULT_PARAMS["text_font_file"], metavar="FILE",
        help=f"Font file to use for text overlay (default: '{DEFAULT_PARAMS['text_font_file']}'). "
             "Looks in media/fonts/ then media/ then script_dir.",
    )
    tg.add_argument(
        "--text-style", type=str, default=DEFAULT_PARAMS["text_style"],
        choices=["none", "bold", "outline", "shadow"], metavar="STYLE",
        help="Text rendering style: none | bold | outline (default) | shadow. "
             "'outline' adds a black border — best readability on 128×32.",
    )
    tg.add_argument(
        "--text-bg", action="store_true", default=DEFAULT_PARAMS["text_bg"],
        help="Draw a dark semi-transparent background box behind the text.",
    )
    tg.add_argument(
        "--text-bg-opacity", type=int, default=DEFAULT_PARAMS["text_bg_opacity"], metavar="N",
        help=f"Background box opacity 0-100 (default: {DEFAULT_PARAMS['text_bg_opacity']}).",
    )

    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()

    params = {
        "mode":           args.mode,
        "max_workers":    args.workers,
        "folder_prefix":  args.prefix,
        "scroll_speed":   args.scroll_speed,
        "scroll_cycles":  args.scroll_cycles,
        "bottom_crop_pct": args.bottom_crop,
        "top_crop_pct":   args.top_crop,
        "fps_min":        args.fps_min,
        "fps_max":        args.fps_max,
        "contrast":       args.contrast,
        "saturation":     args.saturation,
        "brightness":     args.brightness,
        "gamma":          args.gamma,
        "sharpen_lum":    args.sharpen_lum,
        "sharpen_chr":    args.sharpen_chr,
        "dither":         args.dither,
        "auto_action_enabled": args.auto_action,
        "action_detector": args.action_detector,
        "action_strength": args.action_strength,
        "action_smoothness": args.action_smoothness,
        "action_zoom_max": args.action_zoom_max,
        "action_padding": args.action_padding,
        "bg_sub_enable": args.bg_sub_enable,
        "action_smart_auto_crop": args.smart_auto_crop,
        "max_duration": args.max_duration,
        "target_width": args.target_width,
        "target_height": args.target_height,
        "text_overlay_enabled": args.text_overlay,
        "text_content": args.text_content,
        "text_font_size": args.text_font_size,
        "text_color": args.text_color,
        "text_position": args.text_position,
        "text_font_file": args.text_font_file,
        "text_style": args.text_style,
        "text_bg": args.text_bg,
        "text_bg_opacity": args.text_bg_opacity,
    }
    prefix = args.prefix

    if args.folders:
        source_folders = []
        for f in args.folders:
            if not os.path.isdir(f):
                logger.error(f"Not a directory: {f}")
                sys.exit(1)
            if not os.path.basename(f).startswith(prefix):
                logger.warning(f"'{f}' does not start with prefix '{prefix}' — processing anyway")
            source_folders.append(f)
    else:
        source_folders = [
            d for d in sorted(os.listdir("."))
            if os.path.isdir(d) and d.startswith(prefix)
        ]

    if not source_folders:
        logger.warning(
            f"No folder starting with '{prefix}' found in the current directory.\n"
            f"  Tip: place your source folders here as '{prefix}Arcade/', '{prefix}Consoles/', …\n"
            f"  Or pass folder paths directly:  ./dmd_gif_converter.py {prefix}Arcade"
        )
        sys.exit(0)

    for folder_in in source_folders:
        base = os.path.basename(folder_in.rstrip("/\\"))
        folder_out = base[len(prefix):] if base.startswith(prefix) else base + "_DMD"
        files = [
            f for f in sorted(os.listdir(folder_in))
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        logger.info(
            f"=== {folder_in} → {folder_out}  ({len(files)} file(s)) | mode={args.mode} ==="
        )
        process_folder(folder_in, folder_out, params=params)

    logger.info("Done.")