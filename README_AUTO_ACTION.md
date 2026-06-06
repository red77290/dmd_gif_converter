# Auto Action Framing (v5.1.0)

This feature runs **before** the regular ffmpeg conversion pipeline.
It creates an intermediate video that follows action/person areas at the target aspect ratio, then the normal DMD conversion runs on it.

**v5.0.0 engine improvements:**
- **DMD Visibility Score** *(Priority 1)*: Before committing to any zoom, the engine simulates both the current crop and the proposed crop at target DMD resolution and computes a composite visibility score. If the proposed zoom scores less than 95% of the current view the zoom is cancelled — preventing counterproductive crops that make the subject invisible on low-resolution LED matrices.
- **Temporal Scene Memory** *(Priority 2)*: A sliding window (default 3 s) of past ROI detections is kept. When YOLO loses the subject for a few frames the camera continues following the estimated trajectory (weighted average biased toward the most-recent detections) instead of jumping back to centre.
- **Scene Change Detection** *(Priority 3)*: HSV histogram correlation detects hard cuts between frames. On cut: ROI history, floor estimator, and camera smoothing are all reset so stale tracking from the previous scene never bleeds into the new scene.
- **Micro-detection Rejection** *(Priority 4)*: ROIs whose area is below 2% of the source frame area are silently discarded. Prevents zooming onto subjects too small to be visible after resize to DMD resolution.
- **Directional Look-Ahead** *(Priority 5)*: When the detected subject moves consistently in one direction, the camera is offset by 25% of the crop half-width in that direction, giving the subject natural leading space on the DMD strip.
- **Multi-ROI Fusion** *(Priority 6)*: When multiple persons are detected in a frame, their bounding boxes are fused into a single confidence-weighted centroid box. Prevents the camera from snap-locking onto a single high-confidence subject while ignoring the rest of the action.
- **Minimum Useful Size After Resize** *(Priority 7)*: Intercepts and cancels aggressive zooms that would cause the detected subject to shrink below a configured minimum size (e.g. 4 px) in the final DMD output space.
- **Smart Platformer Mode** *(Priority 8)*: Special mode for 2-D side-scrollers. Locks the camera vertically to a steady floor level (using the asymmetric EMA estimator) and widens the horizontal view by 50% to reveal more level ahead.
- **ROI Confidence System** *(Priority 10)*: Replaces hardcoded YOLO thresholds with a configurable minimum. Weak/flickering detections are explicitly rejected, forcing the temporal memory system to rely on smoothed trajectory data instead of twitching.

**v5.0.0 improvements:**
- **GIF pre-conversion**: GIF sources are now transcoded to a clean H.264 MP4 via FFmpeg before OpenCV processing — eliminates `FFmpeg pipe encoding failed` errors caused by BGRA transparency palettes in GIF files.
- **BGRA safety net**: OpenCV frames are normalised to BGR (3-channel) before being piped to FFmpeg, even if the GIF pre-conversion fallback path is taken.
- **FFmpeg stderr capture**: In case of encoding failure, the last 300 characters of FFmpeg's stderr are included in the log for easier diagnosis.
- **Smart Auto Crop 3-group logic**: The decision engine now uses three **mutually exclusive groups** instead of evaluating all signals simultaneously — resolving the face-priority ↔ floor-tracking architectural contradiction.
- **Face Priority improvements**: Detection zone is now at **chin level** (20 % of body height from head top, not 32 % shoulder level). Camera uses **full frame bounds** in face-priority mode, not the restricted detection zone, preventing the camera from being locked at shoulder level.

**v5.0.0 architectural improvements:**
- Person detector upgraded from HOG/SVM to **ONNX YOLOv8 nano** (~6 MB, CPU-only).  Fixes macOS ARM64 crashes and eliminates false positives on animated backgrounds.
- Intermediate encoding now uses a **direct rawvideo pipe to FFmpeg** (H.264 ultrafast). No `cv2.VideoWriter`, no bulky `mp4v` temp file — ~30 % faster and ~5–10× smaller intermediate.

**v5.1.0 architectural improvements:**
- **Full OOP refactoring**: Every class now implements a strict ABC interface (`IDetector`, `ITracker`, `IRenderer`). See [ARCHITECTURE.md](ARCHITECTURE.md) for class diagrams and sequence diagrams.
- **`DetectorFactory`**: The ONNX detector instantiation is now decoupled behind a factory — swap the backend without touching the pipeline.
- **`TrackingEngine` implements `ITracker`**: `last_roi` and `cam_full_view` are now proper `@property` accessors, not raw attributes.
- **`Renderer` implements `IRenderer`**: Crop and render logic is fully encapsulated.
- **`AbstractDetector`**: Intermediate abstract class between `IDetector` and `_FrameDetector` — extend it to add custom backends without subclassing the concrete implementation.

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

