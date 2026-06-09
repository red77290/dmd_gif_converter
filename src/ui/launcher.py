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

# Fallback module-level logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] [UI] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
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