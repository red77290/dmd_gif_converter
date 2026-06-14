# Advanced Features & Architecture

## 🤖 Auto Action Framing — AI-powered cinematic camera

> **TL;DR — enable it, sit back, and watch the magic.**  
> Hidden in **🔧 Advanced Settings → 🎯 Auto Action Framing** · disabled by default.

This is the most powerful feature of the converter. Instead of a static crop or a simple vertical scroll, the **Auto Action engine** analyses every frame of your source video using **computer vision (OpenCV)** and generates a fully automated, **cinema-quality camera movement** before handing the result to ffmpeg:

```
Source video  ──[AI analysis]──▶  4:1 cinematic crop  ──[ffmpeg]──▶  128×32 DMD GIF
                    ↑
        Person detection (ONNX YOLOv8 nano)
        Motion detection (MOG2 background subtraction)
        Smooth exponential camera
        Intro panoramic establishing shot
        Auto floor tracking (2-D platformers)
```

### What it does automatically

| Phase | What happens |
|---|---|
| **Intro panoramic** | Opens with a wide establishing shot (1.5 s by default) so the viewer understands the scene |
| **AI detection** | Detects persons (HOG/SVM) and/or motion (background subtraction + optical flow) frame by frame |
| **Cinematic framing** | Computes the ideal 4:1 crop window centred on the action with configurable padding |
| **Smooth camera** | Applies exponential smoothing to simulate a real camera operator — no jitter, no jumps |
| **Tail extension** | If the source is too short for the camera to finish its movement, the last frame is extended until the camera settles |

### Why it is disabled by default

Auto Action performs **full CPU-intensive computer vision** on every frame (ONNX YOLOv8 nano person detection, MOG2 background subtraction). This is significantly heavier than a simple ffmpeg pass:

- **CPU usage:** ~2–5× higher than standard conversion
- **Processing time per file:** roughly doubles
- **Memory:** each worker loads the full video as raw frames
- **First run:** downloads the YOLOv8n ONNX model (~6 MB) to `~/.cache/dmd_gif_converter/` — subsequent runs use the cached model

For batch conversion of large libraries, this cost adds up. If you are converting retro sprites or pixel-art GIFs, the standard scroll pipeline is already optimal.  
**For live footage, sports, clips, or any video with a person or moving subject → enable Auto Action and get professional results automatically.**

### How to enable it

1. Open the UI with `./launch_ui.sh`
2. Select a video file
3. Scroll down to the **⚙️ Parameters** panel → click **🔧 Advanced Settings ▼**
4. At the very top of the panel: **🎯 Auto Action Framing**
5. Check **"Enable cinematic auto-framing before ffmpeg"**
6. The **AUTO ACTION** preview canvas (middle) will generate immediately

### Parameters