### GIF sources — automatic pre-conversion *(new in v5.0.0)*

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

> **Camera bounds fix (v5.0.0):** in face-priority mode the camera is allowed to travel over the **full source frame height** (not the restricted detection zone). This prevents the camera from being forced to shoulder level when the effective zone is smaller than the DMD window.

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

---

## 🔬 DMD Visibility Score *(v5.0.0 — Priority 1)*

### Problem

The framing engine may zoom onto a detected ROI that becomes **invisible after the resize to DMD resolution** (e.g. 128×32). A character that is 300 px on screen becomes 6 px on the LED matrix — indistinguishable from noise.

### Solution

Before committing to a proposed camera position, the engine:

1. **Simulates the current crop** → resizes to `target_width × target_height`.
2. **Simulates the proposed crop** → resizes to `target_width × target_height`.
3. **Scores both** using a composite metric.
4. If `score_proposed < score_current × 0.95` → **cancel the zoom, keep the current position**.

### Visibility score — composite metrics

| Metric | Weight | What it measures |
|--------|--------|-----------------|
| Non-black pixel ratio | 30 % | How much of the DMD frame has any content |
| Mean Sobel gradient (local contrast) | 40 % | Edge sharpness after resize — low = blurry/flat |
| Contour density | 20 % | Number of distinct object boundaries |
| Horizontal + vertical occupation | 10 % | How much of the DMD strip the subject fills |

The **5 % tolerance** (`0.95` threshold) absorbs natural frame-to-frame micro-variations and ensures the guard only fires on meaningful quality drops.

### Enabling

| Interface | How |
|-----------|-----|
| UI | **📐 Crop & Vertical Bias → Enable DMD Visibility Score** checkbox |
| CLI | not yet exposed (use `AutoActionConfig(dmd_visibility_score_enabled=True)`) |
| Config file | `"dmd_visibility_score_enabled": true` |

> **Default: OFF** — zero behaviour change for existing configurations.

### CPU cost

Two extra `cv2.resize()` + lightweight numpy operations per frame.
On a 1080p source at 30 fps: typically **< 1 ms/frame extra** on any modern CPU.

---

---

## 🕐 Temporal Scene Memory *(v5.0.0 — Priority 2)*

### Problem

YOLO detection is inherently intermittent: a character briefly obscured by a wall, a fast cut, or a partially out-of-frame pose can cause 2–3 frames without a detection. The old behaviour snapped the camera back to the full-frame centre, producing a jarring oscillation.

### Solution

A **sliding deque of past ROI detections** (default 3 s at source FPS) is maintained in the main loop. When the live detector returns `None`, instead of centering the camera the engine computes a **linearly-weighted average** of the history:

```
weight[oldest] = 1   …   weight[most-recent] = N
ROI_synthetic = Σ(weight[i] × ROI[i]) / Σ weight[i]
```

The synthetic ROI is fed into the normal camera-smoothing path — so the camera gently continues the last known trajectory until detection resumes.

### Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `roi_history_window_s` | `3.0` | Sliding window in seconds. Set to `0` to restore legacy behaviour (snap to centre on no detection). |

> **Default: 3.0 s** — enabled automatically, no config change needed.

### CPU cost

One `deque` push + O(N) weighted sum where N = `fps × window_s`. At 30 fps × 3 s = 90 items: negligible (< 0.1 ms/frame).

---

## ✂️ Scene Change Detection *(v5.0.0 — Priority 3)*

### Problem

Hard cuts (instant scene transitions) leave the ROI history and floor estimator populated with data from the *previous* scene. The camera briefly drifts to a position that makes no sense for the new scene.

### Solution

Each frame is compared to the previous using **HSV histogram correlation** (H and V channels, 32 bins each, 64×32 downscale for speed). When the correlation drops below `1 − scene_change_threshold`, a cut is declared and all per-scene state is reset:
- ROI history deque cleared
- Camera smoothing reset to full-frame view
- Floor estimator re-initialised
- Look-ahead velocity cleared

### Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `scene_change_threshold` | `0.45` | Sensitivity: higher = less sensitive. `0` disables. Range 0–1. |

### CPU cost

Two 32-bin histogram compares on a 64×32 thumbnail: **< 0.2 ms/frame**.

---

## 🔍 Micro-detection Rejection *(v5.0.0 — Priority 4)*

### Problem

YOLO occasionally detects a partially-visible subject with a bounding box that is only a few pixels wide. After resize to 128×32 the subject occupies 1–2 pixels and becomes invisible noise.

### Solution

After every live ROI detection, the engine checks:
```
roi_area / (frame_w × frame_h) < min_roi_area_ratio  →  discard ROI
```

