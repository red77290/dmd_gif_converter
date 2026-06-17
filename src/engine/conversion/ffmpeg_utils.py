import subprocess
import json
import logging
logger = logging.getLogger(__name__)

_drawtext_available = None  # bool or None (None = not yet checked)

def _check_drawtext() -> bool:
    """Return True if the installed ffmpeg has the drawtext filter (requires libfreetype)."""
    global _drawtext_available
    if _drawtext_available is None:
        try:
            r = subprocess.run(
                ["ffmpeg", "-filters"],
                capture_output=True, text=True, timeout=10
            )
            _drawtext_available = "drawtext" in (r.stdout + r.stderr)
        except Exception:
            _drawtext_available = False
    return _drawtext_available


# ── Pillow text overlay fallback ───────────────────────────────────────────────
_TEXT_COLOR_MAP = {
    "white":  (255, 255, 255, 255),
    "yellow": (255, 255,   0, 255),
    "red":    (255,   0,   0, 255),
    "green":  (  0, 255,   0, 255),
    "blue":   (  0,   0, 255, 255),
}

def _apply_text_overlay_pillow(
    gif_path: str,
    text: str,
    font_path_str: str,
    font_size: int,
    color_name: str,
    position: str,
    style: str = "outline",
    bg: bool = False,
    bg_opacity: int = 60,
    animation: str = "none",
) -> tuple[bool, str]:
    """Burn text onto every frame of an existing GIF using Pillow.

    Used as a fallback when ffmpeg is built without libfreetype (no drawtext filter).

    Supported styles:
        none    – plain text
        bold    – 1 px same-colour stroke (fatter text, good contrast on dark backgrounds)
        outline – 1 px black stroke (maximum readability on any background)
        shadow  – offset drop-shadow (depth effect)
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return False, "Pillow not available"

    try:
        img = Image.open(gif_path)
    except Exception as e:
        return False, "Cannot open GIF: %s" % e

    # ── Collect all frames as RGBA ─────────────────────────────────────────────
    frames_rgba: list = []
    durations:   list = []
    try:
        while True:
            durations.append(int(img.info.get("duration", 80)))
            frames_rgba.append(img.copy().convert("RGBA"))
            img.seek(img.tell() + 1)
    except EOFError:
        pass
    if not frames_rgba:
        return False, "GIF has no frames"

    # ── Load font (fall back to Pillow default) ────────────────────────────────
    try:
        font = ImageFont.truetype(font_path_str, font_size)
    except Exception:
        font = ImageFont.load_default()

    rgba_color  = _TEXT_COLOR_MAP.get(color_name.lower(), (255, 255, 255, 255))
    black_opaque = (0, 0, 0, 255)
    shadow_color = (0, 0, 0, 200)
    margin = 2

    # Stroke width used for bounding-box calculation (so text does not get clipped)
    stroke_w = 1 if style in ("bold", "outline") else 0

    # ── Draw text on every frame ───────────────────────────────────────────────
    out_frames: list = []
    current_time_ms = 0

    for i, frame in enumerate(frames_rgba):
        draw = ImageDraw.Draw(frame)
        w, h = frame.size

        # Time tracking for animations
        t_sec = current_time_ms / 1000.0
        current_time_ms += durations[i]

        # Bounding box including optional stroke so position maths is correct
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        if   position == "top_left":      base_x, base_y = margin,            margin
        elif position == "top_center":    base_x, base_y = (w - tw) // 2,     margin
        elif position == "top_right":     base_x, base_y = w - tw - margin,   margin
        elif position == "middle_left":   base_x, base_y = margin,            (h - th) // 2
        elif position == "middle_center": base_x, base_y = (w - tw) // 2,     (h - th) // 2
        elif position == "middle_right":  base_x, base_y = w - tw - margin,   (h - th) // 2
        elif position == "bottom_left":   base_x, base_y = margin,            h - th - margin
        elif position == "bottom_right":  base_x, base_y = w - tw - margin,   h - th - margin
        else:                             base_x, base_y = (w - tw) // 2,     h - th - margin  # bottom_center

        # Animations
        x, y = base_x, base_y
        
        if animation == "blink":
            # Blink every 0.5s - start VISIBLE
            if (t_sec % 1.0) > 0.5:
                out_frames.append(frame.convert("RGB"))
                continue  # Skip drawing text
                
        elif animation == "scroll_left":
            # Scroll left at 100px/sec
            offset_x = int(t_sec * 100) % (w + tw)
            x = w - offset_x
            y = base_y
            
        elif animation == "scroll_up":
            # Scroll up at 30px/sec
            offset_y = int(t_sec * 30) % (h + th)
            x = base_x
            y = h - offset_y

        # ── Optional background box ────────────────────────────────────────────
        if bg:
            text_bbox = draw.textbbox((x, y), text, font=font, stroke_width=stroke_w)
            pad = 2
            box_coords = (
                text_bbox[0] - pad, text_bbox[1] - pad,
                text_bbox[2] + pad, text_bbox[3] + pad,
            )
            alpha_val = max(0, min(255, int(bg_opacity * 255 / 100)))
            overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rectangle(box_coords, fill=(0, 0, 0, alpha_val))
            frame = Image.alpha_composite(frame, overlay)
            draw = ImageDraw.Draw(frame)

        # ── Text rendering (style-dependent) ──────────────────────────────────
        if style == "bold":
            # Stroke in the same colour → fatter glyph without a visible border
            draw.text((x, y), text, font=font, fill=rgba_color,
                      stroke_width=1, stroke_fill=rgba_color)
        elif style == "outline":
            # Black stroke → readable on any background
            draw.text((x, y), text, font=font, fill=rgba_color,
                      stroke_width=1, stroke_fill=black_opaque)
        elif style == "shadow":
            # Drop shadow 1 px down-right, then main text on top
            draw.text((x + 1, y + 1), text, font=font, fill=shadow_color)
            draw.text((x, y),         text, font=font, fill=rgba_color)
        else:
            # style == "none"
            draw.text((x, y), text, font=font, fill=rgba_color)

        out_frames.append(frame.convert("RGB"))

    # ── Re-encode as GIF ──────────────────────────────────────────────────────
    # Save directly from RGB: Pillow auto-quantises for GIF output.
    # Using a single save_all call preserves all frames and their durations.
    try:
        out_frames[0].save(
            gif_path,
            format="GIF",
            save_all=True,
            append_images=out_frames[1:],
            loop=0,
            duration=durations,
            optimize=False,
        )
    except Exception as e:
        return False, "Failed to save GIF with text: %s" % e

    return True, f"text overlay ({style}, anim: {animation}) applied via Pillow"

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
        "-show_entries", "stream_tags=rotate",
        "-show_entries", "stream_side_data=rotation",
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
            
        w, h = int(stream["width"]), int(stream["height"])
        
        # Check rotation to swap width/height if necessary (e.g., smartphone videos)
        rotation = 0
        if "tags" in stream and "rotate" in stream["tags"]:
            rotation = abs(int(float(stream["tags"]["rotate"])))
        elif "side_data_list" in stream:
            for sd in stream["side_data_list"]:
                if "rotation" in sd:
                    rotation = abs(int(float(sd["rotation"])))
                    break
                    
        if rotation in (90, 270):
            w, h = h, w
            
        return w, h, fps_src, duration
    except Exception as e:
        logger.warning(f"Could not read metadata ({file_path}): {e}")
        return None, None, 25.0, 0.0