| Parameter | UI slider | Default | Description |
|---|---|---|---|
| `auto_action_enabled` | Checkbox | `OFF` | Master switch — enable AI framing |
| `action_detector` | Detection mode menu | `person` | `person` · `motion` · `hybrid` · `center` |
| `action_intro` | Intro panoramic | `1.5 s` | Duration of the wide establishing shot prepended before AI tracking |
| `action_strength` | Action strength | `0.65` | `0` = loose framing · `1` = tight zoom on subject |
| `action_auto_strength` | Auto strength | `OFF` | Automatically adapt action strength based on content type (0.55 for anime, 0.65 for games) |
| `action_smoothness` | Camera smooth | `0.65` | `0` = instant · `0.98` = very slow camera |
| `action_auto_smoothness`| Auto smooth | `OFF` | Automatically adapt camera smoothness based on content type (0.85 for anime, 0.70 for games) |
| `action_zoom_max` | Zoom max | `1.8×` | Maximum dynamic zoom the AI camera can apply |
| `action_padding` | ROI padding | `0.20` | Extra space added around the detected subject |
| `action_bottom_crop` | Bottom crop % | `0 %` | Exclude the bottom N % of the frame from detection (manual — overridden when auto is active) |
| `action_auto_bottom_crop` | Auto bottom crop | `OFF` | **Automatically** detect where the subject ends at the bottom (feet / floor). Activates **Face Priority** mode 👤 when the body is taller than the DMD window — crops to the estimated chin region (top ~20 % of body height) with asymmetric padding so the **face is centred, not cut at the shoulders** |
| `action_top_crop` | Top crop % | `0 %` | Exclude the top N % of the frame from detection (manual — overridden when auto is active) |
| `action_auto_top_crop` | Auto top crop | `OFF` | **Automatically** detect where the subject starts at the top (head / sky) — adapts padding to face vs full-body content |
| `action_vertical_bias` | Vertical bias | `0.0` | Manually shift the camera: `+1.0` = as low as possible (floor visible), `-1.0` = as high as possible |
| `action_auto_vertical_bias` | Auto floor detect | `OFF` | **Automatically** tracks the ground level using an asymmetric EMA — resists jumps, follows landings. Overrides the manual vertical bias. Ideal for 2-D platformers. |
| `action_smart_auto_crop` | 🧠 Smart Auto Crop | `OFF` | **Engine analyses 60 frames and activates the optimal camera profile** using a **Continuous Scoring Matrix**. It scores 9 different scene types (e.g., `talking_closeup`, `platformer`, `action_horizontal`) based on metrics like height ratio, X/Y variance, and bounding box properties. The scene with the highest score wins, automatically configuring top/bottom crops, floor tracking, and padding. The UI logs show a `=== Scene Classification Scoreboard ===` detailing exactly how the AI made its decision. |

### Detector modes

| Mode | Best for |
|---|---|
| `person` ★ default | Videos with people — uses ONNX YOLOv8 nano person detector, falls back to motion |
| `motion` | Sports, vehicles, fast action without clear human silhouette |
| `hybrid` | Merges person + motion bounding boxes — broadest coverage |
| `center` | No detection — keeps the camera centred (intro pan only) |

### Auto floor detect — dynamic ground tracking

> **Best for 2-D platformers** and any content where the floor level changes.

When **Auto floor detect** is enabled, the camera uses an **asymmetric exponential moving average (EMA)** to memorise the floor position frame by frame:

| Situation | Behaviour |
|---|---|
| Character **lands** / descends to a lower platform | Floor estimate updates quickly (α = 0.28 — reaches new floor in ~10 frames) |
| Character **jumps** or moves upward | Floor estimate barely moves (α = 0.02 — < 30 px drift over 8 frames of airtime) |
| Subject **off-screen** (no detection) | Camera holds last known floor level — no drift |

This means the camera stays anchored to the ground during jumps and naturally follows the character when they land on a new (lower) platform.

**Priority rules:**
1. `auto_vertical_bias = True` → auto floor tracking active, manual `vertical_bias` ignored
2. `auto_vertical_bias = False` + `vertical_bias ≠ 0` → manual lerp bias applied
3. Both off → camera follows ROI centre (default behaviour)

**CLI flag:**
```bash
python auto_action_cli.py input.mp4 --auto-floor-detect
# manual bias flag is silently ignored when --auto-floor-detect is set
```

### Auto crop top / bottom — automatic subject framing

> Works for any content type: face close-ups, full-body character sprites, 2-D platformers.

#### Auto bottom crop

Samples ~40 evenly-spaced frames and detects where **the subject ends at the bottom** (feet, ground line).
Automatically eliminates HUD bars, floor tiles, and subtitle strips that would drag the camera down.

#### Auto top crop

Detects where **the subject starts at the top** (head, hair tip, weapon).
Eliminates sky, ceiling, or black bars above the character.

#### Content-type adaptation

The median bounding-box aspect ratio infers whether the subject is a **face/close-up** or **full body**, adjusting the margin accordingly:

| Aspect ratio h/w | Subject type | Margin applied |
|-----------------|--------------|----------------|
| < 1.3 | Close-up / face | 15 % of frame height |
| 1.3 – 2.5 | Bust / upper body | 10 % of frame height |
| > 2.5 | Full body | 6 % of frame height |

