# -*- coding: utf-8 -*-
import os
import subprocess
import math
import concurrent.futures
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# ── Parallelism ───────────────────────────────────────────────────────────────
# Each worker spawns an independent ffmpeg process (no shared state, no conflicts).
# The real bottleneck is CPU (decode + filters + GIF encode), not disk I/O.
#   SSD  + 8+ cores + 16GB+ RAM  → 6–8 workers, no problem
#   SSD  + 4  cores + 8GB  RAM   → 3–4 workers recommended
#   HDD  or thermal-throttled laptop → 2 workers (I/O Wait)
# MacBook Pro M3 Pro 36GB         → 8 workers optimal (11 cores, NVMe SSD, unified RAM)
MAX_WORKERS = 2

# Source folders must start with this prefix; output folders strip it.
# Example: "gifs_Arcade" → "Arcade"
FOLDER_PREFIX = "gifs_"

# ── Scroll ────────────────────────────────────────────────────────────────────
# Target vertical scroll speed in pixels per second.
# Increase for faster scroll, decrease for slower.
SCROLL_SPEED_PX_S = 24.0

# Fraction of the image bottom to ignore when computing scroll distance.
# The bottom of a sprite (feet, floor, empty background) rarely contains
# important content — trimming it reduces scroll distance and makes the
# motion less aggressive.
#   0.00 = use full image height
#   0.15 = ignore bottom 15% (recommended)
#   0.25 = ignore bottom 25% (very short scroll, near-static feel)
BOTTOM_CROP_PCT = 0.15

# Pause duration at the center position before restarting the cycle (seconds).
# Scroll sequence per cycle:  top → bottom → center → [pause] → (loop to top)
# The center is where the main action is usually visible.
#   0.0 = no pause, cuts straight back to top
#   1.5 = recommended — gives the viewer time to see the action
PAUSE_CENTER_S = 1.5

# ── Render FPS ────────────────────────────────────────────────────────────────
# For GIF files, ffprobe often reports r_frame_rate="100/1" (centisecond base),
# which is NOT the actual playback FPS. We use avg_frame_rate instead, then
# clamp to a sensible range for the ESP32.
#   Below FPS_MIN → upsample  (smoother scroll on slow-fps sources)
#   Above FPS_MAX → downsample (avoids huge files and ESP32 overload)
FPS_MIN = 10.0   # upsample sources below this value
FPS_MAX = 25.0   # hard cap for ESP32 compatibility

# GIF "clean" FPS values: the frame delay (100 / fps) must be a whole centisecond.
# Example: 15fps → 6.67cs → rounds to 7cs → actual fps = 14.28fps → visible judder!
# Allowed values: 10cs=10fps, 8cs=12.5fps, 5cs=20fps, 4cs=25fps
_CLEAN_GIF_FPS = [10.0, 12.5, 20.0, 25.0]

def snap_to_clean_fps(fps: float) -> float:
    """Round to the nearest clean GIF FPS to avoid judder from centisecond quantization."""
    fps_clamped = max(FPS_MIN, min(FPS_MAX, fps))
    return min(_CLEAN_GIF_FPS, key=lambda f: abs(f - fps_clamped))

# ── Content Mode ─────────────────────────────────────────────────────────────
# Switch all colorimetry presets based on the type of source GIF.
#
#   "pixel_art" → retro game sprites, arcade marquees, console GIFs, anime
#                 ★ DEFAULT — identical output to the original moving_gif_V0.py
#                 max saturation & sharpening, no dithering (pure flat colors)
#
#   "anime"     → softer alternative for anime/cartoons with complex gradients
#                 slightly reduced saturation & sharpening vs pixel_art
#                 (use this only if pixel_art feels too aggressive for your source)
#
#   "cinema"    → live-action movie clips, real photography
#                 natural saturation, minimal sharpening
#
#   "custom"    → use the individual CONTRAST / SATURATION / ... values below
#
# NOTE: all modes use dither="none" — Bayer dithering creates persistent vertical
# streaks in the scroll direction (pattern is fixed in screen coords, content moves).
MODE = "pixel_art"   # "pixel_art" | "anime" | "cinema" | "custom"

_PRESETS = {
    #               contrast  sat    bright  gamma  sh_lum sh_chr  dither
    "pixel_art": (  1.6,      2.2,  -0.03,  0.85,  1.8,   0.5,   "none" ),
    "anime":     (  1.5,      1.9,  -0.02,  0.87,  1.3,   0.3,   "none" ),
    "cinema":    (  1.4,      1.3,  -0.01,  0.90,  0.8,   0.2,   "none" ),
}
# ⚠️  WHY ALL MODES USE dither="none":
# Any ordered dithering (Bayer) applies its pattern in OUTPUT frame coordinates (fixed
# on screen). As the content scrolls, the same pixels appear at different y positions
# each frame → the Bayer grid stays still while content moves → persistent vertical
# streaks in the scroll direction.
# Error-diffusion (sierra2_4a) causes temporal noise that "crawls" frame to frame.
# At 128×32 with 256 colors, flat quantization ("none") gives cleaner results than
# any dithering mode for scrolling content.
# Exception: if your GIF is purely STATIC (no scroll, distance ≤ 0), you can safely
# set DITHER = "bayer:bayer_scale=1" in "custom" mode for smoother gradients.

