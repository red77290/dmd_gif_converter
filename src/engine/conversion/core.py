import io
import os
import sys
import subprocess
import math
import threading
import time
import concurrent.futures
import logging
from pathlib import Path
from src.engine.auto_action.pipeline import preprocess_video_for_dmd
from src.engine.auto_action import AutoActionConfig
try:
    from src.engine.conversion.colorimetry import analyze_and_compensate as _analyze_and_compensate
except Exception:
    _analyze_and_compensate = None
from src.engine.conversion.ffmpeg_utils import _check_drawtext, _apply_text_overlay_pillow, snap_to_clean_fps, get_metadata
from src.engine.conversion.quality import evaluate_gif_quality
from src.engine.conversion.hardware_accel import get_best_h264_encoder
import cv2

# Make cv2.VideoCapture thread-safe globally to prevent libavcodec abort traps during concurrent creation/release
_original_video_capture = cv2.VideoCapture
_cv2_global_lock = threading.Lock()

class SafeVideoCapture:
    def __init__(self, *args, **kwargs):
        with _cv2_global_lock:
            self._cap = _original_video_capture(*args, **kwargs)
            
    def __getattr__(self, item):
        return getattr(self._cap, item)
        
    def read(self, *args, **kwargs):
        return self._cap.read(*args, **kwargs)
        
    def set(self, *args, **kwargs):
        return self._cap.set(*args, **kwargs)
        
    def get(self, *args, **kwargs):
        return self._cap.get(*args, **kwargs)
        
    def isOpened(self):
        return self._cap.isOpened()
        
    def release(self):
        with _cv2_global_lock:
            if hasattr(self, "_cap") and self._cap is not None:
                self._cap.release()
                self._cap = None

cv2.VideoCapture = SafeVideoCapture

logger = logging.getLogger(__name__)


# ── FFmpeg subprocess helper ───────────────────────────────────────────────────

def _run_ffmpeg_with_drain(cmd: list, cancel_event=None) -> tuple:
    """Run an ffmpeg command while continuously draining its stderr pipe.

    **Why this exists — the pipe-buffer deadlock problem**
    When ffmpeg runs with ``stderr=subprocess.PIPE`` and produces verbose output
    (long scroll animations can exceed 100 s, generating hundreds of KB of
    progress stats), the ~64 KB OS pipe buffer fills up.  ffmpeg then blocks
    trying to write to stderr, ``poll()`` never returns → deadlock.

    This manifests as "Convert All" appearing sequential (all workers freeze
    simultaneously) or individual conversions hanging forever.

    The fix: a daemon drain-thread reads stderr in 4 KB chunks concurrently so
    the pipe never fills, while the main polling loop remains free to check the
    cancel event every 100 ms.

    Parameters
    ----------
    cmd           : ffmpeg command list (same as passed to subprocess.Popen)
    cancel_event  : optional threading.Event — set it to interrupt the process

    Returns
    -------
    (returncode: int, stderr_data: bytes)
        returncode == -1 signals cancellation (process was terminated).
    """
    _stderr_buf = io.BytesIO()
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _drain():
        try:
            while True:
                chunk = process.stderr.read(4096)
                if not chunk:
                    break
                _stderr_buf.write(chunk)
        except Exception:
            pass

    drain_thread = threading.Thread(target=_drain, daemon=True, name="ffmpeg-stderr-drain")
    drain_thread.start()

    while process.poll() is None:
        if cancel_event and cancel_event.is_set():
            process.terminate()
            process.wait()
            drain_thread.join(timeout=2)
            try:
                process.stderr.close()
            except Exception:
                pass
            return -1, _stderr_buf.getvalue()
        time.sleep(0.1)

    drain_thread.join(timeout=10)
    try:
        process.stderr.close()
    except Exception:
        pass
    return process.returncode, _stderr_buf.getvalue()


def _terminal_log(msg: str, level: str = "info") -> None:
    """Write a log line directly to the original stderr (sys.__stderr__).

    This bypasses the Python logging framework entirely and is therefore
    immune to any sys.stderr redirection performed by Tkinter, customtkinter,
    or OpenCV at runtime.  Used by process_file() to guarantee that
    conversion progress is always visible in the launch terminal.

    Format matches launcher.py's basicConfig:  HH:MM:SS [LEVEL  ] message
    """
    if level == "debug":
        return  # debug is only for the logging framework, not terminal
    try:
        _err = getattr(sys, "__stderr__", None) or sys.stderr
        if _err is None:
            return
        _ts = time.strftime("%H:%M:%S")
        _lvl = level.upper()[:7].ljust(7)
        _err.write(f"{_ts} [{_lvl}] {msg}\n")
        _err.flush()
    except Exception:
        pass


