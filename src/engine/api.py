"""
Public Headless Library API for dmd_gif_converter.

Provides a clean, stateless, headless facade (`DmdMediaProcessor`) to convert
video trailers/snaps and promotional images (posters, backdrops, marquees)
into LED-matrix-optimized assets (.gif, .png, raw .rgb565, and .rgb565.stream)
with zero GUI (Tkinter/CustomTkinter) dependencies.
"""

from __future__ import annotations

import io
import logging
import math
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from src.engine.conversion.core import (
    DEFAULT_PARAMS,
    LET_ME_HANDLE_PARAMS,
    process_file,
    resolve_panorama_scroll_axis,
)
from src.engine.conversion.ffmpeg_utils import get_metadata
from src.engine.conversion.quality import evaluate_gif_quality

logger = logging.getLogger(__name__)

__version__ = "8.0.8"

DMDS_MAGIC = b"DMDS"
DMDS_VERSION = 1
DMDS_HEADER_FORMAT = "<4sBBHHHHH"
DMDS_HEADER_SIZE = struct.calcsize(DMDS_HEADER_FORMAT)  # 16 bytes


@dataclass(frozen=True)
class DmdClipConfig:
    """Configuration for headless DMD video clip extraction and conversion."""

    width: int = 128
    height: int = 32
    fps: int = 15
    max_duration_s: float = 8.0
    skip_intro_pct: float = 0.12
    skip_outro_pct: float = 0.15
    mode: Literal["pixel_art", "anime", "cinema", "custom"] = "pixel_art"
    use_ai_moments: bool = True
    use_auto_action: bool = True
    use_smart_color_boost: bool = True
    scroll_enabled: bool = False
    scroll_direction: str = "auto"
    brightness: float = -0.02
    contrast: float = 1.45
    saturation: float = 1.85
    gamma: float = 0.90
    dither: Literal["none", "bayer", "floyd_steinberg"] = "none"


@dataclass(frozen=True)
class DmdProcessedAssets:
    """Result bundle produced by DmdMediaProcessor.process_video_trailer."""

    gif_path: Optional[Path]
    rgb565_stream_path: Optional[Path]
    frame_count: int
    fps: int
    width: int
    height: int
    duration_s: float
    quality_score: int
    selected_start_s: float
    selected_end_s: float


def rgb888_to_rgb565_le(rgb_array: np.ndarray) -> bytes:
    """
    Convert an (H, W, 3) uint8 RGB image array to little-endian RGB565 raw bytes.
    """
    if rgb_array.ndim != 3 or rgb_array.shape[2] < 3:
        raise ValueError(f"Expected (H, W, 3+) array, got shape {rgb_array.shape}")

    r = rgb_array[:, :, 0].astype(np.uint16)
    g = rgb_array[:, :, 1].astype(np.uint16)
    b = rgb_array[:, :, 2].astype(np.uint16)

    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return rgb565.astype("<u2").tobytes()


def rgb565_le_to_rgb888(data: bytes, width: int, height: int) -> np.ndarray:
    """
    Convert little-endian RGB565 raw bytes back to an (H, W, 3) uint8 RGB array.
    """
    expected = width * height * 2
    if len(data) != expected:
        raise ValueError(f"Expected {expected} bytes for {width}x{height}, got {len(data)}")

    arr = np.frombuffer(data, dtype="<u2").reshape((height, width))
    r = ((arr >> 11) & 0x1F) << 3
    g = ((arr >> 5) & 0x3F) << 2
    b = (arr & 0x1F) << 3
    return np.stack([r, g, b], axis=-1).astype(np.uint8)


def write_rgb565_stream(
    frames_rgb: Sequence[np.ndarray],
    out_path: Path | str,
    fps: int = 15,
) -> int:
    """
    Write a sequence of (H, W, 3) uint8 RGB frames into a `.rgb565.stream` file.

    Binary layout:
      - 16-byte header (`<4sBBHHHHH`):
          magic[4]       = b"DMDS"
          version        = 1 (uint8)
          fps            = fps (uint8)
          width          = frame width (uint16 LE)
          height         = frame height (uint16 LE)
          total_frames   = number of frames (uint16 LE)
          frame_delay_ms = round(1000 / fps) (uint16 LE)
          reserved       = 0 (uint16 LE)
      - Contiguous frame payloads of `width * height * 2` bytes each (RGB565 LE).

    Returns:
        Number of frames written.
    """
    if not frames_rgb:
        raise ValueError("Cannot write an empty frame sequence to .rgb565.stream")

    first = frames_rgb[0]
    height, width = int(first.shape[0]), int(first.shape[1])
    fps_clamped = max(1, min(120, int(fps)))
    frame_delay_ms = max(1, int(round(1000.0 / fps_clamped)))
    total_frames = min(65535, len(frames_rgb))

    header = struct.pack(
        DMDS_HEADER_FORMAT,
        DMDS_MAGIC,
        DMDS_VERSION,
        fps_clamped,
        width,
        height,
        total_frames,
        frame_delay_ms,
        0,
    )

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header)
        for idx in range(total_frames):
            frame = frames_rgb[idx]
            if frame.shape[0] != height or frame.shape[1] != width:
                pil_img = Image.fromarray(frame[:, :, :3]).resize(
                    (width, height), Image.Resampling.LANCZOS
                )
                frame = np.asarray(pil_img, dtype=np.uint8)
            f.write(rgb888_to_rgb565_le(frame))

    return total_frames


