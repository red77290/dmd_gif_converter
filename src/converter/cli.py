#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dmd_gif_converter — Conversion engine for 128×32 DMD LED panels.

Can be imported as a module (process_file / process_folder) or run directly
from the command line for backward-compatible CLI usage.
"""
import os
import sys
import argparse
import logging
from pathlib import Path

from src.converter import (
    SUPPORTED_EXTENSIONS,
    DEFAULT_PARAMS,
    _PRESETS,
    process_file,
    process_folder,
    snap_to_clean_fps,
    get_metadata,
)

logger = logging.getLogger(__name__)

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
    
    # ── Automation (Let me handle it) ──────────────────────────────────────────
    am = p.add_argument_group("Automation (Magic Mode)")
    am.add_argument(
        "--let-me-handle-it", action="store_true", default=False,
        help="Magic mode: overrides several settings to automatically enable Auto-Action, "
             "Smart Auto Crop, Auto-Colorimetry, and DMD Scoring.",
    )
    am.add_argument(
        "--auto-color", action="store_true", default=False,
        help="Enable heuristic auto-colorimetry (brightness/contrast injection).",
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
        "auto_color_enabled": args.auto_color,
    }
    
    # Apply "Let Me Handle It" overrides
    if args.let_me_handle_it:
        params.update({
            "auto_color_enabled":     True,
            "auto_action_enabled":    True,
            "action_smart_auto_crop": True,
            "dmd_visibility_score_enabled": True,
            "dmd_readability_score_enabled": True,
        })
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