#### Manual ↔ Auto toggle

Both crops have an **independent checkbox** and a manual slider:

- **Auto ON** → slider grayed out; value computed automatically at render time.
- **Auto OFF** → slider active; you set the crop percentage manually.

The two modes are fully independent — auto bottom + manual top is valid.

**CLI flags:**
```bash
# Auto both boundaries
python auto_action_cli.py input.mp4 --auto-bottom-crop --auto-top-crop

# Manual bottom + auto top
python auto_action_cli.py input.mp4 --bottom-crop 0.10 --auto-top-crop

# Manual both (original behaviour)
python auto_action_cli.py input.mp4 --top-crop 0.05 --bottom-crop 0.15
```

If OpenCV is not installed, the feature is silently skipped and the standard pipeline runs instead — **no crash, no data loss**.

### 🧠 Continuous Scoring Matrix (v6.3.0)

> Replaces the rigid waterfall model to intelligently classify scenes and assign the perfect camera profile.

When **Smart Auto Crop** is enabled, the engine evaluates the first 60 frames of your video against 9 distinct scene profiles (e.g., `talking_closeup`, `platformer`, `action_horizontal`, `tall_character`).

Instead of a simple IF/ELSE decision tree, each frame contributes points to a **Continuous Scoring Matrix** based on:
1. **Aspect Ratio (`h/w`)**: Is the subject tall and thin, or wide and short?
2. **Bounding Box Size (`roi_h`)**: Does the subject fill the whole screen, or is it a small sprite?
3. **Movement Variance (`var_x`, `var_y`)**: Does the subject move rapidly horizontally (like a platformer) or stay relatively still (like a talking head)?
4. **Floor Stability**: Is there a consistent ground level detected by the EMA floor tracker?

The scene profile with the highest total score dictates the final camera behaviour. There are **12 possible scene types** in the system, which you can also manually enforce via the CLI using the `--scene-type` argument:

#### 🎮 Gaming & Action Profiles
- **`platformer`**: For 2D games with a stable floor (e.g. Mario, Sonic). Enables auto-floor tracking to lock the camera to the ground.
- **`top_down_isometric`**: For Zelda, Pokémon, and isometric games. Focuses on horizontal and vertical tracking without floor gravity constraints. Zoom is restricted to preserve context.
- **`first_person`**: For Doom, Minecraft, and centered action. Locks the camera firmly to the center and prevents zooming to avoid cutting out the HUD or weapons.
- **`fighting_2d`**: For 1v1 arcade fighters (e.g. Street Fighter). Uses tighter tracking (strength 0.70) and faster camera movements (smoothness 0.80) to follow rapid back-and-forth dashes.
- **`action_horizontal`**: For side-scrollers or beat 'em ups. Enables auto-vertical bias to keep the floor level consistent while the camera scrolls smoothly left to right.
- **`action_moving`**: For RPGs or games where the subject moves freely in all directions. Uses standard smooth tracking without locking the floor.
- **`wide_shot`**: For scenes with small subjects and lots of background. Uses very loose tracking (strength 0.40) and high smoothness (0.90) to prevent the camera from jittering aggressively.
- **`menu_static`**: For title screens, menus, and highly static scenes. Locks the camera and heavily smooths any micro-movements to keep the screen stable.

#### 👤 People & Dialogue Profiles
- **`talking_closeup`**: For anime, vlogs, or dialogue where the face fills the frame. Enables **Face Priority Mode**. The camera ignores the lower body and rigidly locks onto the eye region (top 45% of the head) so the face doesn't bounce around during speech.
- **`talking_medium`**: For news anchors or waist-up shots. Enables Face Priority Mode, calculating the head as the top 35% of the visible body bounding box.
- **`full_body_tall`**: For standing characters or tall anime sprites. Enables Face Priority Mode, calculating the head as the top 22% of the body bounding box, ensuring the face is centered rather than cutting them off at the shoulders.
- **`full_body_medium`**: Standard generic tracking for full-body subjects without Face Priority. Uses tighter tracking margins.