def read_rgb565_stream_header(source: Path | str | bytes) -> dict:
    """
    Parse and validate the 16-byte header of a `.rgb565.stream` file or buffer.
    """
    if isinstance(source, (str, Path)):
        with open(source, "rb") as f:
            raw = f.read(DMDS_HEADER_SIZE)
    else:
        raw = bytes(source[:DMDS_HEADER_SIZE])

    if len(raw) < DMDS_HEADER_SIZE:
        raise ValueError(f"Stream header too short ({len(raw)} < {DMDS_HEADER_SIZE} bytes)")

    magic, version, fps, width, height, total_frames, frame_delay_ms, reserved = struct.unpack(
        DMDS_HEADER_FORMAT, raw
    )
    if magic != DMDS_MAGIC:
        raise ValueError(f"Invalid stream magic {magic!r}, expected {DMDS_MAGIC!r}")

    frame_byte_size = width * height * 2
    return {
        "magic": magic.decode("ascii"),
        "version": version,
        "fps": fps,
        "width": width,
        "height": height,
        "total_frames": total_frames,
        "frame_delay_ms": frame_delay_ms,
        "reserved": reserved,
        "frame_byte_size": frame_byte_size,
        "duration_s": round(total_frames / max(1, fps), 3),
    }


def truncate_rgb565_stream(stream_path: Path | str, max_duration_s: float) -> bytes:
    """
    Zero-reencode dynamic truncation of a `.rgb565.stream` file to `max_duration_s`.

    Slices the frame payload at the exact frame boundary and updates `total_frames`
    in the 16-byte header in O(1).
    """
    stream_path = Path(stream_path)
    meta = read_rgb565_stream_header(stream_path)
    fps = max(1, meta["fps"])
    total_frames = meta["total_frames"]
    frame_byte_size = meta["frame_byte_size"]

    if max_duration_s <= 0:
        keep_frames = total_frames
    else:
        keep_frames = max(1, min(total_frames, int(round(max_duration_s * fps))))

    new_header = struct.pack(
        DMDS_HEADER_FORMAT,
        DMDS_MAGIC,
        meta["version"],
        meta["fps"],
        meta["width"],
        meta["height"],
        keep_frames,
        meta["frame_delay_ms"],
        meta["reserved"],
    )

    payload_bytes_to_read = keep_frames * frame_byte_size
    with open(stream_path, "rb") as f:
        f.seek(DMDS_HEADER_SIZE)
        payload = f.read(payload_bytes_to_read)

    return new_header + payload


def truncate_gif_bytes(gif_path: Path | str, max_duration_s: float) -> bytes:
    """
    Return the GIF file bytes truncated to `max_duration_s` seconds.
    If the GIF is already shorter than or equal to `max_duration_s`, returns the
    original file bytes directly without re-encoding.
    """
    gif_path = Path(gif_path)
    if max_duration_s <= 0:
        return gif_path.read_bytes()

    max_ms = max(100.0, max_duration_s * 1000.0)
    with Image.open(gif_path) as img:
        n_frames = getattr(img, "n_frames", 1)
        total_ms = 0.0
        frames: list[Image.Image] = []
        durations: list[int] = []

        for idx in range(n_frames):
            img.seek(idx)
            dur = int(img.info.get("duration", 66) or 66)
            if total_ms + dur > max_ms and len(frames) >= 1:
                break
            frames.append(img.copy())
            durations.append(dur)
            total_ms += dur

        if len(frames) >= n_frames:
            return gif_path.read_bytes()

        buf = io.BytesIO()
        frames[0].save(
            buf,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
        )
        return buf.getvalue()


