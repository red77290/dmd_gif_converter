# CLI Manual & Parameters

Want to use the tool without the GUI? Here are the most powerful commands.
*Place the script next to folders named `gifs_*` (e.g. `gifs_Arcade/`)*.

```bash
# 1. Download GIFs and fully auto-convert them!
python3 -m src.engine.conversion.cli --search-keyword "arcade" --let-me-handle-it

# 2. Process specific folders with cinematic AI framing
python3 -m src.engine.conversion.cli gifs_Arcade --auto-action-enabled

# 3. Add a retro pixel-art text overlay to a video
python3 -m src.engine.conversion.cli input.mp4 --text-overlay --text-content "PLAYER 1" --text-color yellow
```

## ⚙️ Parameters

All parameters are available as **sliders/drop-downs in the UI** and as **`--arg` flags on the CLI**.

### Content mode

| Mode | Best for | contrast | saturation | gamma | Sharpening |
|---|---|---|---|---|---|
| `pixel_art` | Retro sprites, arcade, consoles ★ default | `1.60` | `2.20` 🔥 | `0.85` | `1.8` aggressive |
| `anime` | Softer for complex gradients | `1.50` | `1.90` ✨ | `0.87` | `1.3` crisp |
| `cinema` | Live-action films, photography | `1.35` ¹ | `1.30` 🎞️ | `0.95` ¹ | `0.8` gentle |
| `custom` | Manual control | free | free | free | free |

> ¹ **Cinema preset v6.x** — contrast reduced (1.40 → 1.35), gamma raised (0.90 → 0.95), brightness set to 0.00 to avoid crushing dark cinema scenes.  
> For dark content with any preset, enable **Smart Color Boost** which detects luminance and applies stronger corrections automatically.

> **Note:** Static presets produce the same output regardless of scene brightness. For dark scenes (night, cinema, dungeons) with **any** preset, enable **Smart Color Boost** (`--auto-color-enabled`).

### Full parameter reference

| Parameter | CLI flag | Default | Description |
|---|---|---|---|
| `max_workers` | `--workers` | `auto` | Parallel ffmpeg processes (auto scales to cores/2) |
| `scroll_speed` | `--scroll-speed` | `24.0` | Scroll speed (px/s) |
| `bottom_crop_pct` | `--bottom-crop` | `0.15` | Bottom fraction ignored (feet/floor) |
| `scroll_cycles` | `--scroll-cycles` | `1.5` | Cycle count + fractional stop position (see below) |
| `fps_min` | `--fps-min` | `10.0` | Upsample sources below this FPS |
| `fps_max` | `--fps-max` | `25.0` | Hard cap (ESP32 compatibility) |
| `contrast` | `--contrast` | `1.6` | Custom mode — 0.5 to 2.5 |
| `saturation` | `--saturation` | `2.2` | Custom mode — 0.0 to 4.0 |
| `brightness` | `--brightness` | `-0.03` | Custom mode — LED glow compensation |
| `gamma` | `--gamma` | `0.85` | Custom mode — midtone correction |
| `sharpen_lum` | `--sharpen-lum` | `1.8` | Luma sharpening |
| `sharpen_chr` | `--sharpen-chr` | `0.5` | Chroma sharpening |
| `dither` | `--dither` | `none` | Recommended `none` for scrolling content |

### Output & Logs

| Parameter | Flag | Default | Description |
|-----------|------|---------|-------------|
| `log-level` | `--log-level` | `WARNING` | Sets the logging level (DEBUG, INFO, WARNING, ERROR). Default is WARNING (shows progress bar). |
| `verbose` | `--verbose` / `-v` | `False` | Alias for `--log-level DEBUG`. Shows detailed FFMPEG processing logs. |

> **Note:** The `[DYNAMIC]` tags in the logs display real-time camera cuts, profile transitions (e.g., `scene_change_detected`), and framing adjustments from the Auto Action Engine.

### AI Moments Extraction

| Parameter | Flag | Default | Description |
|-----------|------|---------|-------------|
| `ai_moments` | `--ai-moments` | `False` | Extract the best moments from videos AND automatically convert them to GIFs. |
| `ai_moments_only`| `--ai-moments-only`| `False` | Extract the best moments (MP4) but DO NOT convert them to GIFs. |
| `ai_moments_count` | `--ai-moments-count` | `10` | Max number of moments to extract per video. |
| `ai_moments_strategy` | `--ai-moments-strategy` | `Balanced` | Strategy to prioritize (`Action`, `Balanced`, `Character`). |
| `ai_moments_dur_min` | `--ai-moments-dur-min` | `2.0` | Minimum duration of an extracted moment in seconds |
| `ai_moments_dur_max` | `--ai-moments-dur-max` | `5.0` | Maximum duration of an extracted moment in seconds |
| `ai_moments_analyze_fps`| `--ai-moments-analyze-fps` | `5.0` | Analyze video at N frames per second to speed up YOLO |

### A/B Testing Engine (Scoring V2 Validation)

