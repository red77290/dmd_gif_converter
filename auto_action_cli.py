#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tiny runner for the auto action preprocessor.

Example:
  python auto_action_cli.py input.mp4 --detector person --out pre.mp4
"""

import argparse
import shutil
import sys

from dmd_auto_action import AutoActionConfig, preprocess_video_for_dmd, available_detectors


def main() -> int:
    p = argparse.ArgumentParser(description="Run auto action framing preprocessor only.")
    p.add_argument("src", help="Source video path")
    p.add_argument("--out", help="Destination intermediate MP4 path")
    p.add_argument("--detector", default="person", choices=available_detectors())
    p.add_argument("--strength", type=float, default=0.65)
    p.add_argument("--smoothness", type=float, default=0.85)
    p.add_argument("--zoom-max", type=float, default=1.8)
    p.add_argument("--padding", type=float, default=0.20)
    p.add_argument("--start", type=float, default=None)
    p.add_argument("--end", type=float, default=None)
    args = p.parse_args()

    cfg = AutoActionConfig(
        detector=args.detector,
        strength=args.strength,
        smoothness=args.smoothness,
        zoom_max=args.zoom_max,
        padding=args.padding,
        start_s=args.start,
        end_s=args.end,
    )

    ok, out_path, msg = preprocess_video_for_dmd(args.src, cfg)
    print(msg)
    if not ok or not out_path:
        return 1

    if args.out:
        shutil.copy2(out_path, args.out)
        print(f"Saved: {args.out}")
    else:
        print(f"Generated: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