def extract_frames_from_gif(gif_path: Path | str) -> Tuple[list[np.ndarray], int]:
    """
    Extract all frames as (H, W, 3) uint8 RGB arrays from an animated GIF,
    along with its effective FPS.
    """
    frames: list[np.ndarray] = []
    durations_ms: list[int] = []

    with Image.open(gif_path) as img:
        n_frames = getattr(img, "n_frames", 1)
        for idx in range(n_frames):
            img.seek(idx)
            durations_ms.append(int(img.info.get("duration", 66) or 66))
            rgb = img.convert("RGB")
            frames.append(np.asarray(rgb, dtype=np.uint8))

    avg_delay = float(np.mean(durations_ms)) if durations_ms else 66.6
    fps = max(1, min(60, int(round(1000.0 / max(10.0, avg_delay)))))
    return frames, fps


class DmdMediaProcessor:
    """
    Stateless headless facade for converting trailers, video snaps, posters,
    and backdrops into DMD LED matrix formats (.gif, .png, .rgb565, .rgb565.stream).
    """

    def select_best_clip_window(
        self,
        input_video: Path | str,
        config: DmdClipConfig = DmdClipConfig(),
    ) -> Tuple[float, float]:
        """
        Determine the optimal `[start_s, end_s]` window of at most `config.max_duration_s`
        from a source video or trailer, skipping studio intro/outro padding and using
        `AiMomentsEngine` when enabled.
        """
        input_video_str = str(input_video)
        w, h, fps_src, duration_full = get_metadata(input_video_str)
        if not duration_full or duration_full <= 0:
            return 0.0, max(1.0, config.max_duration_s)

        target_len = max(1.0, float(config.max_duration_s))
        if duration_full <= target_len * 1.15:
            return 0.0, round(min(duration_full, target_len), 2)

        skip_start = max(0.0, min(duration_full * 0.35, duration_full * config.skip_intro_pct))
        skip_end = max(0.0, min(duration_full * 0.35, duration_full * config.skip_outro_pct))
        usable_start = skip_start
        usable_end = max(usable_start + target_len, duration_full - skip_end)
        usable_end = min(duration_full, usable_end)

        if config.use_ai_moments and (usable_end - usable_start) >= target_len * 1.35:
            try:
                from src.plugins.scorers.ai_moments import AiMomentsEngine

                options = {
                    "analyze_fps": 3.0,
                    "dur_min": max(2.0, min(target_len * 0.85, target_len)),
                    "dur_max": target_len,
                    "count": 5,
                    "w_action": 80.0,
                    "w_character": 50.0,
                    "w_epic": 90.0,
                    "w_emotion": 60.0,
                    "w_dmd": 100.0,
                }
                engine = AiMomentsEngine(
                    input_video_str,
                    options=options,
                    progress_cb=lambda _stage, _pct: None,
                )
                moments = engine.run()
                valid = [
                    m
                    for m in moments
                    if m.start_time >= usable_start * 0.8 and m.end_time <= usable_end * 1.05
                ]
                candidates = valid if valid else moments
                if candidates:
                    best = max(candidates, key=lambda m: m.overall_score)
                    start_s = max(0.0, min(float(best.start_time), max(0.0, duration_full - target_len)))
                    end_s = min(duration_full, start_s + target_len)
                    if end_s - start_s >= min(2.0, target_len):
                        return round(start_s, 2), round(end_s, 2)
            except Exception as exc:
                logger.warning("AiMomentsEngine fallback to heuristic center window: %s", exc)

        # Heuristic center-action window (around 35%-45% of the usable trailer)
        usable_span = max(0.0, usable_end - usable_start - target_len)
        start_s = max(0.0, min(usable_start + usable_span * 0.38, max(0.0, duration_full - target_len)))
        end_s = min(duration_full, start_s + target_len)
        return round(start_s, 2), round(end_s, 2)

    def process_video_trailer(
        self,
        input_video: Path | str,
        output_dir: Path | str,
        config: DmdClipConfig = DmdClipConfig(),
        export_gif: bool = True,
        export_rgb565_stream: bool = True,
        stem: Optional[str] = None,
        callback: Optional[Callable[[str, str], None]] = None,
    ) -> DmdProcessedAssets:
        """
        Convert a video or trailer into DMD-ready `.gif` and/or `.rgb565.stream` assets.
        """
        input_path = Path(input_video)
        if not input_path.exists():
            raise FileNotFoundError(f"Input video not found: {input_path}")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        base_stem = stem or f"{input_path.stem}_{config.width}x{config.height}"

        start_s, end_s = self.select_best_clip_window(input_path, config)

        gif_out_path = out_dir / f"{base_stem}.gif"
        stream_out_path = out_dir / f"{base_stem}.rgb565.stream"

        params = {
            **DEFAULT_PARAMS,
            **(LET_ME_HANDLE_PARAMS if config.use_auto_action else {}),
            "target_width": config.width,
            "target_height": config.height,
            "mode": config.mode,
            "fps_min": config.fps,
            "fps_max": config.fps,
            "max_duration": config.max_duration_s,
            "scroll_enabled": False if config.use_auto_action else config.scroll_enabled,
            "scroll_direction": config.scroll_direction,
            "force_panorama_scroll": bool(not config.use_auto_action and config.scroll_enabled),
            "let_me_handle_it": config.use_auto_action,
            "auto_action_enabled": config.use_auto_action,
            "action_smart_auto_crop": config.use_auto_action,
            "action_auto_detector_fallback": True,
            "auto_color_enabled": config.use_smart_color_boost,
            "brightness": config.brightness,
            "contrast": config.contrast,
            "saturation": config.saturation,
            "gamma": config.gamma,
            "dither": config.dither,
        }

        ok, msg = process_file(
            src_path=str(input_path),
            out_path=str(gif_out_path),
            params=params,
            start_s=start_s,
            end_s=end_s,
            callback=callback,
        )
        if not ok or not gif_out_path.exists():
            raise RuntimeError(f"DMD video conversion failed for {input_path.name}: {msg}")

        eval_res = evaluate_gif_quality(str(gif_out_path))
        quality_score = int(eval_res.get("score", 75))

        frames_rgb, effective_fps = extract_frames_from_gif(gif_out_path)
        frame_count = len(frames_rgb)
        duration_s = round(frame_count / max(1, effective_fps), 2)

        final_stream_path: Optional[Path] = None
        if export_rgb565_stream and frames_rgb:
            write_rgb565_stream(frames_rgb, stream_out_path, fps=effective_fps)
            final_stream_path = stream_out_path

        final_gif_path: Optional[Path] = gif_out_path if export_gif else None
        if not export_gif and gif_out_path.exists():
            gif_out_path.unlink(missing_ok=True)

        return DmdProcessedAssets(
            gif_path=final_gif_path,
            rgb565_stream_path=final_stream_path,
            frame_count=frame_count,
            fps=effective_fps,
            width=config.width,
            height=config.height,
            duration_s=duration_s,
            quality_score=quality_score,
            selected_start_s=start_s,
            selected_end_s=end_s,
        )

    def _enhance_for_led(self, img: Image.Image, smart_color_boost: bool) -> Image.Image:
        rgb = img.convert("RGB")
        if not smart_color_boost:
            return rgb
        rgb = ImageEnhance.Contrast(rgb).enhance(1.22)
        rgb = ImageEnhance.Color(rgb).enhance(1.30)
        rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
        return rgb

    def process_poster(
        self,
        input_image: Path | str,
        output_dir: Path | str,
        width: int = 32,
        height: int = 32,
        smart_color_boost: bool = True,
        stem: str = "poster",
    ) -> Tuple[Path, Path]:
        """
        Resize and center-crop a poster/boxart image to `(width, height)` (default 32x32)
        and write both `.png` and raw `.rgb565` (little-endian) files.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        with Image.open(input_image) as img:
            fitted = ImageOps.fit(
                img.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.35),
            )
            enhanced = self._enhance_for_led(fitted, smart_color_boost)

        png_path = out_dir / f"{stem}_{width}x{height}.png"
        rgb565_path = out_dir / f"{stem}_{width}x{height}.rgb565"

        enhanced.save(png_path, format="PNG", optimize=True)
        arr = np.asarray(enhanced, dtype=np.uint8)
        rgb565_path.write_bytes(rgb888_to_rgb565_le(arr))
        return png_path, rgb565_path

    def process_pan_backdrop(
        self,
        input_image: Path | str,
        output_dir: Path | str,
        width: int = 128,
        height: int = 72,
        smart_color_boost: bool = True,
        stem: str = "snap",
    ) -> Tuple[Path, Path]:
        """
        Resize a snapshot or movie backdrop to `(width, height)` (default 128x72 for smooth
        vertical Ken Burns panning on a 128x32 matrix) and write both `.png` and `.rgb565`.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        with Image.open(input_image) as img:
            fitted = ImageOps.fit(
                img.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            enhanced = self._enhance_for_led(fitted, smart_color_boost)

        png_path = out_dir / f"{stem}_{width}x{height}.png"
        rgb565_path = out_dir / f"{stem}_{width}x{height}.rgb565"

        enhanced.save(png_path, format="PNG", optimize=True)
        arr = np.asarray(enhanced, dtype=np.uint8)
        rgb565_path.write_bytes(rgb888_to_rgb565_le(arr))
        return png_path, rgb565_path

    def process_image_panorama(
        self,
        input_image: Path | str | Image.Image,
        output_dir: Path | str,
        width: int = 128,
        height: int = 32,
        duration_s: float = 4.0,
        fps: int = 20,
        hold_start_s: float = 0.35,
        hold_end_s: float = 0.35,
        smart_color_boost: bool = True,
        mode: str = "pixel_art",
        scroll_cycles: float = 0.999,
        bottom_crop_pct: float = 0.0,
        top_crop_pct: float = 0.0,
        scroll_direction: str = "auto",
        export_gif: bool = True,
        export_rgb565_stream: bool = True,
        stem: str = "pan",
        callback: Optional[Callable[[str, str], None]] = None,
    ) -> DmdProcessedAssets:
        """
        Convert a static image (Jacket/Poster, Marquee/Banner, or Snapshot/Backdrop)
        into an aspect-ratio-preserving, zero-black-bar scrolling panorama `.gif` and
        `.rgb565.stream` (`DMDS`) using `process_file`:
        - TATE panels (`height > width`) always pan left-to-right, centering vertically if zoomed.
        - YOKO panels (`width > height`) always pan top-to-bottom, centering horizontally if zoomed.
        - Square panels (`width == height`) pan left-to-right when `src_w > src_h` and top-to-bottom otherwise.
        """
        _ = (hold_start_s, hold_end_s)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        width = max(16, int(width))
        height = max(16, int(height))
        fps_clamped = max(10, min(25, int(fps)))
        duration_clamped = max(1.5, float(duration_s))

        temp_src_path: Optional[Path] = None
        if isinstance(input_image, Image.Image):
            temp_src_path = out_dir / f"_tmp_src_{stem}_{width}x{height}.png"
            if input_image.mode in ("RGBA", "LA") or "transparency" in input_image.info:
                rgba = input_image.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
                bg.alpha_composite(rgba)
                bg.convert("RGB").save(temp_src_path, format="PNG")
            else:
                input_image.convert("RGB").save(temp_src_path, format="PNG")
            src_path = temp_src_path
        else:
            src_path = Path(input_image)
            if not src_path.exists():
                raise FileNotFoundError(f"Input image not found: {src_path}")

        gif_out_path = out_dir / f"{stem}_{width}x{height}.gif"
        stream_out_path = out_dir / f"{stem}_{width}x{height}.rgb565.stream"

        params = {
            **DEFAULT_PARAMS,
            "target_width": width,
            "target_height": height,
            "mode": mode,
            "fps_min": float(fps_clamped),
            "fps_max": float(fps_clamped),
            "scroll_enabled": True,
            "scroll_direction": str(scroll_direction or "auto"),
            "force_panorama_scroll": True,
            "scroll_cycles": float(scroll_cycles),
            "scroll_duration": duration_clamped,
            "bottom_crop_pct": float(bottom_crop_pct),
            "top_crop_pct": float(top_crop_pct),
            "auto_action_enabled": False,
            "auto_color_enabled": bool(smart_color_boost),
        }

        try:
            ok, msg = process_file(
                src_path=str(src_path),
                out_path=str(gif_out_path),
                params=params,
                callback=callback,
            )
        finally:
            if temp_src_path is not None:
                temp_src_path.unlink(missing_ok=True)

        if not ok or not gif_out_path.exists():
            raise RuntimeError(f"DMD image panorama conversion failed for {stem}: {msg}")

        eval_res = evaluate_gif_quality(str(gif_out_path))
        quality_score = int(eval_res.get("score", 75))

        frames_rgb, effective_fps = extract_frames_from_gif(gif_out_path)
        frame_count = len(frames_rgb)
        actual_duration_s = round(frame_count / max(1, effective_fps), 2)

        final_stream_path: Optional[Path] = None
        if export_rgb565_stream and frames_rgb:
            write_rgb565_stream(frames_rgb, stream_out_path, fps=effective_fps)
            final_stream_path = stream_out_path

        final_gif_path: Optional[Path] = gif_out_path if export_gif else None
        if not export_gif and gif_out_path.exists():
            gif_out_path.unlink(missing_ok=True)

        return DmdProcessedAssets(
            gif_path=final_gif_path,
            rgb565_stream_path=final_stream_path,
            frame_count=frame_count,
            fps=effective_fps,
            width=width,
            height=height,
            duration_s=actual_duration_s,
            quality_score=quality_score,
            selected_start_s=0.0,
            selected_end_s=actual_duration_s,
        )
