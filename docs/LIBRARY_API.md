# 📦 Headless Python Library & Binary Stream Reference (`v8.0.7`)

`dmd_gif_converter` is packaged as a standard **PEP 621 Python library** (`dmd-gif-converter`, `dmd_gif_converter.__version__ == "8.0.7"`) with strict separation between its **Headless Core Engine** (zero X11 / Tkinter dependency, ready for Docker and server backends) and its optional **Desktop GUI (`[ui]`)**.

---

## 1. Installation

### Headless Server / Docker Installation (No GUI Dependencies)
```bash
# Install the latest stable release automatically via the floating 'latest' Git tag:
pip install "git+https://github.com/red77290/dmd_gif_converter.git@latest"
# Or pin a specific release tag from the GitHub Releases tab:
pip install "git+https://github.com/red77290/dmd_gif_converter.git@<release-tag>"
# Or install directly from a local checkout:
pip install .
```

### Desktop GUI Installation (`CustomTkinter` + GIF Search)
```bash
pip install ".[ui]"
```

### Developer & Test Suite Installation
```bash
pip install -e ".[ui,dev]"
```

---

## 2. Quickstart — `DmdMediaProcessor`

The high-level stateless facade `DmdMediaProcessor` converts video trailers, gameplay snaps, posters, and scene backdrops into LED-matrix-optimized formats (`.gif`, `.png`, raw `.rgb565`, and `.rgb565.stream`):

```python
from pathlib import Path
from dmd_gif_converter import (
    DmdClipConfig,
    DmdMediaProcessor,
    resolve_panorama_scroll_axis,
    truncate_rgb565_stream,
    __version__,
)

processor = DmdMediaProcessor()

# 1. Convert a video trailer or gameplay clip (AI Moments + Auto-Action + Smart Color Boost)
config = DmdClipConfig(
    width=128,
    height=32,
    fps=15,
    max_duration_s=8.0,          # Extract the best 8-second window
    skip_intro_pct=0.12,         # Skip studio intro logos
    skip_outro_pct=0.15,         # Skip end credits
    mode="cinema",               # "pixel_art" | "anime" | "cinema" | "custom"
    use_ai_moments=True,         # Score & pick the most iconic segment
    use_auto_action=True,        # YOLOv8 / motion framing for 128x32
    use_smart_color_boost=True,  # Automatic LED HUB75 contrast/saturation compensation
)

assets = processor.process_video_trailer(
    input_video=Path("trailer.mp4"),
    output_dir=Path("/tmp/dmd_out"),
    config=config,
    export_gif=True,
    export_rgb565_stream=True,
    stem="blade_runner_1982",
)

print(f"GIF: {assets.gif_path} | Stream: {assets.rgb565_stream_path}")
print(f"Frames: {assets.frame_count} @ {assets.fps} FPS | Quality: {assets.quality_score}%")

# 2. Resize & boost a Poster / Boxart (32x32 PNG + 2 KB raw RGB565 LE)
poster_png, poster_rgb565 = processor.process_poster(
    input_image=Path("poster.jpg"),
    output_dir=Path("/tmp/dmd_out"),
    width=32,
    height=32,
    stem="poster",
)

# 3. Resize & boost a Scene Backdrop for vertical Ken Burns panning (128x72 PNG + 18 KB RGB565 LE)
snap_png, snap_rgb565 = processor.process_pan_backdrop(
    input_image=Path("backdrop.jpg"),
    output_dir=Path("/tmp/dmd_out"),
    width=128,
    height=72,
    stem="snap",
)

# 4. Generate a zero-black-bar scrolling panorama (.gif + .rgb565.stream) for YOKO or TATE panels
axis = resolve_panorama_scroll_axis(src_w=1920, src_h=1080, target_width=64, target_height=128)
assert axis == "horizontal"  # TATE panels (H > W) always pan left-to-right

pan_assets = processor.process_image_panorama(
    input_image=Path("marquee_or_poster.png"),  # RGBA alpha is composited onto pure #000000 black
    output_dir=Path("/tmp/dmd_out"),
    width=64,
    height=128,
    duration_s=5.0,
    fps=20,
    scroll_direction="auto",  # "auto" | "horizontal" | "vertical"
    export_gif=True,
    export_rgb565_stream=True,
    stem="pan_tate",
)
```

