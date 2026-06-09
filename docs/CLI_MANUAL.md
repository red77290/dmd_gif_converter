# CLI Manual & Parameters

## ⚙️ Parameters

All parameters are available as **sliders/drop-downs in the UI** and as **`--arg` flags on the CLI**.

### Content mode

| Mode | Best for | Saturation | Sharpening |
|---|---|---|---|
| `pixel_art` | Retro sprites, arcade, consoles ★ default | `2.2` 🔥 | `1.8` aggressive |
| `anime` | Softer for complex gradients | `1.9` ✨ | `1.3` crisp |
| `cinema` | Live-action films, photography | `1.3` 🎞️ | `0.8` gentle |
| `custom` | Manual control | free | free |

### Full parameter reference

| Parameter | CLI flag | Default | Description |
|---|---|---|---|
| `max_workers` | `--workers` | `2` | Parallel ffmpeg processes |
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

### AI Moments Extraction

| Parameter | Flag | Default | Description |
|-----------|------|---------|-------------|
| `ai_moments` | `--ai-moments` | `False` | Extract the best moments from videos before converting to GIFs. |
| `ai_moments_count` | `--ai-moments-count` | `10` | Max number of moments to extract per video. |
| `ai_moments_strategy` | `--ai-moments-strategy` | `Balanced` | Strategy to prioritize (`Action`, `Balanced`, `Character`). |
| `ai_moments_dur_min` | `--ai-moments-dur-min` | `2.0` | Minimum duration of an extracted moment in seconds. |
| `ai_moments_dur_max` | `--ai-moments-dur-max` | `5.0` | Maximum duration of an extracted moment in seconds. |

**Advanced parameters** (UI — all default = no change):

| Parameter | Default | Description |
|---|---|---|
| `scroll_enabled` | `True` | `False` = manual crop mode |
| `zoom` | `1.0` | Scale multiplier before crop (manual mode) |
| `manual_x` | `0` | Horizontal crop offset px (manual mode) |
| `manual_y` | `0` | Vertical crop offset px (manual mode) |
| `hue_shift` | `0.0` | Hue rotation in degrees |
| `noise_reduction` | `0.0` | hqdn3d strength |
| `film_grain` | `0` | Additive noise amount |
| `vignette` | `False` | Edge darkening vignette |
| `max_duration` | `0.0` | Hard cap on clip length in seconds (`0` = no limit) |
| `auto_color_enabled` | `False` | 🎨 Smart Color Boost — AI heuristic colorimetry |
| `auto_action_enabled` | `False` | 🤖 AI cinematic camera — see dedicated section |
| `action_detector` | `person` | `person` / `motion` / `hybrid` / `center` |
| `action_intro` | `1.5` | Establishing shot duration in seconds |
| `action_strength` | `0.65` | Framing tightness around subject |
| `action_auto_strength` | `False` | Auto strength based on content type |
| `action_smoothness` | `0.65` | Camera exponential smoothing factor |
| `action_auto_smoothness`| `False` | Auto smooth based on content type |
| `action_zoom_max` | `1.8` | Maximum AI zoom factor |
| `action_padding` | `0.20` | Padding around detected ROI |
| `bg_sub_enable` | `False` | Replace background with black (maximises subject contrast) |
| `action_bottom_crop` | `0.0` | Exclude bottom N % of frame (manual, 0 = disabled) |
| `action_auto_bottom_crop` | `False` | Auto-detect bottom crop from ROI analysis |
| `action_top_crop` | `0.0` | Exclude top N % of frame (manual, 0 = disabled) |
| `action_auto_top_crop` | `False` | Auto-detect top crop from ROI analysis |
| `action_vertical_bias` | `0.0` | Manual camera vertical shift (`+1.0` = floor, `-1.0` = ceiling) |
| `action_auto_vertical_bias` | `False` | Auto floor detect — asymmetric EMA ground tracker, overrides vertical bias |
| `action_smart_auto_crop` | `False` | 🧠 Smart Auto Crop — engine scans 60 frames and activates the optimal combination of the 3 options above using 3 mutually exclusive groups; resolves the face-priority ↔ floor-tracking contradiction automatically |
| `dmd_visibility_score_enabled` | `False` | 🔬 DMD Visibility Score — simulates the proposed crop at target DMD resolution and computes a composite score (contrast, edges, pixel occupation). Cancels any zoom that scores < 95 % of the current view. Prevents zooms that make the subject invisible on low-res LED matrices. CPU cost: < 1 ms/frame. |
| `let_me_handle_it` | `False` | 🚀 Let Me Handle It — one-click full-auto mode: activates Smart Color Boost + Auto Action + Smart Auto Crop + Background Subtraction + DMD Visibility Score simultaneously and grays out all unrelated settings |
| `target_width` | `128` | Output width in pixels (multi-panel tiling) |
| `target_height` | `32` | Output height in pixels (multi-panel tiling) |
| `text_overlay_enabled` | `False` | 💬 Burn a text label into the output GIF |
| `text_content` | `""` | Text string to render |
| `text_font_size` | `8` | Font size in pixels |
| `text_color` | `white` | Text colour (`white` / `yellow` / `red` / `green` / `blue` / hex) |
| `text_position` | `bottom_center` | One of 9 anchor positions |
| `text_font_file` | `HelvetiPixel.ttf` | Font file from `media/fonts/` |

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

| Machine | Recommended |
|---|---|
| MacBook Pro M3 Pro (11 cores, 36 GB) | `8` |
| Desktop SSD, 8+ cores, 16 GB+ | `6`–`8` |
| Desktop SSD, 4 cores, 8 GB | `3`–`4` |
| Laptop or HDD | `2` |
