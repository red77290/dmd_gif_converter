#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny runner for the auto action preprocessor.

Example:
  python auto_action_cli.py input.mp4 --detector person --out pre.mp4
"""

import argparse
import logging
import shutil
import sys

from dmd_auto_action import AutoActionConfig, preprocess_video_for_dmd, available_detectors

# ── Module-level logger ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser(description="Run auto action framing preprocessor only.")
    p.add_argument("src", help="Source video path")
    p.add_argument("--out", help="Destination intermediate MP4 path")
    p.add_argument("--detector", default="person", choices=available_detectors())
    p.add_argument("--strength", type=float, default=0.65)
    p.add_argument("--smoothness", type=float, default=0.85)
    p.add_argument("--zoom-max", type=float, default=1.8)
    p.add_argument("--padding", type=float, default=0.20)
    p.add_argument("--scene-type", default="", choices=["", "platformer", "talking_closeup",
                   "full_body_tall", "fighting_2d", "action_horizontal", "talking_medium",
                   "full_body_medium", "wide_shot", "action_moving"],
                   help="Manual scene type (default: none)")
    p.add_argument("--auto-scene-type", action="store_true", default=False,
                   help="Auto-detect scene type from content (overrides --scene-type)")
    p.add_argument("--bottom-crop", type=float, default=0.0,
                   help="Fraction of image bottom to exclude from framing (0=disabled, e.g. 0.15)")
    p.add_argument("--auto-bottom-crop", action="store_true", default=False,
                   help="Auto-detect bottom crop boundary from ROI analysis (overrides --bottom-crop)")
    p.add_argument("--top-crop", type=float, default=0.0,
                   help="Fraction of image top to exclude from framing (0=disabled, e.g. 0.10)")
    p.add_argument("--auto-top-crop", action="store_true", default=False,
                   help="Auto-detect top crop boundary from ROI analysis (overrides --top-crop)")
    p.add_argument("--vertical-bias", type=float, default=0.0,
                   help="Shift camera center: +1.0=down (show floor/platformer), -1.0=up (show sky)")
    p.add_argument("--auto-floor-detect", action="store_true", default=False,
                   help="Auto floor detection: places ROI bottom at ~93%% of crop height (overrides --vertical-bias)")
    p.add_argument("--start", type=float, default=None)
    p.add_argument("--end", type=float, default=None)
    args = p.parse_args()

    cfg = AutoActionConfig(
        detector=args.detector,
        strength=args.strength,
        smoothness=args.smoothness,
        zoom_max=args.zoom_max,
        padding=args.padding,
        scene_type=args.scene_type,
        auto_scene_type=args.auto_scene_type,
        bottom_crop_pct=args.bottom_crop,
        auto_bottom_crop=args.auto_bottom_crop,
        top_crop_pct=args.top_crop,
        auto_top_crop=args.auto_top_crop,
        vertical_bias=args.vertical_bias,
        auto_vertical_bias=args.auto_floor_detect,
        start_s=args.start,
        end_s=args.end,
    )

    ok, out_path, msg = preprocess_video_for_dmd(args.src, cfg)
    if ok:
        logger.info("%s", msg)
    else:
        logger.error("%s", msg)
        return 1

    if args.out:
        shutil.copy2(out_path, args.out)
        logger.info("Saved → %s", args.out)
    else:
        logger.info("Generated → %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
