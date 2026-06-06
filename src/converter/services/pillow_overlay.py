"""
PillowOverlayService — wraps _apply_text_overlay_pillow from ffmpeg_utils.
Responsible for adding text overlay to a GIF using Pillow when FFmpeg
drawtext is not available.
"""
import logging
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


class PillowOverlayService:
    """Uses Pillow to burn text into an already-generated GIF."""

    def apply(self, gif_path: str, out_path: str, params: Dict[str, Any]) -> bool:
        """Apply text overlay from params onto gif_path, writing to out_path.

        Returns True on success, False on any failure.
        """
        from ..ffmpeg_utils import _apply_text_overlay_pillow
        import shutil

        text_content = params.get("text_content", "")
        font_file = params.get("text_font_file", "HelvetiPixel.ttf")
        font_size = params.get("text_font_size", 8)
        text_color = params.get("text_color", "white")
        text_position = params.get("text_position", "bottom_center")
        text_style = params.get("text_style", "outline")
        text_bg = params.get("text_bg", False)
        text_bg_opacity = params.get("text_bg_opacity", 60)

        # Resolve font file path
        import os
        _media_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "media", "fonts"
        )
        font_path = os.path.join(_media_dir, font_file) if font_file else None

        try:
            ok, msg = _apply_text_overlay_pillow(
                gif_path, text_content, font_path,
                font_size, text_color, text_position,
                style=text_style, bg=text_bg, bg_opacity=text_bg_opacity,
            )
            if ok and gif_path != out_path:
                shutil.copy2(gif_path, out_path)
            return ok
        except Exception as e:
            logger.warning("PillowOverlayService failed: %s", e)
            return False
