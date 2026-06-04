# Auto Action Framing (Experimental)

This feature runs **before** the regular ffmpeg conversion pipeline.
It creates an intermediate video that follows action/person areas at the target aspect ratio, then the normal DMD conversion runs on it.

---

## Detection Modes

| Mode | Behaviour |
|------|-----------|
| `person` *(default)* | Prioritise HOG person detector, fall back to motion |
| `motion` | Prioritise moving regions, fall back to person |
| `hybrid` | Merge person + motion bounding boxes when both detected |
| `center` | Disable detection — static centre framing |

---

## Auto Crop Features

Two new **auto crop** modes let the system automatically find where the subject starts and ends vertically, eliminating manual guesswork.

### Auto Bottom Crop (`auto_bottom_crop`)

Samples the video to find where the subject **ends at the bottom** (feet, floor line).
Crops out everything below — HUD elements, floor tiles, subtitle bars.

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
- The camera is automatically **constrained to the head region** for the entire tracking phase → the face is always fully visible on screen, even if the character is much taller than the DMD resolution
- A `[face priority 👤]` tag appears in the conversion log when this mode activates

This mode activates when the **majority (> 50 %) of sampled frames** have a body that is too tall — it won't trigger on a single jump or outlier frame.

> Percentile-based analysis (5th for top, 95th for bottom) makes all measurements robust to detection outliers and momentary jumps.

### Manual vs Auto toggle

Both crops have an **independent toggle** (checkbox) and a manual slider:

- **Auto ON** → slider disabled; value computed automatically at render time.
- **Auto OFF** → slider active; you set the crop percentage manually.

The two modes are fully independent — auto bottom + manual top is valid.

---

## UI Usage

1. Open `🔧 Advanced Settings`
2. Enable `Auto Action Framing (pre-ffmpeg)`
3. Keep detector at `person` (default) or choose another mode
4. Tune strength / smoothness / zoom max / padding
5. **Bottom crop:**
   - Tick `Auto bottom crop` to detect feet / floor automatically, **or**
   - Leave unticked and drag the `Bottom crop (%)` slider manually
6. **Top crop:**
   - Tick `Auto top crop` to detect head / ceiling automatically, **or**
   - Leave unticked and drag the `Top crop (%)` slider manually

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
| `--start` | — | Clip start time in seconds |
| `--end` | — | Clip end time in seconds |

---

## Notes

- Requires OpenCV (`opencv-python`). If missing, conversion falls back to the normal pipeline.
- Default settings keep this feature **disabled** — existing behaviour is unchanged.
- Auto crop performs a quick **pre-scan** (~40 evenly-spaced frames) before the main pass.
- When auto mode is active, the corresponding manual slider value is ignored.