### 🎥 Dynamic Scene Detection (Per-Shot)

When generating "AI Moments" or processing montages, videos often cut between multiple camera angles (e.g., from a wide shot to a face close-up).

Enable the **Dynamic Scene Detection** checkbox (or `--dynamic-scene` in the CLI) to instruct the tracking engine to re-evaluate the scene profile on the fly. When a camera cut is detected, the engine gathers a few frames of history and automatically switches to the most appropriate Scene Profile for the new shot.

### 🔄 Auto Detector Fallback

When dealing with mixed content, the primary `person` detector might fail on close-ups or non-human subjects. 

Enable the **Auto Detector Fallback** checkbox (or `--action-auto-detector-fallback` in the CLI) to allow the engine to dynamically switch to the `hybrid` detector if no person is found. Combined with Dynamic Scene Detection, this allows the engine to track a person in the first shot, and seamlessly fall back to tracking generic motion and faces in the next shot if the person disappears.

### 🛠️ Manual Override via CLI
If you want to bypass the Continuous Scoring Matrix and explicitly force one of the 9 profiles, you can use the `--scene-type` argument. This disables the AI analysis phase and immediately applies your chosen profile's tracking rules:

```bash
# Force the Platformer profile (locks the camera to the floor)
python3 -m src.engine.conversion.cli gifs_Sonic --scene-type "platformer"

# Force the Face Priority closeup profile
python3 -m src.engine.conversion.cli input.mp4 --scene-type "talking_closeup"
```

---

## 🎨 Smart Color Boost — AI heuristic colorimetry

> **TL;DR — one checkbox, perfect colours on any source, including dark cinema scenes.**  
> Located in the **⚙️ Parameters** panel → **🎨 Content mode → Smart Color Boost** checkbox · disabled by default.

LED matrix panels have very different rendering characteristics compared to screens: diffused light, limited bit depth, and high perceived brightness. Content that looks perfect on a monitor can appear washed-out, too dark, or over-saturated on a 128×32 HUB75 panel.

**Smart Color Boost** solves this automatically. It analyses three representative keyframes from each source video (at 25 %, 50 %, 75 % of duration) and computes the optimal colorimetry profile for that specific piece of content, without any manual intervention.

```
Source video  ──[keyframes × 3]──▶  heuristic analysis  ──▶  optimal params  ──▶  ffmpeg
                                           ↑
                               Luminance (mean grey level)
                               Dynamic range (standard deviation)
                               Colour saturation (HSV S-channel)
                               🌑 Dark scene detection (lum < 80)
```

### What it analyses and adjusts

| Measurement | What is detected | Correction applied |
|---|---|---|
| **Mean luminance** | Under-exposed (dark) · over-exposed (bright) | **Gamma** boost/reduction |
| **Std deviation** | Flat / dull image (low dynamic range) | **Contrast** multiplier |
| **HSV saturation** | Desaturated · near-greyscale content | **Saturation** boost |
| **Dark scene** `lum < 80` | Night / cinema / dungeon | Contrast **capped** to preserve shadows + stronger gamma & brightness lift |

### 🌑 Dark scene detection (v6.x improvement)

For content with mean luminance below 80/255 (dark cinema, night scenes, dungeons), earlier versions applied high contrast that **crushed shadow detail**, making characters invisible on the LED panel. This is now fixed:

| Parameter | Behaviour when `lum < 80` | Effect |
|---|---|---|
| **Gamma** | Up to **1.70** (was capped at 1.40) | Lifts midtones; characters become visible |
| **Brightness** | **+0.04 to +0.07** (was ≈ 0) | Shifts the entire tonal range upward |
| **Contrast** | **Capped at 1.40–1.60** (was uncapped) | Prevents crushing the limited shadow detail |

> **Example** — *Back to the Future II* dark scene (`lum=67 std=51`):  
> - Before: `contrast=1.79 gamma=1.10 bri=+0.004` → characters barely visible  
> - After:  `contrast=1.57 gamma=1.21 bri=+0.036 🌑dark` → characters clearly visible

