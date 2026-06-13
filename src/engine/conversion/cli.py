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

from src.engine.conversion import (
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
    ag.add_argument(
        "--action-auto-detector-fallback", action="store_true", default=DEFAULT_PARAMS.get("action_auto_detector_fallback", False),
        help="Dynamically switch to hybrid if person detects nothing.",
    )
    ag.add_argument("--action-strength", type=float, default=DEFAULT_PARAMS["action_strength"], metavar="F")
    ag.add_argument("--action-smoothness", type=float, default=DEFAULT_PARAMS["action_smoothness"], metavar="F")
    ag.add_argument("--action-zoom-max", type=float, default=DEFAULT_PARAMS["action_zoom_max"], metavar="F")
    ag.add_argument("--action-padding", type=float, default=DEFAULT_PARAMS["action_padding"], metavar="F")
    ag.add_argument("--action-intro", type=float, default=DEFAULT_PARAMS["action_intro"], metavar="F",
                    help="Establishing shot duration in seconds (default: 1.5).")
    ag.add_argument("--action-bottom-crop", type=float, default=DEFAULT_PARAMS["action_bottom_crop"], metavar="F",
                    help="Exclude bottom fraction of frame (manual, 0 = disabled).")
    ag.add_argument("--action-auto-bottom-crop", action="store_true", default=DEFAULT_PARAMS["action_auto_bottom_crop"],
                    help="Auto-detect bottom crop from ROI analysis.")
    ag.add_argument("--action-top-crop", type=float, default=DEFAULT_PARAMS["action_top_crop"], metavar="F",
                    help="Exclude top fraction of frame (manual, 0 = disabled).")
    ag.add_argument("--action-auto-top-crop", action="store_true", default=DEFAULT_PARAMS["action_auto_top_crop"],
                    help="Auto-detect top crop from ROI analysis.")
    ag.add_argument("--action-vertical-bias", type=float, default=DEFAULT_PARAMS["action_vertical_bias"], metavar="F",
                    help="Manual camera vertical shift (+1.0 = floor, -1.0 = ceiling).")
    ag.add_argument("--action-auto-vertical-bias", action="store_true", default=DEFAULT_PARAMS["action_auto_vertical_bias"],
                    help="Auto floor detect, overrides vertical bias.")
    ag.add_argument(
        "--bg-sub-enable", action="store_true", default=DEFAULT_PARAMS["bg_sub_enable"],
        help="Enable background subtraction (replaces background with black) (default: disabled).",
    )
    ag.add_argument(
        "--smart-auto-crop", action="store_true", default=DEFAULT_PARAMS["action_smart_auto_crop"],
        help="Smart Auto Crop: engine analyses context and activates the optimal combination of "
             "auto-bottom-crop, auto-top-crop and auto-floor-tracking (default: disabled).",
    )
    ag.add_argument(
        "--action-scene-type", type=str, default="",
        choices=["", "platformer", "talking_closeup", "full_body_tall",
                 "fighting_2d", "action_horizontal", "talking_medium",
                 "full_body_medium", "wide_shot", "action_moving",
                 "top_down_isometric", "first_person", "menu_static"],
        help="Manual scene type selection (default: none).",
    )
    ag.add_argument(
        "--action-auto-scene-type", action="store_true", default=False,
        help="Auto-detect scene type from content (overrides --action-scene-type).",
    )
    ag.add_argument(
        "--dynamic-scene", action="store_true", default=False,
        help="Classify the scene dynamically on every camera cut (requires --action-auto-scene-type).",
    )
    
    # ── A/B Testing ─────────────────────────────────────────────────────────
    ab = p.add_argument_group("A/B Testing (Scoring V2)")
    ab.add_argument(
        "--ab-test", action="store_true", default=False,
        help="Run A/B testing to compare scoring strategies on a single video file instead of converting it."
    )
    ab.add_argument(
        "--ab-test-strategies", type=str, default="baseline_v1,balanced_v2",
        help="Comma-separated list of scoring strategies to test (default: baseline_v1,balanced_v2)."
    )

    # ── AI Moments Extraction ───────────────────────────────────────────────
    am = p.add_argument_group("AI Moments Extraction")
    am.add_argument(
        "--ai-moments", action="store_true", default=False,
        help="Extract the best moments from videos and automatically convert them to GIFs."
    )
    am.add_argument(
        "--ai-moments-only", action="store_true", default=False,
        help="Extract AI moments but DO NOT convert them to GIFs (keeps the extracted mp4s)."
    )
    am.add_argument(
        "--ai-moments-count", type=int, default=10, metavar="N",
        help="Max number of moments to extract per video (default: 10)."
    )
    am.add_argument(
        "--ai-moments-strategy", type=str, default="balanced_v2",
        help="Scoring strategy to use for AI moments (default: balanced_v2)."
    )
    am.add_argument(
        "--ai-moments-dur-min", type=float, default=2.0, metavar="F",
        help="Minimum duration of an extracted moment in seconds (default: 2.0)."
    )
    am.add_argument(
        "--ai-moments-dur-max", type=float, default=5.0, metavar="F",
        help="Maximum duration of an extracted moment in seconds (default: 5.0)."
    )
    
    # ── Automation (Magic Mode) ──────────────────────────────────────────
    mm = p.add_argument_group("Automation (Magic Mode)")
    mm.add_argument(
        "--let-me-handle-it", action="store_true", default=False,
        help="Magic mode: overrides several settings to automatically enable Auto-Action, "
             "Smart Auto Crop, Auto-Colorimetry, and DMD Scoring.",
    )
    mm.add_argument(
        "--auto-color", action="store_true", default=False,
        help="Enable heuristic auto-colorimetry (brightness/contrast injection).",
    )
    mm.add_argument(
        "--reject-threshold", type=int, default=0, metavar="N",
        help="Automatically move generated GIFs to the trash if their DMD Visibility Score is strictly below N%% (0-100). Default: 0 (disabled).",
    )
    
    # ── Output & Logs ────────────────────────────────────────────────────────
    lg = p.add_argument_group("Output & Logs")
    lg.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Alias for --log-level DEBUG. Show detailed FFMPEG processing logs.",
    )
    lg.add_argument(
        "--log-level", type=str, default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set the logging level. Default is INFO.",
    )

    # ── Search & Download (Integrated CLI) ───────────────────────────────────
    sd = p.add_argument_group("Search & Download (Integrated CLI)")
    sd.add_argument(
        "--search-keyword", type=str, default="", metavar="STR",
        help="Download GIFs before converting. If set, searches this keyword and creates a source folder automatically.",
    )
    sd.add_argument(
        "--search-engine", type=str, default="DuckDuckGo", choices=["DuckDuckGo", "Tenor", "Giphy"],
        help="Search engine to use (default: DuckDuckGo).",
    )
    sd.add_argument(
        "--search-limit", type=int, default=10, metavar="N",
        help="Number of GIFs to download (default: 10).",
    )
    sd.add_argument(
        "--search-api-key", type=str, default="", metavar="STR",
        help="API key if required (for Tenor or Giphy).",
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

    # ── Advanced Positioning & Visual Effects ─────────────────────────────────
    av = p.add_argument_group("Advanced Positioning & Visual Effects")
    av.add_argument(
        "--no-scroll", action="store_false", dest="scroll_enabled", default=DEFAULT_PARAMS["scroll_enabled"],
        help="Disable automatic vertical scroll (enables manual crop mode).",
    )
    av.add_argument("--zoom", type=float, default=DEFAULT_PARAMS["zoom"], metavar="F",
                    help="Scale multiplier before crop (manual mode).")
    av.add_argument("--manual-x", type=int, default=DEFAULT_PARAMS["manual_x"], metavar="PX",
                    help="Horizontal crop offset px (manual mode).")
    av.add_argument("--manual-y", type=int, default=DEFAULT_PARAMS["manual_y"], metavar="PX",
                    help="Vertical crop offset px (manual mode).")
    av.add_argument("--hue-shift", type=float, default=DEFAULT_PARAMS["hue_shift"], metavar="F",
                    help="Hue rotation in degrees.")
    av.add_argument("--noise-reduction", type=float, default=DEFAULT_PARAMS["noise_reduction"], metavar="F",
                    help="hqdn3d strength.")
    av.add_argument("--film-grain", type=int, default=DEFAULT_PARAMS["film_grain"], metavar="N",
                    help="Additive noise amount.")
    av.add_argument("--vignette", action="store_true", default=DEFAULT_PARAMS["vignette"],
                    help="Apply edge darkening vignette.")

    return p


if __name__ == "__main__":
    args = _build_parser().parse_args()

    # Configure logging based on verbosity
    if args.verbose:
        args.log_level = "DEBUG"
        
    log_level = getattr(logging, args.log_level)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%H:%M:%S"
    )

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
        "action_scene_type": args.action_scene_type,
        "action_auto_scene_type": args.action_auto_scene_type,
        "dynamic_scene_detection": args.dynamic_scene,
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
        "log_level": args.log_level,
    }
    
    # Apply "Let Me Handle It" overrides
    if args.let_me_handle_it:
        params.update({
            "auto_color_enabled":     True,
            "auto_action_enabled":    True,
            "action_smart_auto_crop": True,
            "action_auto_scene_type": True,
            "dmd_visibility_score_enabled": True,
            "dmd_readability_score_enabled": True,
        })
    prefix = args.prefix

    # ── A/B Testing ─────────────────────────────────────────────────────────
    if args.ab_test:
        from src.engine.testing.ab_testing_engine import ABTestingEngine
        if not args.folders or not os.path.isfile(args.folders[0]):
            logger.error("A/B testing requires a single video file as the argument.")
            sys.exit(1)
            
        video_path = args.folders[0]
        strategies = [s.strip() for s in args.ab_test_strategies.split(",") if s.strip()]
        
        logger.info(f"Running A/B Test on {video_path} using strategies: {strategies}")
        engine = ABTestingEngine(video_path=video_path, target_w=128, target_h=32)
        report = engine.run(strategy_names=strategies)
        report.print_leaderboard()
        sys.exit(0)

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

    # ── Integrated Search & Download ──────────────────────────────────────────
    if args.search_keyword:
        logger.info(f"=== Search & Download: '{args.search_keyword}' via {args.search_engine} ===")
        try:
            from src.engine.conversion.services.gif_search_service import GifSearchService, GifSearchFilter
            service = GifSearchService()
            filters = GifSearchFilter(ratio="All")
            results = service.search(args.search_keyword, args.search_limit, args.search_engine, filters, api_key=args.search_api_key)
            
            if results:
                # Create a temporary source folder for the downloaded GIFs
                safe_keyword = "".join(c if c.isalnum() else "_" for c in args.search_keyword).strip("_")
                download_folder = f"{prefix}{safe_keyword}"
                os.makedirs(download_folder, exist_ok=True)
                
                downloaded_count = 0
                for i, result in enumerate(results):
                    if downloaded_count >= args.search_limit:
                        break
                    logger.info(f"Downloading {i+1}/{len(results)}: {result.url}")
                    file_path = service.download(result, download_folder, downloaded_count, args.search_keyword)
                    if file_path:
                        downloaded_count += 1
                
                logger.info(f"Downloaded {downloaded_count} GIFs to '{download_folder}'. Injecting into pipeline...")
                if download_folder not in source_folders:
                    source_folders.append(download_folder)
            else:
                logger.warning(f"No GIFs found for keyword '{args.search_keyword}'.")
        except Exception as e:
            logger.error(f"Search & Download failed: {e}")

    if not source_folders:
        logger.warning(
            f"No folder starting with '{prefix}' found in the current directory.\n"
            f"  Tip: place your source folders here as '{prefix}Arcade/', '{prefix}Consoles/', …\n"
            f"  Or pass folder paths directly:  ./dmd_gif_converter.py {prefix}Arcade\n"
            f"  Or use search to auto-download: ./dmd_gif_converter.py --search-keyword \"pixel art\""
        )
        sys.exit(0)

    # ── Integrated AI Moments Extraction ──────────────────────────────────────
    if args.ai_moments or args.ai_moments_only:
        logger.info(f"=== Extracting AI Moments (Count: {args.ai_moments_count}, Strategy: {args.ai_moments_strategy}) ===")
        import subprocess
        try:
            from src.engine.auto_action.ai_moments import AiMomentsEngine
            
            extracted_folders = []
            for folder_in in source_folders:
                tmp_dir = Path(folder_in) / "ai_moments_tmp"
                extracted_files_exist = False
                
                for file in sorted(os.listdir(folder_in)):
                    file_path = Path(folder_in) / file
                    if not file_path.is_file() or file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                        continue
                    if file_path.suffix.lower() == ".gif":
                        continue  # Skip GIFs for extraction
                        
                    logger.info(f"Analyzing {file} for AI moments...")
                    options = {
                        "count": args.ai_moments_count,
                        "strategy": args.ai_moments_strategy,
                        "w_action": 70.0,
                        "w_epic": 100.0,
                        "w_character": 40.0,
                        "w_loopable": 70.0,
                        "w_dmd": 100.0,
                        "dur_min": args.ai_moments_dur_min,
                        "dur_max": args.ai_moments_dur_max,
                        "auto_framing": args.auto_action,
                        "opt_dmd": True
                    }
                    
                    def _prog(msg, pct):
                        pass # Silent progress for CLI, or we could print it
                        
                    engine = AiMomentsEngine(str(file_path), options, _prog)
                    moments = engine.run()
                    
                    if not moments:
                        logger.warning(f"No moments found in {file}.")
                        continue
                        
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    base_name = file_path.stem
                    ext = file_path.suffix
                    
                    for i, m in enumerate(moments):
                        out_name = f"{base_name}_M{i+1}{ext}"
                        out_path = tmp_dir / out_name
                        
                        cmd = [
                            "ffmpeg", "-y", "-v", "warning",
                            "-ss", str(m.start_time),
                            "-i", str(file_path),
                            "-to", str(m.end_time - m.start_time),
                            "-c", "copy",
                            str(out_path)
                        ]
                        try:
                            subprocess.run(cmd, check=True)
                            logger.info(f"  Extracted: {out_name} (Score: {m.overall_score:.1f})")
                            extracted_files_exist = True
                        except subprocess.CalledProcessError as e:
                            logger.error(f"  Failed to extract moment {i+1} from {file}: {e}")
                
                if extracted_files_exist:
                    extracted_folders.append(str(tmp_dir))
                    
            if extracted_folders:
                if args.ai_moments_only:
                    logger.info("AI moments extracted successfully. Skipping GIF conversion as requested (--ai-moments-only).")
                    sys.exit(0)
                logger.info("Re-routing conversion to use extracted AI moments folders.")
                source_folders = extracted_folders
            else:
                logger.warning("No AI moments were extracted from any source folder. Aborting conversion.")
                sys.exit(0)
                
        except ImportError as e:
            logger.error(f"Failed to load AiMomentsEngine. Auto-action dependencies might be missing: {e}")
            sys.exit(1)

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
        
        progress_cb = None
        if args.log_level in ("WARNING", "ERROR") and len(files) > 0:
            print(f"Processing '{folder_in}' ({len(files)} files)...")
            def _progress(current, total):
                bar_len = 40
                filled = int(round(bar_len * current / float(total)))
                bar = '=' * filled + '-' * (bar_len - filled)
                sys.stdout.write(f'\r[{bar}] {current}/{total} ({current/total*100:.1f}%)')
                sys.stdout.flush()
                if current == total:
                    sys.stdout.write('\n')
            progress_cb = _progress

        process_folder(folder_in, folder_out, params=params, progress_callback=progress_cb)


if __name__ == "__main__":
    main()
