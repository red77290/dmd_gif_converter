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
| `action_smart_auto_crop` | 🧠 Smart Auto Crop | `OFF` | **Engine analyses 60 frames and activates the optimal combination** of auto-bottom-crop, auto-top-crop and auto-floor-tracking using 3 mutually exclusive groups. GROUP 1 (tall character > 80 % of DMD window) → face priority (top+bottom crop, no floor). GROUP 2 (trackable stable floor) → floor tracking + optional bottom. GROUP 3 (normal) → top+bottom together. Resolves the face-priority ↔ floor-tracking contradiction automatically. Recommended over manual individual options. |

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

---

## 🎨 Smart Color Boost — AI heuristic colorimetry

> **TL;DR — one checkbox, perfect colours on any source.**  
> Located in the **⚙️ Parameters** panel → **🎨 Content mode → Smart Color Boost** checkbox · disabled by default.

LED matrix panels have very different rendering characteristics compared to screens: diffused light, limited bit depth, and high perceived brightness. Content that looks perfect on a monitor can appear washed-out, too dark, or over-saturated on a 128×32 HUB75 panel.

**Smart Color Boost** solves this automatically. It analyses a representative keyframe from each source video and computes the optimal colorimetry profile for that specific piece of content, without any manual intervention.

```
Source video  ──[keyframe @ 50%]──▶  heuristic analysis  ──▶  optimal params  ──▶  ffmpeg
                                           ↑
                               Luminance (mean grey level)
                               Dynamic range (standard deviation)
                               Colour saturation (HSV S-channel)
```

### What it analyses and adjusts

| Measurement | What is detected | Correction applied |
|---|---|---|
| **Mean luminance** | Under-exposed (dark) · over-exposed (bright) | **Gamma** boost/reduction |
| **Std deviation** | Flat / dull image (low dynamic range) | **Contrast** multiplier |
| **HSV saturation** | Desaturated · near-greyscale content | **Saturation** boost |
| Residual offset | Fine brightness mismatch | **Brightness** fine-tune |

### Compensation examples

| Source type | lum | std | → contrast | saturation | gamma |
|---|---|---|---|---|---|
| Night scene / dungeon | 31 | 22 | **2.50** ↑↑ | 2.45 | **1.40** ↑↑ |
| Foggy / washed-out | 55 | 18 | **2.50** ↑↑ | **3.00** ↑↑ | **1.40** ↑↑ |
| Normal arcade sprite | 116 | 62 | 1.20 | 1.90 | 0.93 |
| Over-exposed bright | 190 | 20 | **2.50** ↑↑ | **3.46** ↑↑ | **0.55** ↓↓ |
| High-contrast vivid | 120 | 75 | 1.20 | 1.50 | 0.89 |
| Near-greyscale / B&W | 129 | 54 | 1.20 | **3.00** ↑↑ | 0.81 |

### Why it is disabled by default

Smart Color Boost **overrides the manual colorimetry sliders** (contrast, saturation, gamma, brightness) and disables them in the UI to prevent conflicts. Users who prefer to tune their own presets, or who use the `pixel_art` / `anime` / `cinema` modes that already ship with carefully hand-tuned values, should leave it off.

**Enable it for:**
- Heterogeneous batch libraries with wildly different brightness levels
- Live footage or cinema clips where the source exposure is unknown
- Any content that looks wrong with the standard presets

### How to enable it

1. Open the UI with `./launch_ui.sh`
2. In the **⚙️ Parameters** panel → **🎨 Content mode** section
3. Check **"🎨 Smart Color Boost — IA auto-colorimetry"**
4. The manual colorimetry sliders are automatically grayed out
5. Convert — the log will show the computed values: `[COLOR ] lum=XX std=XX → contrast=X.XX saturation=X.XX …`

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