The log now shows a `🌑dark` tag (or other semantic tags like `[Vivid]`, `[Washed Out]`) when specific content profiles are triggered:
```
[COLOR  ] scene.mkv — auto-color (1 frame) [Dark + Low Contrast]: lum=67 std=51 sat=138 → contrast=1.57 (+−0.03) …
```

### Which modes benefit?

> **Smart Color Boost works the same for ALL content modes** (pixel_art, anime, cinema, custom) because it overrides the preset entirely with mode="custom" once activated.

| Mode | Without Smart Color Boost | With Smart Color Boost |
|---|---|---|
| `pixel_art` | gamma=0.85, contrast=1.60 (fixed) | Adapts to source content |
| `anime` | gamma=0.87, contrast=1.50 (fixed) | Adapts to source content |
| `cinema` | gamma=0.95, contrast=1.35 (fixed) | Adapts to source content |
| `custom` | Manual sliders | **Smart Color Boost takes over** |

**For dark pixel art, dark anime, or dark cinema clips → enable Smart Color Boost.**  
Static presets cannot detect dark scenes; only Smart Color Boost can.

### Compensation examples (updated)

| Source type | lum | std | → contrast | saturation | gamma | notes |
|---|---|---|---|---|---|---|
| Dark cinema scene | 67 | 51 | **1.57** | 2.15 | **1.21** | 🌑dark cap applied |
| Night scene / dungeon | 31 | 22 | **1.40** | 2.45 | **1.65** | 🌑dark cap applied |
| Normal arcade sprite | 116 | 62 | 1.20 | 1.90 | 0.93 | |
| Over-exposed bright | 190 | 20 | 1.60 | 3.46 | **0.60** | |
| High-contrast vivid | 120 | 75 | 1.20 | 1.50 | 0.89 | |
| Near-greyscale / B&W | 129 | 54 | 1.20 | **3.00** ↑↑ | 0.81 | |

### Why it is disabled by default

Smart Color Boost **overrides the manual colorimetry sliders** (contrast, saturation, gamma, brightness) and disables them in the UI to prevent conflicts. Users who prefer to tune their own presets should leave it off.

**Enable it for:**
- Heterogeneous batch libraries with wildly different brightness levels
- Live footage or cinema clips where the source exposure is unknown
- **Dark content (night scenes, dungeons, dark cinema) with any preset**
- Any content that looks wrong with the standard presets

### How to enable it

1. Open the UI with `./launch_ui.sh`
2. In the **⚙️ Parameters** panel → **🎨 Content mode** section
3. Check **"🎨 Smart Color Boost — IA auto-colorimetry"**
4. The manual colorimetry sliders are automatically grayed out
5. Convert — the log will show the computed values:  
   `[COLOR ] lum=XX std=XX → contrast=X.XX saturation=X.XX …` (+ `🌑dark` if dark scene)

### Requirements

Smart Color Boost uses the same **OpenCV + NumPy** that Auto Action requires — no extra dependency. The analysis is fast (<0.5 s per file) and negligible compared to the ffmpeg conversion time.

If OpenCV is unavailable, the feature falls back silently to the standard preset — **no crash, no data loss**.

---

## 🔍 How it works

### Tall sources — smart scroll

```
[cycle 1]  top ──down──▶ bottom ──up──▶ top
[partial]  top ──down──▶ stop_pos ──hold until source ends──▶ (loop)
```

- **`scroll_cycles = 1.5`** (default): 1 full round-trip then descends to centre (50 % of scroll distance), holds there
- **Bottom crop** (`bottom_crop_pct`): bottom 15 % (feet, floor) ignored → shorter scroll distance
- Speed constant in **px/second** regardless of source FPS
- Output FPS snapped to clean GIF values (10, 12.5, 20, 25 fps) — no judder

### Wide sources — static centring

Vertically centred on the 32-pixel panel. Natural source duration preserved (minimum 1 s).

### Transparency elimination

