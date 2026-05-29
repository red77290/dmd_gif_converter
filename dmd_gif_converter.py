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
    #
    # scroll_cycles: number of round-trips + fractional stop position.
    #   integer part  = number of complete down→up cycles
    #   fractional part × scroll_dist = y position where the image stops and holds
    #
    #   Examples (scroll_dist = 64 px):
    #     1.0  → 1 full round-trip, holds at top     (y = 0)
    #     1.5  → 1 full round-trip, holds at centre  (y = 32 px)
    #     1.75 → 1 full round-trip, holds at ¾       (y = 48 px)
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

    src_w, src_h, fps_src, duration_full = get_metadata(src_path)
    if not src_w:
        log(f"[ERROR] {filename} — could not read metadata", "error")
        return False, f"[ERROR] {filename} — metadata unreadable"

    # ── Clip timing ───────────────────────────────────────────────────────────
    trim_start   = float(start_s) if start_s is not None else 0.0
    trim_end     = float(end_s)   if end_s   is not None else duration_full
    duration_src = max(0.1, trim_end - trim_start)

    # ── Colorimetry preset ────────────────────────────────────────────────────
    mode = p["mode"]
    if mode in _PRESETS:
        c, s, b, g, sl, sc, dither = _PRESETS[mode]
    else:
        c  = p["contrast"];  s  = p["saturation"]; b = p["brightness"]
        g  = p["gamma"];     sl = p["sharpen_lum"]; sc = p["sharpen_chr"]
        dither = p["dither"]

    fps_render  = snap_to_clean_fps(fps_src, p["fps_min"], p["fps_max"])
    scaled_h    = math.ceil(((128.0 / src_w) * src_h) / 2.0) * 2
    effective_h = math.floor(scaled_h * (1.0 - p["bottom_crop_pct"]) / 2) * 2
    effective_h = max(effective_h, 32)
    scroll_dist = effective_h - 32

    if scroll_dist > 0:
        step = max(1, round(p["scroll_speed"] / fps_render))

        # ── Cycle decomposition ───────────────────────────────────────────────
        # scroll_cycles = <integer full round-trips> + <fractional stop position>
        cycles   = float(p.get("scroll_cycles", 1.5))
        full_cyc = int(cycles)
        frac     = round(cycles - full_cyc, 10)   # guard fp drift (e.g. 1.5-1 = 0.5)

        # One-way frames: top→bottom (or bottom→top, same count)
        frames_one_way    = math.ceil(scroll_dist / step)
        frames_full_cycle = 2 * frames_one_way   # one complete down+up round-trip

        # Stop position: frac × scroll_dist  (pixels from top, on the way down)
        stop_pos      = min(round(frac * scroll_dist), scroll_dist)
        frames_partial = math.ceil(stop_pos / step) if stop_pos > 0 else 0

        # Frame counts
        n_cyc_end    = full_cyc * frames_full_cycle    # end of all full cycles
        frames_move  = n_cyc_end + frames_partial       # end of all movement
        frames_src   = max(1, round(duration_src * fps_render)) if duration_src > 0 else 1
        frames_total = max(frames_move + 1, frames_src) # +1 = at least 1 hold frame
        duration_out = str(frames_total / fps_render)

        # ── FFmpeg crop_y expression ──────────────────────────────────────────
        # n < n_cyc_end         → triangular wave (mod-based cycling)
        # n_cyc_end ≤ n < frames_move → partial downward pass to stop_pos
        # n ≥ frames_move       → hold at stop_pos
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
                # frac = 0 → hold at top (y=0) after last cycle
                crop_y = f"if(lt(n,{n_cyc_end}),{cycle_y},0)"
        else:
            # No full cycles: go down to stop_pos then hold
            if frac > 0:
                crop_y = (
                    f"if(lt(n,{frames_partial}),"
                    f"min(n*{step},{stop_pos}),"
                    f"{stop_pos})"
                )
            else:
                # cycles = 0 → static at top
                crop_y = "0"

        log(
            f"[SCROLL ] {filename} | src {src_w}x{src_h} → 128x{effective_h} "
            f"| scroll_dist={scroll_dist}px | cycles={cycles} "
            f"(full={full_cyc} frac={frac:.2f} stop={stop_pos}px) "
            f"| fps={fps_render} | step={step}px | total={float(duration_out):.2f}s"
        )
    else:
        duration_out = str(max(duration_src, 1.0))
        crop_y       = "(in_h-out_h)/2"
        log(
            f"[CENTER ] {filename} | src {src_w}x{src_h} → 128x{effective_h} (centered) "
            f"| fps_src={fps_src:.1f} → render={fps_render} | duration={float(duration_out):.2f}s"
        )

    filter_graph = (
        f"color=black:s=128x{scaled_h}:r={fps_render}[bg];"
        f"[0:v]setpts=PTS-STARTPTS,fps={fps_render},scale=128:-2:flags=lanczos[fg];"
        f"[bg][fg]overlay=0:0:shortest=1,format=rgb24,"
        f"eq=contrast={c}:saturation={s}:brightness={b}:gamma={g},"
        f"unsharp=5:5:{sl}:3:3:{sc},"
        f"crop=128:32:0:'{crop_y}'[v_crop];"
        "[v_crop]split[v1][v2];"
        "[v1]palettegen=max_colors=256:reserve_transparent=0[pal];"
        f"[v2][pal]paletteuse=dither={dither}"
    )

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # ── FFmpeg command ────────────────────────────────────────────────────────
    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    cmd += ["-stream_loop", "-1", "-t", duration_out, "-i", src_path]
    cmd += [
        "-filter_complex", filter_graph,
        "-gifflags", "-offsetting-transdiff",
        out_path
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    if result.returncode == 0:
        log(f"[OK    ] {filename}")
        return True, f"[OK] {filename}"
    else:
        err = result.stderr.decode(errors="replace").strip().splitlines()
        last_line = err[-1] if err else "unknown error"
        log(f"[ERROR ] {filename} — ffmpeg: {last_line}", "error")
        return False, f"[ERROR] {filename} — {last_line}"


def process_folder(folder_in, folder_out, params=None, callback=None):
    """Batch-convert all supported video files in a folder to DMD GIFs."""
    p = {**DEFAULT_PARAMS, **(params or {})}
    os.makedirs(str(folder_out), exist_ok=True)

    files = [
        f for f in os.listdir(str(folder_in))
        if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not files:
        logger.warning(f"No supported files found in {folder_in}")
        return []

    def _one(filename):
        src = os.path.join(str(folder_in), filename)
        out = os.path.join(str(folder_out), Path(filename).stem + ".gif")
        return process_file(src, out, params=p, callback=callback)

    with concurrent.futures.ThreadPoolExecutor(max_workers=p["max_workers"]) as ex:
        results = list(ex.map(_one, files))

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

    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()

    # Build params dict from CLI args
    params = {
        "mode":           args.mode,
        "max_workers":    args.workers,
        "folder_prefix":  args.prefix,
        "scroll_speed":   args.scroll_speed,
        "scroll_cycles":  args.scroll_cycles,
        "bottom_crop_pct": args.bottom_crop,
        "fps_min":        args.fps_min,
        "fps_max":        args.fps_max,
        "contrast":       args.contrast,
        "saturation":     args.saturation,
        "brightness":     args.brightness,
        "gamma":          args.gamma,
        "sharpen_lum":    args.sharpen_lum,
        "sharpen_chr":    args.sharpen_chr,
        "dither":         args.dither,
    }
    prefix = args.prefix

    # Resolve source folders
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

    # Process each folder
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