SUPPORTED_EXTENSIONS = {
    ".gif", ".mp4", ".avi", ".mkv", ".mov", ".webm",
    ".flv", ".wmv", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp"
}

# ── Default parameters ─────────────────────────────────────────────────────────
DEFAULT_PARAMS = {
    # Parallelism
    "max_workers": 0,
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
    "smart_ratio_bypass": True,
    "auto_action_enabled": False,
    "action_detector":     "person",   # person | motion | hybrid | center
    "action_auto_detector_fallback": False, # fallback to hybrid if person fails
    "action_strength":     0.65,       # 0..1 tighter framing around action
    "action_smoothness":   0.98,       # 0..0.98 camera smoothing
    "action_zoom_max":     1.0,        # max dynamic zoom factor (1.0 = no zoom into action)
    "action_padding":      0.20,       # ROI padding before aspect crop
    "action_subsample_frames": 3,      # Run YOLO every N frames
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
    # gamma 0.90 was darkening already-dark cinema content; 0.95 is more neutral.
    # contrast 1.35 (was 1.4) avoids crushing shadow detail in dark scenes.
    # brightness 0.00 (was -0.01) stops the slight push toward black in low-light.
    "cinema":    (  1.35,     1.3,   0.00,  0.95,  0.8,   0.2,   "none" ),
}