To validate and test the Scoring Engine locally, use the new A/B Testing runner:
```bash
python3 -m src.engine.testing.ab_runner tests/videos/
```
This will run the Auto Action preprocessing pipeline on all videos in the target folder, and output a detailed Markdown report (`report.md`) that compares Scoring V1 vs Scoring V2 side-by-side.

**Advanced parameters** (UI and CLI):

| Parameter | CLI Flag | Default | Description |
|---|---|---|---|
| `prefix` | `--prefix` | `gifs_` | Source folder prefix |
| `no_scroll` | `--no-scroll` | `False` | `True` = disable automatic scroll (enables manual crop) |
| `zoom` | `--zoom` | `1.0` | Scale multiplier before crop (manual mode) |
| `manual_x` | `--manual-x` | `0` | Horizontal crop offset px (manual mode) |
| `manual_y` | `--manual-y` | `0` | Vertical crop offset px (manual mode) |
| `hue_shift` | `--hue-shift` | `0.0` | Hue rotation in degrees |
| `noise_reduction` | `--noise-reduction` | `0.0` | hqdn3d strength |
| `film_grain` | `--film-grain` | `0` | Additive noise amount |
| `vignette` | `--vignette` | `False` | Edge darkening vignette |
| `max_duration` | `--max-duration` | `0.0` | Hard cap on clip length in seconds (`0` = no limit) |
| `auto_color` | `--auto-color` | `False` | 🎨 Smart Color Boost — AI heuristic colorimetry |
| `auto_action` | `--auto-action` | `False` | 🤖 AI cinematic camera — see dedicated section |
| `action_detector` | `--action-detector` | `person` | `person` / `motion` / `hybrid` / `center` |
| `action_auto_detector_fallback` | `--action-auto-detector-fallback` | `False` | Dynamically switch to hybrid if person detects nothing |
| `action_intro` | `--action-intro` | `1.5` | Establishing shot duration in seconds |
| `action_strength` | `--action-strength` | `0.65` | Framing tightness around subject |
| `action_smoothness` | `--action-smoothness`| `0.65` | Camera exponential smoothing factor |
| `action_zoom_max` | `--action-zoom-max` | `2.0` | Maximum dynamic zoom factor |
| `action_padding` | `--action-padding` | `0.20` | Padding around detected ROI |
| `action_subsample_frames` | `--action-subsample-frames` | `3` | Speed optimization. Skips YOLO inference on N frames. |
| `bg_sub_enable` | `--bg-sub-enable` | `False` | Replace background with black (maximises subject contrast) |
| `action_bottom_crop` | `--action-bottom-crop`| `0.0` | Exclude bottom N % of frame (manual, 0 = disabled) |
| `action_auto_bottom_crop`| `--action-auto-bottom-crop`| `False` | Auto-detect bottom crop from ROI analysis |
| `action_top_crop` | `--action-top-crop` | `0.0` | Exclude top N % of frame (manual, 0 = disabled) |
| `action_auto_top_crop`| `--action-auto-top-crop`| `False` | Auto-detect top crop from ROI analysis |
| `action_vertical_bias`| `--action-vertical-bias`| `0.0` | Manual camera vertical shift (`+1.0` = floor, `-1.0` = ceiling) |
| `action_auto_vertical_bias`| `--action-auto-vertical-bias`| `False` | Auto floor detect — asymmetric EMA ground tracker, overrides vertical bias |
| `action_scene_type` | `--action-scene-type`| `""` | Manually force one of the Continuous Scoring Matrix profiles: `platformer` / `talking_closeup` / `full_body_tall` / `action_horizontal` / `talking_medium` / `full_body_medium` / `wide_shot` / `action_moving`. Overrides auto-detection. |
| `action_auto_scene_type`| `--action-auto-scene-type`| `False` | Auto-detect scene type from content (overrides `--action-scene-type`). |
| `action_smart_auto_crop` | `--smart-auto-crop`| `False` | 🧠 Smart Auto Crop — engine scans 60 frames and activates the optimal camera profile using a continuous scoring matrix of 9 scene types; resolves the face-priority ↔ floor-tracking contradiction automatically |
| `reject_threshold` | `--reject-threshold`| `0` | Automatically move generated GIFs to the trash if their DMD Visibility Score is strictly below N% (0-100). Default: 0 (disabled). |
| `dmd_visibility_score_enabled` | `N/A` | `False` | 🔬 DMD Visibility Score — simulates the proposed crop at target DMD resolution. (Implicitly activated by reject_threshold or let_me_handle_it) |
| `let_me_handle_it` | `--let-me-handle-it`| `False` | 🚀 Let Me Handle It — one-click full-auto mode: activates Smart Color Boost + Auto Action + Smart Auto Crop + Background Subtraction + DMD Visibility Score simultaneously |
| `target_width` | `--target-width` | `128` | Output width in pixels (multi-panel tiling) |
| `target_height` | `--target-height` | `32` | Output height in pixels (multi-panel tiling) |
| `text_overlay_enabled` | `--text-overlay` | `False` | 💬 Burn a text label into the output GIF |
| `text_content` | `--text-content` | `""` | Text string to render |
| `text_font_size` | `--text-font-size` | `8` | Font size in pixels |
| `text_color` | `--text-color` | `white` | Text colour (`white` / `yellow` / `red` / `green` / `blue` / hex) |
| `text_position` | `--text-position` | `bottom_center`| One of 9 anchor positions |
| `text_font_file` | `--text-font-file` | `HelvetiPixel.ttf`| Font file from `media/fonts/` |
| `text_style` | `--text-style` | `outline` | Text rendering style: `none` / `bold` / `outline` / `shadow` |
| `text_bg` | `--text-bg` | `False` | Draw a dark semi-transparent background box behind the text |
| `text_bg_opacity` | `--text-bg-opacity`| `150` | Background box opacity 0-255 |