# ── HUB75 LED Panel Colorimetry (used when MODE = "custom") ───────────────────
CONTRAST    = 1.6
SATURATION  = 2.2
BRIGHTNESS  = -0.03
GAMMA       = 0.85
SHARPEN_LUM = 1.8
SHARPEN_CHR = 0.5
DITHER      = "none"


def get_metadata(file_path):
    """Extract width, height, playback FPS and duration from a GIF using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames",
        "-show_entries", "format=duration",
        "-of", "json", file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = json.loads(res.stdout.strip())
        stream = data["streams"][0]

        # avg_frame_rate = total_frames / total_duration → actual playback FPS.
        # r_frame_rate for GIFs is often "100/1" (centisecond base clock) → unusable.
        fps_str = stream.get("avg_frame_rate") or stream.get("r_frame_rate", "25/1")
        num, den = map(int, fps_str.split("/"))
        fps_src = (num / den) if (den and num) else 25.0
        # Guard against aberrant values (0fps, 100fps...)
        fps_src = max(1.0, min(100.0, fps_src))

        # Prefer format-level duration (more accurate than nb_frames / fps)
        duration = float(data.get("format", {}).get("duration", 0) or 0)
        if duration <= 0 and stream.get("nb_frames", "N/A") != "N/A":
            duration = int(stream["nb_frames"]) / fps_src

        return int(stream["width"]), int(stream["height"]), fps_src, duration
    except Exception as e:
        logger.warning(f"Could not read metadata ({file_path}): {e}")
        return None, None, 25.0, 0.0


def process_file(filename, folder_in, folder_out):
    """Convert a single GIF to 128×32 DMD format with ping-pong scroll or centering."""
    src_path = os.path.join(folder_in, filename)
    src_w, src_h, fps_src, duration_src = get_metadata(src_path)

    if not src_w:
        logger.error(f"[ERROR] {filename} — could not read metadata")
        return f"  [ERROR] {filename} - metadata unreadable"

    # Resolve colorimetry preset
    if MODE in _PRESETS:
        c, s, b, g, sl, sc, dither = _PRESETS[MODE]
    else:
        c, s, b, g, sl, sc, dither = CONTRAST, SATURATION, BRIGHTNESS, GAMMA, SHARPEN_LUM, SHARPEN_CHR, DITHER


    # Snap FPS to nearest clean GIF value to avoid judder from centisecond rounding
    fps_render = snap_to_clean_fps(fps_src)

    # Scale width to 128px, compute proportional height rounded up to nearest even number
    scaled_h = math.ceil(((128.0 / src_w) * src_h) / 2.0) * 2

    # Effective height: trim the bottom BOTTOM_CROP_PCT of the image.
    # The bottom of a sprite (feet, floor) rarely matters — reducing it shortens
    # the scroll distance and makes the motion less aggressive.
    effective_h = math.floor(scaled_h * (1.0 - BOTTOM_CROP_PCT) / 2) * 2
    effective_h = max(effective_h, 32)   # must be at least 32px (panel height)

    scroll_dist = effective_h - 32   # pixels to scroll (0 = image fits, center it)

    if scroll_dist > 0:
        # ── Scroll: top → bottom → center → hold → (loop) ───────────────────
        # Step size (px/frame) to maintain a constant scroll speed regardless of FPS
        step = max(1, round(SCROLL_SPEED_PX_S / fps_render))

        # Center of the image = where the action is
        center = scroll_dist // 2

        frames_down = math.ceil(scroll_dist / step)              # top → bottom
        frames_up   = math.ceil((scroll_dist - center) / step)   # bottom → center
        frames_hold = round(PAUSE_CENTER_S * fps_render)          # hold at center
        frames_sequence = frames_down + frames_up + frames_hold

        duration_cycle = frames_sequence / fps_render
        num_cycles  = max(1, math.ceil(duration_src / duration_cycle)) if duration_src > 0 else 1
        duration_out = str(num_cycles * duration_cycle)

        # n_seq = position within the current cycle (resets every frames_sequence)
        # Phase 1 (n_seq ≤ frames_down)  : scroll down  0 → scroll_dist
        # Phase 2 (n_seq > frames_down)  : scroll up    scroll_dist → center
        #   max(..., center) naturally holds at center for the remaining frames_hold
        n_seq  = f"mod(n,{frames_sequence})"
        crop_y = (
            f"if(lte({n_seq},{frames_down}),"
            f"min({n_seq}*{step},{scroll_dist}),"
            f"max({scroll_dist}-({n_seq}-{frames_down})*{step},{center}))"
        )

        logger.info(
            f"[SCROLL ] {filename} | src {src_w}x{src_h} "
            f"→ 128x{scaled_h} (effective 128x{effective_h}, crop→128x32) | "
            f"scroll={scroll_dist}px | center={center}px | "
            f"fps={fps_render}fps ({100/fps_render:.0f}cs) | step={step}px | "
            f"speed≈{step*fps_render:.0f}px/s | down={frames_down}f up={frames_up}f hold={frames_hold}f | "
            f"cycle={duration_cycle:.2f}s×{num_cycles}={float(duration_out):.2f}s"
        )
    else:
        # ── Static centering ─────────────────────────────────────────────────
        # GIF is wider than tall (logo / banner) → center vertically on the 32px panel.
        # Use the source's natural duration (avoids cutting to 0.1s bug).
        duration_out = str(max(duration_src, 1.0))
        crop_y = "(in_h-out_h)/2"
        logger.info(
            f"[CENTER ] {filename} | src {src_w}x{src_h} "
            f"→ 128x{scaled_h} (effective 128x{effective_h}, centered) | "
            f"fps_src={fps_src:.1f} → render={fps_render:.0f} | duration={float(duration_out):.2f}s"
        )

    # ── FFmpeg filter graph ───────────────────────────────────────────────────
    # Step 1  color=black + overlay  → composites the source onto a solid black background,
    #         eliminating any source transparency (sprites with alpha, transparent frames).
    #         Without this, transparent pixels pass through to the ESP32 frame buffer
    #         (i.e., the clock shows through the GIF).
    # Step 2  setpts=PTS-STARTPTS   → resets timestamps before the fps filter so that
    #         stream_loop restarts don't cause a duplicate/dropped frame at the loop boundary.
    # Step 3  fps + scale=128:-2    → constant framerate + proportional scale (:-2 = even height).
    # Step 4  eq + unsharp          → HUB75 LED colorimetry boost.
    # Step 5  crop 128×32 FIRST     → palettegen only sees the pixels actually displayed.
    # Step 6  palettegen + paletteuse → 256-color palette, no dithering.
    filter_graph = (
        # Solid black background at the correct resolution and FPS
        f"color=black:s=128x{scaled_h}:r={fps_render}[bg];"
        # Source: normalize timestamps, then force constant FPS and scale
        f"[0:v]setpts=PTS-STARTPTS,fps={fps_render},scale=128:-2:flags=lanczos[fg];"
        # Composite GIF over black background → zero transparent pixels possible
        f"[bg][fg]overlay=0:0:shortest=1,format=rgb24,"
        # HUB75 LED colorimetry
        f"eq=contrast={c}:saturation={s}:brightness={b}:gamma={g},"
        f"unsharp=5:5:{sl}:3:3:{sc},"
        # Ping-pong crop → final 128×32 window
        f"crop=128:32:0:'{crop_y}'[v_crop];"
        # Palette generated from the actual visible pixels (256 colors = GIF max)
        "[v_crop]split[v1][v2];"
        "[v1]palettegen=max_colors=256:reserve_transparent=0[pal];"
        f"[v2][pal]paletteuse=dither={dither}"
    )

    out_path = os.path.join(folder_out, filename)
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-t", duration_out,
        "-i", src_path, "-filter_complex", filter_graph,
        # Disable GIF muxer transparency compression:
        #   transdiff  → marks unchanged pixels as transparent (delta encoding)
        #                → ESP32 frames buffer shows through (clock, previous GIF...)
        #   offsetting → partial-frame offset trick, same transparency side-effect
        "-gifflags", "-offsetting-transdiff",
        out_path
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode == 0:
        logger.info(f"[OK    ] {filename}")
        return f"  [OK] {filename}"
    else:
        err = result.stderr.decode(errors="replace").strip().splitlines()
        last_line = err[-1] if err else "unknown error"
        logger.error(f"[ERROR ] {filename} — ffmpeg failed: {last_line}")
        return f"  [ERROR] {filename} - render failed"


if __name__ == "__main__":
    source_folders = [
        d for d in os.listdir(".")
        if os.path.isdir(d) and d.startswith(FOLDER_PREFIX)
    ]

    if not source_folders:
        logger.warning(f"No folder starting with '{FOLDER_PREFIX}' found in the current directory.")
    else:
        for folder_in in source_folders:
            folder_out = folder_in[len(FOLDER_PREFIX):]
            os.makedirs(folder_out, exist_ok=True)
            files = [f for f in os.listdir(folder_in) if f.lower().endswith(".gif")]

            logger.info(f"=== Processing: {folder_in} → {folder_out} ({len(files)} file(s)) | mode={MODE} ===")

            # Each worker is an independent ffmpeg process — no shared state, safe to parallelize
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                list(executor.map(
                    lambda f, fi=folder_in, fo=folder_out: process_file(f, fi, fo),
                    files
                ))

