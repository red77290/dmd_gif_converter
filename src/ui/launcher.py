#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DMD GIF Converter — Graphical Interface Launcher
"""

import os
import sys
import logging
from pathlib import Path

# ── Suppress [mp3float @ ...] / Header missing messages (OpenCV/FFmpeg) ──────
# Must be set BEFORE any cv2 import.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import argparse
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--debug", action="store_true")
args, _ = parser.parse_known_args()

log_level = logging.DEBUG if args.debug else logging.INFO

# Fallback module-level logger
log_file = Path(__file__).parent.parent.parent.parent / "dmd_converter.log"
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)-7s] [UI] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(str(log_file), mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    try:
        from src.ui.app import main as ui_main
        ui_main()
    except ImportError as e:
        logger.critical(f"Failed to load UI components: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()