### Orientation-Aware Panorama & Framing Guarantees (`v8.0.3`–`v8.0.5`)

- **`resolve_panorama_scroll_axis(src_w, src_h, target_width, target_height, scroll_direction="auto") -> str`**:
  - **TATE (`target_height > target_width`)**: Always returns `"horizontal"` (left-to-right pan), centering vertically when zoomed.
  - **YOKO (`target_width > target_height`)**: Always returns `"vertical"` (top-to-bottom pan), centering horizontally when zoomed.
  - **Square (`target_width == target_height`)**: Returns `"horizontal"` when `src_w > src_h` and `"vertical"` otherwise.
  - Supports explicit overrides (`"horizontal"` / `"left_to_right"` / `"ltr"` / `"x"` and `"vertical"` / `"top_to_bottom"` / `"ttb"` / `"y"`), also configurable on `DmdClipConfig(scroll_enabled=True, scroll_direction="auto")`.
- **Uniform Zoom-to-Cover**: Preserves 1:1 pixel aspect ratio via Lanczos resampling with zero black bars and guaranteed non-static travel in panorama mode; RGBA/palette transparency is composited onto pure black before encoding.
- **Auto-Action Framing (`use_auto_action=True`)**: Ships with stance-aware bidirectional 2D platformer floor tracking (`platformer_floor_ratio=0.90`, ~3 px ground strip on 32 px DMDs, headroom/footroom visibility envelope) and calibrated eyes-to-mouth close-up framing (`closeup_eye_mouth_fractions`).

---

## 3. Binary `.rgb565.stream` Specification (`DMDS` v1)

In addition to standard `.gif` files, `dmd_gif_converter` can export a zero-overhead binary frame stream (`.rgb565.stream`) designed for direct consumption by Raspberry Pi and ESP32 HUB75 LED matrices and instant server-side duration truncation without re-encoding.

### Header Layout (16 Bytes, Little-Endian `<4sBBHHHHH`)

| Byte Offset | Type | Field | Description |
| :--- | :--- | :--- | :--- |
| `0..3` | `char[4]` | `magic` | ASCII magic bytes `"DMDS"` (`0x44 0x4D 0x44 0x53`) |
| `4` | `uint8` | `version` | Format version (`1`) |
| `5` | `uint8` | `fps` | Playback frame rate in frames/second (e.g. `15`) |
| `6..7` | `uint16_le` | `width` | Frame width in pixels (e.g. `128`) |
| `8..9` | `uint16_le` | `height` | Frame height in pixels (e.g. `32`) |
| `10..11` | `uint16_le` | `total_frames` | Total number of frames in the stream |
| `12..13` | `uint16_le` | `frame_delay_ms` | Target delay per frame in milliseconds (`round(1000 / fps)`) |
| `14..15` | `uint16_le` | `reserved` | Reserved (`0`) |

### Frame Payload (`offset = 16`)
Immediately following the 16-byte header are `total_frames` contiguous raw frames:
- Each frame is exactly `width * height * 2` bytes (`8,192 bytes` for `128×32`) in row-major order, **RGB565 Little-Endian** (`((R & 0xF8) << 8) | ((G & 0xFC) << 3) | (B >> 3)`).

### Dynamic Zero-Reencode Truncation
When a DMD client requests a shorter `video_max_duration_s` (e.g. `4.0s` from an `8.0s` cached stream), call `truncate_rgb565_stream(stream_path, max_duration_s=4.0)` to slice the exact byte range and update `total_frames` in $O(1)$ without running FFmpeg again.
