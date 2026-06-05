# Auto Action Framing

This feature runs **before** the regular ffmpeg conversion pipeline.
It creates an intermediate video that follows action/person areas at the target aspect ratio, then the normal DMD conversion runs on it.

**v3.3.0 improvements:**
- **GIF pre-conversion**: GIF sources are now transcoded to a clean H.264 MP4 via FFmpeg before OpenCV processing — eliminates `FFmpeg pipe encoding failed` errors caused by BGRA transparency palettes in GIF files.
- **BGRA safety net**: OpenCV frames are normalised to BGR (3-channel) before being piped to FFmpeg, even if the GIF pre-conversion fallback path is taken.
- **FFmpeg stderr capture**: In case of encoding failure, the last 300 characters of FFmpeg's stderr are included in the log for easier diagnosis.
- **Smart Auto Crop 3-group logic**: The decision engine now uses three **mutually exclusive groups** instead of evaluating all signals simultaneously — resolving the face-priority ↔ floor-tracking architectural contradiction.
- **Face Priority improvements**: Detection zone is now at **chin level** (20 % of body height from head top, not 32 % shoulder level). Camera uses **full frame bounds** in face-priority mode, not the restricted detection zone, preventing the camera from being locked at shoulder level.

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

## Intermediate Encoding — rawvideo pipe + GIF pre-conversion

### GIF sources — automatic pre-conversion *(new in v3.3.0)*

GIF files are pre-converted to a clean H.264 MP4 via FFmpeg **before** OpenCV processes them:

```
GIF source  ──[FFmpeg GIF→MP4]──▶  clean BGR24 MP4  ──[OpenCV]──▶  rawvideo pipe  ──▶  H.264 temp.mp4
```

This solves a class of failures specific to GIF files on macOS/AVFoundation:
- GIF transparency palettes decode as **BGRA (4-channel)** in OpenCV — mismatching the `bgr24` pipe format
- Sub-frame delta GIFs produce garbled frames after the first one
- FPS metadata in GIF files may be wrong — FFmpeg decodes timing correctly

If FFmpeg is unavailable or the conversion fails, the original GIF is used with BGRA→BGR normalisation as a safety net.

### Standard sources — rawvideo pipe

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

When enabled, the engine scans **60 evenly-spaced frames** and classifies the content into one of **three mutually exclusive groups**:

#### GROUP 1 — Face Priority (tall character)

**Trigger:** `median(roi_h) > 80 % of DMD window height`

The character body is taller than the DMD strip. The camera must zoom onto the face.

| Action | Reason |
|--------|--------|
| `auto_top_crop = ON` (forced) | Restricts YOLO detection zone to the head region only |
| `auto_bottom_crop = ON` | Marks content bottom at chin level (20 % of body height from top) |
| `auto_floor_track = OFF` | **Explicitly suppressed** — tracking the floor while face-priority is active would pan the camera down to feet |

> **Camera bounds fix (v3.3.0):** in face-priority mode the camera is allowed to travel over the **full source frame height** (not the restricted detection zone). This prevents the camera from being forced to shoulder level when the effective zone is smaller than the DMD window.

#### GROUP 2 — Floor Tracking (platformer / ground level)

**Trigger:** `median(roi_bottom) > 50 % of frame_h` AND `floor_variance ≤ 25 %` AND NOT GROUP 1

The floor is visible, stable, and the character fits on screen.

| Action | Reason |
|--------|--------|
| `auto_floor_track = ON` | Asymmetric EMA anchors camera to ground — resists jumps, follows landings |
| `auto_top_crop` skipped | No top-crop needed when character fits and floor is the reference |
| `auto_bottom_crop` | Optional — only if there is significant clutter below the floor line |

#### GROUP 3 — Normal (default)

**Trigger:** all other content

| Action | Reason |
|--------|--------|
| `auto_top_crop` | Activated only when `top_space > 8 %` of frame_h (blank sky / ceiling above) |
| `auto_bottom_crop` | Activated when `bottom_gap > 8 %` of frame_h, **or forced ON** whenever `auto_top_crop` is active (the two work together to centre the subject) |
| `auto_floor_track = OFF` | Not applicable for general content |

#### Why mutually exclusive groups?

The old approach evaluated all signals simultaneously — leading to contradictions like enabling floor-tracking AND face-priority at the same time. A floor-tracking camera follows feet; a face-priority camera must follow the head. Enabling both produced chaotic results.

The three-group architecture ensures only one coherent strategy is activated per source.

#### Decision examples

| Content | Group | Activated options |
|---------|-------|-------------------|
| Very tall character (full-screen sprite) | **GROUP 1** | `auto_top_crop` + `auto_bottom_crop` (face) |
| 2D platformer (normal char, stable floor) | **GROUP 2** | `auto_floor_track` + optional `auto_bottom_crop` |
| 2D platformer + tall boss | **GROUP 1** | `auto_top_crop` + `auto_bottom_crop` (face) |
| Aerial / sky battle, no floor | **GROUP 3** | `auto_top_crop` + `auto_bottom_crop` |
| Well-framed close-up | **GROUP 3** | none (manual) |

#### When Smart Auto is ON

- The 3 individual auto-checkboxes are **disabled** in the UI (managed by the engine at render time)
- The 3 sliders remain **editable** — they serve as manual fallback values if the engine decides NOT to activate a mode for that dimension
- Decision reasons appear in the conversion log: `[smart: face-priority → auto-top+bottom / floor-tracking suppressed]`

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

#### 👤 Face Priority mode (automatic) — v3.3.0 improvements

When the detected character is **taller than the DMD window** (body height > 80 % of `frame_width / target_ratio`), the system automatically switches to **Face Priority** mode:

- The effective "content bottom" is set to **the estimated chin region** — top **20 %** of the body ROI height from the head (≈ chin level, **not shoulder level** which was the old 32 % value)
- Padding is **asymmetric**: `+10 % forehead headroom` above + `+3 % chin buffer` below — so the face is centred with natural breathing room and the detection zone doesn't extend to the shoulders
- **Camera travel uses full frame bounds**: In face-priority mode, `_cam_frame_h = frame_h` and `_cam_frame_top = 0.0` (independent of the restricted YOLO detection zone). This prevents the camera from being mathematically forced to shoulder level when `_cy_min > _cy_max`.
- YOLO still detects in the restricted zone (head ROI only) — the camera is free to follow that small ROI across the full frame height
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
- Smart Auto Crop scans **60 evenly-spaced frames** (handles sources with long intros before the character appears).
- Individual Auto Crop (bottom / top) scans **80 evenly-spaced frames** for the margin calculation pass.
- **GIF sources** are automatically pre-converted to a clean MP4 via FFmpeg before OpenCV processing — no manual intervention needed.
