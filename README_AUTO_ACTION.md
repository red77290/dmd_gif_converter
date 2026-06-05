# Auto Action Framing (Experimental)

This feature runs **before** the regular ffmpeg conversion pipeline.
It creates an intermediate video that follows action/person areas at the target aspect ratio, then the normal DMD conversion runs on it.

**v3.2.0 architectural improvements:**
- Person detector upgraded from HOG/SVM to **ONNX YOLOv8 nano** (~6 MB, CPU-only).  Fixes macOS ARM64 crashes and eliminates false positives on animated backgrounds.
- Intermediate encoding now uses a **direct rawvideo pipe to FFmpeg** (H.264 ultrafast). No `cv2.VideoWriter`, no bulky `mp4v` temp file — ~30 % faster and ~5–10× smaller intermediate.

---

## Detection Modes

| Mode | Behaviour |
|------|-----------|
| `person` *(default)* | Prioritise ONNX YOLOv8n person detector, fall back to motion |
| `motion` | Prioritise moving regions (MOG2), fall back to person |
| `hybrid` | Merge person + motion bounding boxes when both detected |
| `center` | Disable detection — static centre framing |

### Person detector — ONNX YOLOv8 nano

The HOG/SVM detector has been replaced with **YOLOv8n** exported to ONNX format and executed via `onnxruntime` (CPUExecutionProvider):

| Property | Value |
|----------|-------|
| Model file | `yolov8n.onnx` (~6 MB) |
| Download | Automatic on first use → `~/.cache/dmd_gif_converter/yolov8n.onnx` |
| Runtime | `onnxruntime` ≥ 1.16 (CPU-only, no GPU required) |
| Input size | 640 × 640 px (letterbox resize, normalised 0–1) |
| Class | COCO class 0 = person |
| Confidence threshold | 0.30 (returns highest-confidence detection) |
| Fallback | If `onnxruntime` is missing or model cannot be downloaded, automatic fallback to MOG2 motion detection |

**Benefits over the old HOG backend:**
- Works on **macOS ARM64** (Apple Silicon) — HOG caused a hard SIGBUS crash via Apple GCD
- **No false positives** from animated backgrounds — deep-learning features vs gradient histograms
- **Faster** per-frame inference thanks to ONNX runtime optimisations
- **Same disk footprint**: ~6 MB model, downloaded once and cached

---

## Intermediate Encoding — rawvideo pipe

Frames processed by OpenCV are piped **directly to FFmpeg via stdin** as BGR24 rawvideo.
FFmpeg encodes them to H.264/MP4 (ultrafast preset) without writing any intermediate raw data to disk:

```
OpenCV → [BGR24 rawvideo pipe] → FFmpeg stdin → H.264 temp.mp4
```

vs. the old approach:

```
OpenCV → cv2.VideoWriter → [mp4v temp.mp4 on disk] → FFmpeg reads it
```

**Benefits:**
- ~30 % faster preprocessing phase
- Intermediate file ~5–10× smaller (H.264 vs mp4v)
- No `cv2.VideoWriter` dependency

---

## Auto Crop Features

Three independent crop / vertical-bias options are grouped under the **📐 Crop & Vertical Bias** section.  Each can be activated manually or left to the **Smart Auto Crop** engine.

### 🧠 Smart Auto Crop — context-aware combination selector

**Replaces the manual trial-and-error of enabling the right combination.**

When enabled, the engine scans **25 evenly-spaced frames** and analyses four signals:

| Signal | How it is detected | Result |
|--------|--------------------|--------|
| **Blank space at top** | `median(roi_top) > 8 % of frame_h` | → `auto_top_crop ✓` |
| **Tall character** | `median(roi_h) > 70 % of DMD window height` | → `auto_bottom_crop ✓` (face priority mode) · **floor-tracking ✗** (contradiction) |
| **Bottom clutter / HUD** | `(frame_h − median(roi_bottom)) > 8 %` | → `auto_bottom_crop ✓` |
| **Stable / dynamic floor** | `median(roi_bottom) > 50 % of frame_h` AND `std < 25 %` | → `auto_vertical_bias ✓` (asymmetric EMA floor tracker) |

#### Contradiction handling — face priority vs floor tracking

The engine automatically resolves the key contradiction:

> **Tall character** = face-priority mode is active → camera must stay on the **head region**.  
> **Floor tracking** = camera follows the **feet / ground** via asymmetric EMA.  
> These are **mutually exclusive** — the engine picks face-priority and **suppresses** floor-tracking.

#### Decision examples

| Content | Activated options |
|---------|-------------------|
| 2D platformer (normal char, HUD at bottom) | `auto_bottom_crop` + `auto_floor_track` |
| Very tall character (full-screen sprite) | `auto_bottom_crop` (face priority) only |
| Aerial shot / floating character | `auto_bottom_crop` (clutter below) |
| Wide shot, subject centered with sky + HUD | `auto_top_crop` + `auto_bottom_crop` + `auto_floor_track` |
| All options unnecessary (well-framed source) | none (all manual) |

#### When Smart Auto is ON

- The 3 individual auto-checkboxes are **disabled** in the UI (managed by the engine at render time)
- The 3 sliders remain **editable** — they serve as manual fallback values if the engine decides NOT to activate a mode for that dimension
- Decision reasons appear in the conversion log: `[smart: top-space 15% -> auto-top-crop / floor@83% var=3% (stable) -> floor-tracking ✓]`