A discarded ROI triggers the **Temporal Scene Memory** fallback (Priority 2) — so the camera continues the last known trajectory instead of jumping to centre.

### Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `min_roi_area_ratio` | `0.02` | Minimum ROI area as a fraction of the source frame. `0` disables. |

> At 1920×1080: minimum useful ROI area = 1920 × 1080 × 0.02 ≈ **41 500 px²** (roughly 200×208).

### CPU cost

Two integer multiplications and a division per frame: **negligible**.

---

## ➡️ Directional Look-Ahead *(v5.0.0 — Priority 5)*

### Problem

When a subject moves horizontally, the camera tracks the *centre* of the subject. On a narrow 128-wide LED strip this puts the subject in the middle with equal space before and behind — but visually the viewer expects space *in front of* the direction of travel.

### Solution

The ROI centre velocity (current − previous frame) is computed each frame. The smoothed camera position is then offset by:

```
offset_x = sign(vx) × look_ahead_factor × (crop_width / 2)
```

The offset is clamped to the frame boundaries. Vertical look-ahead is applied at 50% of the horizontal factor (the DMD strip is very short vertically).

### Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `look_ahead_enabled` | `True` | Master switch. |
| `look_ahead_factor` | `0.25` | Fraction of crop half-width to offset. 0 = disabled. 0.15–0.35 recommended. |

> **Default: ON** with 25% lead. Set `look_ahead_enabled=False` or `look_ahead_factor=0` to disable.

### CPU cost

Two velocity differences and two clamp operations per frame: **negligible**.

---

## 👥 Multi-ROI Fusion *(v5.0.0 — Priority 6)*

### Problem

YOLO's default mode returns only the single highest-confidence person. In scenes with multiple characters (co-op games, crowd scenes, dialogues) the camera locks onto the dominant subject and ignores the rest, causing jerky panning as confidence rankings change.

### Solution

All per-frame detections above the confidence threshold are collected. When more than one box is found they are fused into a **confidence-weighted centroid box**:

```
fused_cx = Σ(score[i] × cx[i]) / Σ score[i]
fused_w  = Σ(score[i] × w[i])  / Σ score[i]
```

This gives a natural "centre of mass" of all visible subjects, weighted toward the most clearly-detected one. The result is fed into the normal P2/P3/P4 pipeline like any other ROI.

### Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `multi_roi_fusion_enabled` | `True` | Enable multi-person fusion. `False` = legacy single-best-box behaviour. |

> **Default: ON** — no config change needed.

### CPU cost

One ONNX inference call (unchanged) + O(N) weighted sum where N = number of detections above threshold. At most a few dozen extras: **< 0.5 ms/frame**.

---

## 🔍 Minimum Useful Size After Resize *(v5.0.0 — Priority 7)*

When zooming aggressively, the detected subject might end up occupying only a few pixels on the DMD, becoming a blurry, unrecognisable blob. This feature intercepts zoom commands that would cause the subject to drop below a hard minimum size *in the final output space* (e.g. 128×32).

If the estimated final dimensions are too small, the zoom is cancelled and the camera holds its previous view.

| Field | Default | Description |
|-------|---------|-------------|
| `min_subject_dmd_px` | `4` | Minimum size (in output pixels) the ROI must occupy. `0` disables this check. |

---

## 🕹 Smart Platformer Mode *(v5.0.0 — Priority 8)*

Optimised specifically for side-scrolling 2-D games (Mario, Sonic, Metroid).

Standard tracking centres the subject, meaning the floor moves up and down as the character jumps. Platformer mode instead:
1. **Locks the floor:** Uses the asymmetric EMA floor estimator to anchor the camera vertically so the ground stays at a fixed height (default: bottom 20% of the strip).
2. **Widens the view:** Expands the horizontal field of view by 50% to reveal more of the level ahead, preventing the "tunnel vision" effect.

| Field | Default | Description |
|-------|---------|-------------|
| `platformer_mode` | `False` | Enable platformer-specific framing logic. |
| `platformer_floor_ratio` | `0.80` | Vertical position of the floor (0.80 = 80% down from the top). |

---

## 🛡️ ROI Confidence System *(v5.0.0 — Priority 10)*

Replaces the hardcoded YOLO confidence threshold (`0.30`) with a configurable minimum.

When combined with **Priority 2 (Temporal Scene Memory)**, raising this threshold makes the camera much more stable: weak, flickering detections are discarded, and the camera relies on its smoothed memory trajectory instead of twitching.

| Field | Default | Description |
|-------|---------|-------------|
| `roi_confidence_min` | `0.0` | Minimum confidence `[0.0, 1.0]`. `0.0` uses the legacy `0.30` hardcoded fallback. |

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

#### 👤 Face Priority mode (automatic) — v5.0.0 improvements

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