| Layer | Mechanism |
|---|---|
| `color=black` + `overlay` | Source alpha → black — no clock bleed-through |
| `-gifflags -offsetting-transdiff` | Disables GIF delta encoding |
| `-f gif` (explicit) | Forces GIF output format regardless of input extension |

---

## ⚡ Parallel Conversion — multithreading

### Worker IDs in logs

When using **Convert All** with multiple workers, each file's log messages are now prefixed with a `[W{n}]` tag so you can tell which worker produced which output:

```
🚀  Convert 3 file(s) using 2 worker(s)…
[W1] [ACTION ] clip_a.mkv — Auto action OK (303 frames…)
[W2] [ACTION ] clip_b.mkv — Auto action OK (241 frames…)
[W1] [COLOR  ] clip_a.mkv — lum=67 … 🌑dark
[W2] [COLOR  ] clip_b.mkv — lum=146 …
[W1] [OK    ] clip_a.mkv
[W2] [OK    ] clip_b.mkv
[W1] [OK    ] clip_c.mkv   ← W1 picks up the 3rd task
✅  3 conversion(s) done.
```

### Long conversion deadlock fix (v6.x)

A pipe-buffer deadlock was silently causing **Convert All** to appear sequential or to freeze when converting long clips (scroll animations can be 30–120 s of rendered output):

- **Root cause:** ffmpeg writes progress stats to stderr. Without continuous reading, the ~64 KB OS pipe buffer fills up. ffmpeg then blocks trying to write, `poll()` never returns → all parallel workers freeze simultaneously.
- **Fix:** a background drain thread reads stderr in 4 KB chunks throughout the conversion. The polling/cancellation loop is unaffected.

This fix applies to:
- `process_file()` (single file, UI or CLI)
- `process_folder()` (batch folder)
- `FFmpegWriter.close()` (auto-action preprocessing pipe)

### `--workers` tuning

| Machine | Recommended |
|---|---|
| MacBook Pro M-series (10+ cores) | `6`–`8` |
| Desktop SSD, 8+ cores, 16 GB+ | `6`–`8` |
| Desktop SSD, 4 cores, 8 GB | `3`–`4` |
| Laptop or HDD | `2` |

> Workers are CPU-bound on the ffmpeg side (palette generation + dithering). Going beyond 8 workers rarely helps and increases memory pressure.

---

## 📟 Terminal Logs

### UI launcher

The `./launch_ui.sh` (macOS/Linux), `launch_ui.bat` (Windows), and `launch_ui.ps1` (PowerShell) scripts now correctly route Python logging to the terminal. All `[ACTION]`, `[COLOR]`, `[QUALITY]`, `[ERROR]` messages visible in the UI log panel are also printed to the terminal.

```bash
./launch_ui.sh
# Output:
# 10:42:31 [INFO   ] [UI] DMD Converter starting…
# 10:42:35 [INFO   ] src.engine.conversion.core — [ACTION ] clip.mkv — Auto action OK …
# 10:42:36 [INFO   ] src.engine.conversion.core — [COLOR  ] clip.mkv — lum=67 🌑dark …
```

**If logs are missing from your terminal**, make sure you launch via the script (not `python -m src.ui.app` directly):

```bash
# ✅ Correct — logging configured by launcher.py
./launch_ui.sh

# ⚠️  Direct invocation — also works but uses a simpler log format
python -m src.ui.launcher

# ❌ No terminal logs (bypasses logging setup)
python -m src.ui.app
```

### Log level control (UI)

Use the **Filter** dropdown in the log panel footer to control which messages are shown:

| Level | Shows |
|---|---|
| `DEBUG` | Everything including raw ffmpeg output |
| `INFO` | Normal conversion messages (default) |
| `WARNING` | Only warnings and errors |
| `ERROR` | Only errors |

### Log level control (CLI)

```bash
python -m src.engine.conversion.cli input/ --log-level INFO    # verbose
python -m src.engine.conversion.cli input/ --log-level WARNING # quiet (progress bar only)
python -m src.engine.conversion.cli input/ --verbose           # alias for --log-level DEBUG
```