#### When Smart Auto is OFF

- All 3 individual toggles and sliders are fully interactive
- The user activates each option manually as before

---

### Auto Bottom Crop (`auto_bottom_crop`)

Samples the video to find where the subject **ends at the bottom** (feet, floor line).
Crops out everything below — HUD elements, floor tiles, subtitle bars.
Also activates **Face Priority** automatically when the character is too tall for the DMD window.

### Auto Top Crop (`auto_top_crop`)

Samples the video to find where the subject **starts at the top** (head, top of hair, weapon tip).
Crops out sky, ceiling, or empty black bars above the character.

### Content-type adaptation & Face Priority

The algorithm infers whether the subject is a **face/close-up** or **full body** from the median bounding-box aspect ratio, and applies an appropriate padding margin:

| ROI aspect ratio (h/w) | Subject type | Padding applied |
|------------------------|--------------|-----------------|
| < 1.3 | Close-up / face | 15 % of frame height |
| 1.3 – 2.5 | Bust / upper body | 10 % of frame height |
| > 2.5 | Full body (fits on screen) | 6 % of frame height |

#### 👤 Face Priority mode (automatic)

When the detected character is **taller than the DMD window** (body height > 80 % of `frame_width / target_ratio`), the system automatically switches to **Face Priority** mode:

- The effective "content bottom" is set to **the estimated face/head region** (top ~32 % of the body ROI height) instead of the feet
- The padding switches to face-mode (12 % — generous, prevents forehead clipping)
- A `[face priority 👤]` tag appears in the conversion log when this mode activates

### Manual vs Smart Auto vs Individual Auto

| Mode | How to use | Sliders | Auto checkboxes |
|------|-----------|---------|-----------------|
| **Smart Auto Crop ON** | One checkbox at the top — engine decides everything | Active (manual fallback) | Disabled (engine manages) |
| **Individual auto ON** | Toggle each checkbox independently | Disabled (auto takes over) | Active |
| **All manual** | Just use the sliders | Active | Unchecked |

Both crops have an **independent toggle** (checkbox) and a manual slider:

- **Auto ON** → slider disabled; value computed automatically at render time.
- **Auto OFF** → slider active; you set the crop percentage manually.

---

## UI Usage

1. Open `🔧 Advanced Settings`
2. Enable `Auto Action Framing (pre-ffmpeg)`
3. Keep detector at `person` (default) or choose another mode
4. Tune strength / smoothness / zoom max / padding
5. **Crop & Vertical Bias** section — choose one of three modes:
   - **🧠 Smart Auto Crop** ← tick this box and let the engine decide everything (recommended)
   - **Individual auto** ← tick each box separately (`Auto bottom crop`, `Auto top crop`, `Auto floor detect`)
   - **All manual** ← leave all boxes unchecked and drag the sliders directly

---

## CLI Runner

```bash
# Basic usage
python auto_action_cli.py input.mp4 --detector person --out preprocessed.mp4

# Auto crop both top and bottom
python auto_action_cli.py input.mp4 --auto-bottom-crop --auto-top-crop --out preprocessed.mp4

# Manual bottom crop + auto top crop
python auto_action_cli.py input.mp4 --bottom-crop 0.10 --auto-top-crop --out preprocessed.mp4

# Manual top and bottom crop (original behaviour)
python auto_action_cli.py input.mp4 --top-crop 0.05 --bottom-crop 0.15 --out preprocessed.mp4
```

### Full CLI reference

| Flag | Default | Description |
|------|---------|-------------|
| `--detector` | `person` | `person` / `motion` / `hybrid` / `center` |
| `--strength` | `0.65` | Framing tightness 0→1 |
| `--smoothness` | `0.85` | Camera smoothing 0→0.98 |
| `--zoom-max` | `1.8` | Maximum dynamic zoom factor |
| `--padding` | `0.20` | Extra padding around detected ROI |
| `--bottom-crop` | `0.0` | Fraction of frame bottom to exclude (manual) |
| `--auto-bottom-crop` | off | Auto-detect bottom crop from ROI analysis |
| `--top-crop` | `0.0` | Fraction of frame top to exclude (manual) |
| `--auto-top-crop` | off | Auto-detect top crop from ROI analysis |
| `--vertical-bias` | `0.0` | Camera bias: `+1.0` = down, `-1.0` = up |
| `--auto-floor-detect` | off | Dynamic floor tracking (overrides `--vertical-bias`) |
| `--smart-auto-crop` | off | Engine analyses context & picks the optimal crop/tracking combination |
| `--start` | — | Clip start time in seconds |
| `--end` | — | Clip end time in seconds |

---

## Notes

- Requires `opencv-python` and `onnxruntime`. If missing, conversion falls back to the normal pipeline (no crash).
- The YOLOv8n model (~6 MB) is downloaded automatically to `~/.cache/dmd_gif_converter/` on first use. Subsequent runs use the cached model.
- If `onnxruntime` is installed but the model download fails (no internet), the motion detector is used as a silent fallback.
- Default settings keep this feature **disabled** — existing behaviour is unchanged.
- Auto crop performs a quick **pre-scan** (~40 evenly-spaced frames) before the main pass.