def process_file(src_path, out_path, params=None, start_s=None, end_s=None, callback=None, cancel_event=None):
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
        # 1. Always write directly to the original stderr — immune to
        #    sys.stderr redirection by Tkinter / customtkinter / OpenCV.
        _terminal_log(msg, level)
        # 2. Logging framework (test capture, external file handlers).
        getattr(logger, level)(msg)
        # 3. Callback for the UI log panel.
        if callback:
            callback(msg, level)

    if cancel_event and cancel_event.is_set():
        log(f"[CANCEL] {filename} — Cancelled before processing", "warning")
        return False, f"[CANCEL] {filename}"

    # Optional preprocessor temp dir (auto action mode).
    temp_pre_src = None
    # Keep a reference to the original source for keyframe analysis (auto-color
    # must analyse the original colours, not the auto-action crop).
    original_src = src_path

    src_w, src_h, fps_src, duration_full = get_metadata(src_path)
    if not src_w:
        log(f"[ERROR] {filename} — could not read metadata", "error")
        return False, f"[ERROR] {filename} — metadata unreadable"

    # Get target dimensions
    target_width = int(p.get("target_width", 128))
    target_height = int(p.get("target_height", 32))
    
    smart_ratio_bypass = bool(p.get("smart_ratio_bypass", True))

    if target_width == 0 or target_height == 0:
        keep_original_resolution = True
        target_width = src_w
        target_height = src_h
    else:
        keep_original_resolution = False

    is_perfect_ratio = False
    if src_w > 0 and src_h > 0 and target_height > 0:
        src_ratio = src_w / src_h
        target_ratio = target_width / target_height
        is_perfect_ratio = abs(src_ratio - target_ratio) < 0.05

    auto_action_enabled = bool(p.get("auto_action_enabled", False))

    if keep_original_resolution:
        p["scroll_enabled"] = False
        p["zoom"] = 1.0
        p["manual_x"] = 0
        p["manual_y"] = 0
        auto_action_enabled = False
        log(f"[BYPASS ] {filename} — Keep Original Resolution active ({src_w}x{src_h})", "info")
    elif is_perfect_ratio and auto_action_enabled and smart_ratio_bypass:
        auto_action_enabled = False
        log(f"[BYPASS ] {filename} — Source matches target ratio ({src_w}x{src_h}), auto-framing bypassed.", "info")

    # ── Auto action preprocessor (outside ffmpeg pipeline) ───────────────────
    # Default is disabled, so this block has zero effect unless explicitly enabled.
    if auto_action_enabled:
        cfg = AutoActionConfig.from_params(
            p,
            start_s=float(start_s) if start_s is not None and str(start_s).strip() != "" else None,
            end_s=float(end_s) if end_s is not None and str(end_s).strip() != "" else None
        )
        ok_pre, pre_src, pre_msg = preprocess_video_for_dmd(src_path, cfg, cancel_event=cancel_event, callback=callback)
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

    # ── Clip timing ───────────────────────────────────────────────────────
    trim_start   = float(start_s) if start_s is not None and str(start_s).strip() != "" else 0.0
    trim_end     = float(end_s)   if end_s   is not None and str(end_s).strip() != "" else duration_full

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
    text_color         = str(p.get("text_color", "white"))
    text_position      = str(p.get("text_position", "bottom_center"))
    text_font_file     = str(p.get("text_font_file", "HelvetiPixel.ttf"))
    text_style         = str(p.get("text_style", "outline"))
    text_animation     = str(p.get("text_animation", "none"))
    text_bg            = bool(p.get("text_bg", False))
    text_bg_opacity    = int(p.get("text_bg_opacity", 60))

    if text_overlay_enabled:
        log(f"[DEBUG ] {filename} — text_animation passed to core: '{text_animation}'", "debug")

    # Resolve font path
    script_dir = Path(__file__).parent          # src/engine/conversion/
    root_dir = script_dir.parent.parent.parent   # project root (dmd_gif_converter/)
    font_path = root_dir / "media" / "fonts" / text_font_file
    if not font_path.exists():
        font_path = root_dir / "media" / text_font_file
        if not font_path.exists():
            font_path = Path(text_font_file)
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
            
        anim_extra = ""
        if text_animation == "blink":
            # Blink every 0.5 seconds
            anim_extra = ":enable='lt(mod(t,1),0.5)'"
        elif text_animation == "scroll_left":
            # Scroll text from right to left
            x_pos = f"w-mod(t*50\\,w+tw)"
        elif text_animation == "scroll_up":
            # Scroll text from bottom to top
            y_pos = f"h-mod(t*30\\,h+th)"
            
        drawtext_filter = (
            f"drawtext=fontfile='{font_path_str}':text='{text_content}':"
            f"fontsize={text_font_size}:fontcolor={text_color}:"
            f"x={x_pos}:y={y_pos}:fix_bounds=1"
            f"{style_extra}{bg_extra}{anim_extra}"
        )
        filter_graph = f"{filter_graph_base},{drawtext_filter}[v_final];"
    else:
        filter_graph = f"{filter_graph_base}[v_final];"

    is_mp4 = out_path.lower().endswith(".mp4")

    if is_mp4:
        filter_graph += "[v_final]format=yuv420p[out]"
    else:
        filter_graph += (
            "[v_final]split[v1][v2];"
            "[v1]palettegen=max_colors=256:reserve_transparent=0[pal];"
            f"[v2][pal]paletteuse=dither={dither}[out]"
        )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # ── FFmpeg command ────────────────────────────────────────────────────────
    # When auto_action is enabled the preprocessed MP4 already has the exact
    # right duration (intro + tracking + short tail).  Playing it exactly once
    # without any -t cap or -stream_loop avoids ffmpeg padding glitches at the end.
    import multiprocessing
    max_workers = int(params.get("max_workers", 2) if params else 2)
    if max_workers <= 0:
        max_workers = max(1, min(16, (multiprocessing.cpu_count() or 4) // 2))
    ffmpeg_threads = max(1, multiprocessing.cpu_count() // max_workers)
    
    cmd = ["ffmpeg", "-y", "-threads", str(ffmpeg_threads)]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    
    if auto_action_enabled:
        cmd += ["-i", src_path]
    else:
        cmd += ["-stream_loop", "-1", "-t", duration_out, "-i", src_path]
        
    cmd += ["-filter_complex", filter_graph, "-map", "[out]"]
    
    if is_mp4:
        best_encoder = get_best_h264_encoder()
        if best_encoder == "libx264":
            cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        else:
            # For hardware encoders like nvenc/qsv/videotoolbox, preset 'ultrafast' or '-crf 23' might not be supported identically
            # so we use a high bitrate instead to guarantee quality and speed
            cmd += ["-c:v", best_encoder, "-b:v", "5M"]
    else:
        cmd += ["-gifflags", "-offsetting-transdiff", "-f", "gif"]
        
    cmd += [out_path]

    # ── Run ffmpeg with continuous stderr drain (prevents pipe-buffer deadlock) ─
    returncode, result_stderr = _run_ffmpeg_with_drain(cmd, cancel_event)
    if returncode == -1:
        log(f"[CANCEL] {filename} — ffmpeg interrupted by user", "warning")
        if temp_pre_src and os.path.isdir(temp_pre_src):
            import shutil
            shutil.rmtree(temp_pre_src, ignore_errors=True)
        return False, f"[CANCEL] {filename} interrupted"

    if (p.get("verbose") or p.get("log_level") == "DEBUG") and result_stderr:
        ffmpeg_log = result_stderr.decode(errors="replace").strip()
        if ffmpeg_log:
            log(f"[FFMPEG] {filename}:\n{ffmpeg_log}", "debug")

    if temp_pre_src and os.path.isdir(temp_pre_src):
        import shutil
        shutil.rmtree(temp_pre_src, ignore_errors=True)

    if returncode != 0:
        err = result_stderr.decode(errors="replace").strip().splitlines()
        last_line = err[-1] if err else "unknown error"
        log(f"[ERROR ] {filename} — ffmpeg: {last_line}", "error")
        return False, f"[ERROR] {filename} — {last_line}"

    if _use_pillow_text:
        ok_txt, txt_msg = _apply_text_overlay_pillow(
            out_path, text_content_raw, font_path_str,
            text_font_size, text_color, text_position,
            style=text_style, bg=text_bg, bg_opacity=text_bg_opacity,
            animation=text_animation,
        )
        if ok_txt:
            log(f"[TEXT  ] {filename} — {txt_msg}")
        else:
            log(f"[TEXT  ] {filename} — Pillow text overlay failed: {txt_msg}", "warning")

    # Run quality evaluation on the generated GIF for UI rating and the Cleanup Assistant
    try:
        q_res = evaluate_gif_quality(out_path)
        log(f"[QUALITY] {filename} — Quality Score: {q_res.get('score', 0)}% ({q_res.get('rating', 'Unknown')})")
    except Exception as e:
        log(f"[QUALITY] {filename} — Failed to evaluate quality: {e}", "warning")

    log(f"[OK    ] {filename}")
    return True, f"[OK] {filename}"


def process_folder(folder_in, folder_out, params=None, callback=None, progress_callback=None, cancel_event=None):
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

    v_auto_workers = p.get("auto_workers", True)
    if v_auto_workers:
        max_workers = max(1, min(16, (os.cpu_count() or 4) // 2))
    else:
        max_workers = p.get("max_workers", 0)
        if max_workers <= 0:
            max_workers = max(1, min(16, (os.cpu_count() or 4) // 2))

    auto_enabled = bool(p.get("auto_action_enabled", False))

    # ── Single-phase path (auto_action disabled — unchanged behaviour) ─────────
    if not auto_enabled:
        total = len(files)
        done_count = [0]
        done_lock  = __import__("threading").Lock()

        def _one(filename):
            if cancel_event and cancel_event.is_set():
                return False, "[CANCEL] Skipped"
            src = os.path.join(str(folder_in), filename)
            out = os.path.join(str(folder_out), Path(filename).stem + ".gif")
            result = process_file(src, out, params=p, callback=callback, cancel_event=cancel_event)
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
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass
        
    def log(msg, level="info"):
        _terminal_log(msg, level)
        getattr(logger, level)(msg)
        if callback:
            callback(msg, level)
    action_cfg = AutoActionConfig.from_params(p)
    action_cfg.is_batch = True

    def _preprocess(filename):
        src = os.path.join(str(folder_in), filename)
        cfg = action_cfg.copy()
        if cancel_event and cancel_event.is_set():
            return filename, src, None

        ok, pre_src, msg = preprocess_video_for_dmd(src, cfg, cancel_event=cancel_event, callback=log)
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
        if cancel_event and cancel_event.is_set():
            return False, "[CANCEL] Skipped"
        filename, pre_src, tmpdir = item
        out = os.path.join(str(folder_out), Path(filename).stem + ".gif")
        success, msg = process_file(pre_src, out, params=p_no_action, callback=callback, cancel_event=cancel_event)
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