### `scroll_cycles` explained

The integer part is the number of complete **round-trips** (down→up); the fractional part × `scroll_dist` is the **stop position** where the image holds until the source ends:

| Value | Behaviour |
|---|---|
| `0.5` | Go halfway down, hold at centre |
| `1.0` | 1 round-trip, hold at top |
| `1.5` ★ default | 1 round-trip then hold at centre (50%) |
| `1.75` | 1 round-trip then hold at ¾ |
| `2.0` | 2 round-trips, hold at top |

### `--workers` tuning
By default, the converter uses an automatic optimal worker count (`cpu_cores / 2`).

If you have a powerful multi-core CPU and SSD, you can override this limit. Be aware that FFmpeg scales poorly after 8 concurrent instances unless you have exceptional I/O throughput. Going beyond 8 workers rarely helps and increases memory pressure.  
> In UI mode, each parallel worker's log is prefixed with `[W1]`, `[W2]`, etc. for easy isolation in the log panel.

### Terminal logs — launcher vs direct invocation

To get **full Python logging output in your terminal**, always launch via the provided script:

```bash
# ✅ Full logs — uses src.ui.launcher which configures logging.basicConfig
./launch_ui.sh         # macOS / Linux
launch_ui.bat          # Windows (double-click or cmd)
./launch_ui.ps1        # PowerShell

# ⚠️  Also works — simpler format
python -m src.ui.launcher

# ❌ No terminal logs (bypasses logging setup)
python -m src.ui.app
```

For CLI use, control verbosity with:
```bash
--log-level INFO     # all messages
--log-level WARNING  # quiet (progress bar only, default)
--verbose / -v       # alias for --log-level DEBUG (shows raw ffmpeg output)
```

## 📖 Comprehensive Use Case Examples

Here are examples for all the main use cases, showing how to combine or separate the various AI features via the command line.

### 1. Basic Folder Conversion
Scans all folders starting with `gifs_` in the current directory and converts them to DMD GIFs using standard settings.
```bash
python3 -m src.engine.conversion.cli
```

### 2. The "Let Me Handle It" Magic Mode
The ultimate zero-configuration command. It applies AI Colorimetry, Auto Action framing, Background Subtraction, and DMD Visibility Scoring all at once to a specific folder.
```bash
python3 -m src.engine.conversion.cli gifs_MyGameplay --let-me-handle-it --workers 8
```

### 3. Text Overlay (Watermarking / Player Tags)
Burn a yellow "PLAYER 1" tag at the top left of the GIF with an outline for readability.
```bash
python3 -m src.engine.conversion.cli gifs_InputFolder --text-overlay --text-content "PLAYER 1" --text-color "yellow" --text-position "top_left"
```

### 4. Smart Color Boost for Dark Scenes
Convert a dark movie scene (e.g. Batman) ensuring it is visible on LED panels by enabling heuristic auto-colorimetry.
```bash
python3 -m src.engine.conversion.cli gifs_Batman --auto-color
```

### 5. Web Search & Download
Search for "arcade fighting" on DuckDuckGo, download the top 5 results, and convert them immediately using the platformer camera profile (which tracks tall sprites perfectly and locks to the ground).

```bash
python3 -m src.engine.conversion.cli --search-keyword "arcade fighting" --search-limit 5 --action-scene-type "platformer"
```

### 6. AI Moments: Pipeline Extraction + Conversion
Take a 10-minute gameplay video, find the 5 best action moments, and immediately convert those 5 moments into 128x32 GIFs.
```bash
python3 -m src.engine.conversion.cli gifs_RawGameplay --ai-moments --ai-moments-count 5 --ai-moments-strategy "Action" --let-me-handle-it
```

### 7. AI Moments: Extraction ONLY
If you just want to use the AI to find the best moments and save them as `.mp4` files *without* generating GIFs yet.
```bash
python3 -m src.engine.conversion.cli gifs_RawGameplay --ai-moments-only --ai-moments-count 10
```

### 8. Manual Camera Forcing
Disable AI scene detection and explicitly force the camera to lock onto the floor (Platformer mode) while converting.
```bash
python3 -m src.engine.conversion.cli gifs_SonicGameplay --auto-action --action-scene-type "platformer"
```

### 9. Trash Bad Conversions Automatically
Run a massive batch conversion but automatically delete any resulting GIF that scores less than 60% on the LED Readability scale.
```bash
python3 -m src.engine.conversion.cli --let-me-handle-it --reject-threshold 60
```

