# 🎞️ DMD GIF Converter — v3.0.0

Converts **any animated GIF or video** (MP4, MKV, MOV, AVI, WEBM…) into a format optimised for a **128×32 HUB75 LED matrix panel** driven by an ESP32 (compatible with [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) and the [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF) library).

Now ships with a **full cross-platform graphical interface** — no command line needed.

---

## 🔍 GIF Search — download GIFs directly from the UI  *(new in v3.0.0)*

> **TL;DR — type a keyword, set a quantity, press ⬇ DL, and GIFs appear in the list ready to convert.**  
> Located in the **📁 Source files** panel on the left, between the file buttons and the list.

The GIF Search panel lets you search DuckDuckGo for animated GIFs and download them directly into a managed temporary folder. Each downloaded GIF is immediately added to the file list — no manual folder navigation needed.

```
Keyword + quantity  ──[DuckDuckGo image search]──▶  temp folder  ──▶  file list  ──▶  Convert
```

### Features

| Feature | Details |
|---|---|
| **Keyword search** | Any text — supports `Enter` key to trigger search |
| **Configurable quantity** | 1–50 GIFs per search (default: 10) |
| **Real-time progress** | Main progress bar updates as each file is downloaded |
| **Per-file feed** | Each downloaded GIF appears in the list immediately |
| **Cancel button** | Appears during download — stops after current file |
| **Error handling** | Timeouts, bad URLs and wrong MIME types are skipped with log entries |
| **Temp folder management** | All downloaded GIFs go to a managed temp dir, cleaned up on exit |
| **Graceful fallback** | If `duckduckgo-search` or `requests` are missing, the panel shows a warning and the button is disabled — no crash |

### How to use

1. In the **📁 Source files** panel → find the **🔍 GIF Search** section
2. Type a keyword (e.g. `pac-man`, `pixel art fire`, `retro arcade`)
3. Set the quantity (default: 10, max: 50)
4. Press **⬇ DL** or hit Enter
5. GIFs download one by one and appear in the file list
6. Select any, adjust parameters, and convert!

### Requirements

```bash
pip install duckduckgo-search requests
# already included in requirements_ui.txt — auto-installed by ./launch_ui.sh
```

---

## 🤖 Auto Action Framing — AI-powered cinematic camera

> **TL;DR — enable it, sit back, and watch the magic.**  
> Hidden in **🔧 Advanced Settings → 🎯 Auto Action Framing** · disabled by default.

This is the most powerful feature of the converter. Instead of a static crop or a simple vertical scroll, the **Auto Action engine** analyses every frame of your source video using **computer vision (OpenCV)** and generates a fully automated, **cinema-quality camera movement** before handing the result to ffmpeg:

```
Source video  ──[AI analysis]──▶  4:1 cinematic crop  ──[ffmpeg]──▶  128×32 DMD GIF
                    ↑
        Person detection (HOG)
        Motion detection (optical flow)
        Smooth exponential camera
        Intro panoramic establishing shot
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

Auto Action performs **full CPU-intensive computer vision** on every frame (HOG person detection, background subtraction, optical flow). This is significantly heavier than a simple ffmpeg pass:

- **CPU usage:** ~2–5× higher than standard conversion
- **Processing time per file:** roughly doubles
- **Memory:** each worker loads the full video as raw frames

For batch conversion of large libraries, this cost adds up. If you are converting retro sprites or pixel-art GIFs, the standard scroll pipeline is already optimal.  
**For live footage, sports, cinema clips, or any video with a person or moving subject → enable Auto Action and get professional results automatically.**

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
| `action_smoothness` | Camera smooth | `0.85` | `0` = instant · `0.98` = very slow camera |
| `action_zoom_max` | Zoom max | `1.8×` | Maximum dynamic zoom the AI camera can apply |
| `action_padding` | ROI padding | `0.20` | Extra space added around the detected subject |

### Detector modes

| Mode | Best for |
|---|---|
| `person` ★ default | Videos with people — uses HOG/SVM person detector, falls back to motion |
| `motion` | Sports, vehicles, fast action without clear human silhouette |
| `hybrid` | Merges person + motion bounding boxes — broadest coverage |
| `center` | No detection — keeps the camera centred (intro pan only) |

### Requirements

Auto Action requires **OpenCV** (installed automatically by `launch_ui.sh`):

```bash
pip install opencv-python   # or: pip install -r requirements_ui.txt
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

## ✨ What it does

| Source | Output behaviour |
|---|---|
| **Taller than 32 px** (character, scene) | Scroll N cycles (down→up), then holds at a configurable position |
| **Wider than tall** (logo, banner) | Vertical centring, natural GIF duration preserved |

**Processing pipeline:**
1. *(optional)* **🤖 Auto Action** — AI cinematic crop at native resolution (pre-ffmpeg)
2. *(optional)* **🎨 Smart Color Boost** — heuristic keyframe analysis, injects optimal colorimetry
3. Black background composite → eliminates source transparency (no clock bleed-through)
4. Proportional scale to 128 px wide, `bottom_crop_pct` % of bottom ignored (feet/floor)
5. Colorimetry boost for LED panels (contrast, saturation, gamma, sharpening)
6. 128×32 crop with smart scroll (cycle count + hold position)
7. Palette generation on actually-displayed pixels only (256 colours)
8. GIF encoding with transparency compression disabled

---

## 🖥️ Graphical interface

### Screenshots

![DMD GIF Converter UI](media/UI_PREVIEW.png)

### Features at a glance

| Feature | Details |
|---|---|
| **Import by file or folder** | ➕ individual files, 📂 entire folder — all video formats accepted |
| **🔍 GIF Search** | Search & download GIFs from DuckDuckGo — keyword + quantity, auto-populates the list |
| **Triple live preview** | SOURCE (left) + AUTO ACTION intermediate (middle) + DMD OUTPUT (right) |
| **DMD auto-refresh** | DMD preview rebuilds automatically ~2 s after you stop moving any slider |
| **Trim / clip** | Set start and end time — single-file conversion only |
| **⏱ Max Duration** | Cap clip length + place the window anywhere in the source |
| **🎨 Smart Color Boost** | One-click AI colorimetry — auto-adjusts contrast, saturation and gamma per source |
| **All standard parameters** | Sliders and drop-downs for mode, scroll, FPS, colorimetry |
| **🔧 Advanced Settings** | Collapsible panel — all extras hidden by default, default values never alter the output |
| **Batch folder** | Convert an entire folder in one click |
| **Convert all listed files** | One click to process the whole current list |
| **Real-time log** | Live progress feed in the UI |
| **Cross-platform** | macOS · Windows · Linux |

### 🔧 Advanced Settings panel (new in v2.1)

Expand the **🔧 Advanced Settings ▼** button at the bottom of the Parameters panel.  
All values default to "no effect" — standard output is 100% identical to v2.0.

#### 🎨 Smart Color Boost — AI heuristic colorimetry

> See the full dedicated section earlier in this README for the complete guide.

- Located directly in the **🎨 Content mode** block of the Parameters panel (not in Advanced)
- Analyses a **keyframe at 50 %** of the source and computes contrast / saturation / gamma / brightness automatically
- **Disables the manual colorimetry sliders** when active to prevent conflicts
- Negligible performance cost (<0.5 s per file) — uses OpenCV + NumPy
- Falls back silently to standard preset if OpenCV is unavailable

#### 🎯 Auto Action Framing — AI cinematic camera

> See the full dedicated section at the top of this README for the complete guide.

- **Disabled by default** — enable when you need intelligent camera movement on live footage
- Runs a full **computer vision pass** (OpenCV) on every frame before ffmpeg
- Generates a **4:1 native-resolution** intermediate clip that follows the action
- The **AUTO ACTION** preview canvas (middle panel) shows the result in real time
- Falls back gracefully to standard conversion if OpenCV is unavailable

| Slider | Default | Effect |
|---|---|---|
| Enable checkbox | `OFF` | Master switch |
| Detection mode | `person` | `person` / `motion` / `hybrid` / `center` |
| **Intro panoramic** | `1.5 s` | Wide establishing shot prepended (first frame frozen, full source replayed) |
| Action strength | `0.65` | How tightly the camera frames the subject |
| Camera smooth | `0.85` | Exponential smoothing — higher = slower camera |
| Zoom max | `1.8×` | Maximum allowed zoom-in |
| ROI padding | `0.20` | Breathing room around the detected subject |

#### ⏱ Max Duration

Caps the output clip length to a configurable maximum (default **2:00 min**).  
Move the **trim Start** slider to place the 2-minute window anywhere in the source video.  
Set to `0` or uncheck to disable.

#### 📍 Positioning

| Control | Description | Default |
|---|---|---|
| **Auto vertical scroll** ✅ | When checked: standard scroll behaviour (unchanged) | ✅ checked |
| **Zoom** | Scale multiplier before cropping (1.0 = fit to 128 px) | `1.0×` |
| **X offset** | Horizontal crop start in pixels (manual mode only) | `0 px` |
| **Y offset** | Vertical crop start in pixels (manual mode only) | `0 px` |

> Uncheck **Auto vertical scroll** to enable manual mode. Zoom first, then set X/Y to
> choose exactly which 128×32 window to crop from the scaled frame.
> The DMD preview updates automatically ~2 s after you stop dragging.

#### 🖼️ Multi-Dalle / Tiling

Configure the output resolution for multi-panel setups.

| Control | Default | Description |
|---|---|---|
| **Dimensions Preset** | `128×32 (1×1)` | Quick presets: `128×32`, `256×32`, `128×64` or Custom |
| **Custom Width** | `128` | Target width in pixels (only editable when preset = Custom) |
| **Custom Height** | `32` | Target height in pixels (only editable when preset = Custom) |

> The Auto Action framing engine always uses the correct target aspect ratio.

#### 💬 Text Overlay

Burn a text label directly into the output GIF. Text is **always applied on the final 128×32 output** (after all scaling / cropping), so even a small font remains as sharp as possible.

> **Two rendering backends** — used transparently:
> - **ffmpeg `drawtext`** when ffmpeg is compiled with `libfreetype` (Linux typical build)
> - **Pillow post-processing** fallback when drawtext is unavailable (Homebrew macOS default)  
>   Both produce identical results; the log shows which backend was used.

| Control | Default | Description |
|---|---|---|
| **Enable Text Overlay** | ☐ off | Master switch |
| **Text Content** | `""` | Text to render on every frame |
| **Font Size** | `8 px` | Font size in pixels (4–32 px) |
| **Text Color** | `white` | `white` / `yellow` / `red` / `green` / `blue` |
| **Text Position** | `bottom_center` | 9 anchor positions (top/middle/bottom × left/center/right) |
| **Font** | `HelvetiPixel.ttf` | Pixel font from `media/fonts/` |
| **Text Style** | `outline` | Rendering style — see table below |
| **Background box** | ☐ off | Dark semi-transparent box behind text |
| **Box opacity** | `60 %` | 10–100 % (visible only when Background box is on) |

**Text styles** (tuned for 128×32 visibility):

| Style | Effect | Best use |
|---|---|---|
| `outline` ★ default | 1 px black stroke around the glyph | Maximum readability on any background |
| `bold` | 1 px same-colour stroke → thicker glyph | Bright text on dark content |
| `shadow` | 1 px dark drop-shadow offset | Depth effect, slight readability gain |
| `none` | Plain text, no effect | Dark-on-light content only |

**Available fonts** (all optimised for 128×32 pixel DMD panels):

| Font file | Style |
|---|---|
| `HelvetiPixel.ttf` | Clean pixel sans-serif ★ default |
| `PixelMordred.ttf` | Bold pixel gothic |
| `BitCasual.ttf` | Casual retro pixel |
| `CursivePixel.ttf` | Pixel cursive |
| `justabit.ttf` | Minimal 1-bit style |
| `KarenBook.ttf` | Book / readable pixel |
| `OldWizard.ttf` | Fantasy / medieval pixel |
| `OrdinaryBasis.ttf` | Plain pixel |
| `Quintet.ttf` | Compact pixel |
| `TimesNewPixel.ttf` | Pixel serif |

> Font files must exist in `media/fonts/`. If the selected font is not found, text overlay is automatically disabled with a warning in the log.

**CLI flags:**

```bash
./dmd_gif_converter.py --text-overlay --text-content "PLAYER 1" \
  --text-font-size 10 --text-color yellow --text-position top_center \
  --text-font-file HelvetiPixel.ttf --text-style outline \
  --text-bg --text-bg-opacity 60
```

#### ✨ Visual Effects

| Effect | Filter | Default |
|---|---|---|
| **Hue shift** | ffmpeg `hue=h=…` | `0°` (off) |
| **Noise reduction** | ffmpeg `hqdn3d` | `0` (off) |
| **Film grain** | ffmpeg `noise=alls=…` | `0` (off) |
| **Vignette** | ffmpeg `vignette` | ☐ unchecked |

All effects are disabled by default. Non-zero values add extra ffmpeg filter passes *after* the standard colorimetry chain.

### Launch

```bash
./launch_ui.sh          # macOS / Linux  (recommended — handles venv automatically)
python3 dmd_gif_converter_ui.py   # if venv already activated
```

---

## 📋 Requirements

### 1 — System: Python 3.8+ and FFmpeg

#### 🍎 macOS
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install ffmpeg
```

#### 🪟 Windows
```powershell
winget install Gyan.FFmpeg
```
Or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add `C:\ffmpeg\bin` to your `PATH`.

#### 🐧 Linux (Debian / Ubuntu)
```bash
sudo apt update && sudo apt install python3 ffmpeg
```

**Fedora:**
```bash
sudo dnf install https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install python3 ffmpeg
```

**Arch:**
```bash
sudo pacman -S python ffmpeg
```

**Verify:**
```bash
python3 --version   # 3.8+
ffmpeg -version
```

---

### 2 — Python dependencies (UI only)

```bash
pip install -r requirements_ui.txt
```

Or directly:
```bash
pip install customtkinter Pillow "darkdetect==0.7.1" opencv-python duckduckgo-search requests
```

> `dmd_gif_converter.py` (CLI / engine) has **zero external dependencies** — standard library only.  
> `opencv-python` is optional — only required for the **Auto Action** AI feature. If absent, Auto Action is silently skipped.

---

## 🚀 Quick start

```bash
git https://github.com/red77290/dmd_gif_converter.git
cd dmd_gif_converter
```

Then launch with the script for your OS — **it sets everything up automatically on the first run** (creates a Python venv, installs dependencies):

| OS | Command |
|---|---|
| 🍎 macOS / 🐧 Linux | `./launch_ui.sh` |
| 🪟 Windows (double-click) | `launch_ui.bat` |
| 🪟 Windows (PowerShell) | `.\launch_ui.ps1` |

> **Why a launcher script instead of plain `python3`?**  
> On macOS, the system Python (CommandLineTools) ships with Tcl/Tk 8.5 which **crashes on macOS 15+ / 26 (Tahoe)**. The launcher automatically picks Homebrew Python 3.13 (Tk 9.0) and isolates dependencies in a venv.  
> On Linux, make sure `python3-tk` is installed alongside Python:  
> `sudo apt install python3-tk` · `sudo dnf install python3-tkinter` · `sudo pacman -S tk`

---

## ▶️ CLI usage (no UI required)

Place the script next to folders named `gifs_*`:

```
my_folder/
├── dmd_gif_converter.py
├── gifs_Arcade/
│   ├── metalslug.gif
│   └── kof98.mp4        ← MP4, MKV, MOV, AVI, WEBM… also accepted
└── gifs_Consoles/
    └── mario.gif
```

```bash
# Default: pixel_art mode, auto-detects gifs_* folders
./dmd_gif_converter.py

# Override mode or workers
./dmd_gif_converter.py --mode anime --workers 6

# Process specific folders only
./dmd_gif_converter.py gifs_Arcade gifs_Consoles

# Full custom colorimetry
./dmd_gif_converter.py --mode custom --saturation 2.8 --contrast 1.7

# Tune scroll
./dmd_gif_converter.py --scroll-speed 32 --scroll-cycles 1.75

# Help
./dmd_gif_converter.py --help
```

Output folders are created automatically (`Arcade/`, `Consoles/`…).

**Sample log:**
```
12:34:01 [INFO   ] === gifs_Arcade → Arcade  (42 file(s)) | mode=pixel_art ===
12:34:02 [INFO   ] [SCROLL ] metalslug.gif | src 320x240 → 128x96 | scroll_dist=64px | cycles=1.5 (full=1 frac=0.50 stop=32px) | fps=12.5 | total=4.54s
12:34:04 [INFO   ] [OK    ] metalslug.gif
```

---

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
| `action_smoothness` | `0.85` | Camera exponential smoothing factor |
| `action_zoom_max` | `1.8` | Maximum AI zoom factor |
| `action_padding` | `0.20` | Padding around detected ROI |
| `bg_sub_enable` | `False` | Replace background with black (maximises subject contrast) |
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

---

## ❓ Troubleshooting

| Problem | Solution |
|---|---|
| `ffmpeg: command not found` | FFmpeg not in PATH → re-read installation section |
| Preview is blank | FFmpeg must be installed and in PATH |
| `[ERROR] xxx — metadata unreadable` | Corrupted or unsupported file |
| Very slow conversion | Increase `--workers` (SSD + multi-core recommended) |
| Colours too saturated | Switch to `--mode anime` or lower `--saturation` in custom mode |
| Output too dark | Raise `--brightness` (e.g. `0.05`) or `--gamma` (e.g. `0.95`) |
| Scroll too fast / slow | Adjust `--scroll-speed` (default `24.0`) |
| Stops at wrong position | Adjust `--scroll-cycles` (default `1.5` = centre hold) |
| Banding on gradients | Switch to `anime` or `cinema` — dithering causes streaks with scrolling |
| DMD preview not auto-refreshing | Wait ~2 s after last slider move; make sure a file is selected |
| Manual mode shows wrong area | Increase Zoom first, then move X/Y sliders |
| Auto Action says "OpenCV not installed" | Run `pip install opencv-python` or re-run `./launch_ui.sh` (installs automatically) |
| Auto Action preview is slow to appear | Normal — AI analysis takes a few seconds per video; progress shown in the AUTO ACTION canvas |
| Auto Action result looks wrong | Try a different **Detection mode** (`motion` or `hybrid`) — `person` mode works best with visible human silhouettes |
| Smart Color Boost makes colours look wrong | Disable it and tune manually — it works best on heterogeneous or poorly-exposed footage |
| Smart Color Boost log shows `fallback` | OpenCV unavailable — run `pip install opencv-python` |
| Text overlay not appearing | Make sure **Text Content** is not empty and the font file exists in `media/fonts/` |
| `[ERROR] Font file '…' not found` | The selected font is missing from `media/fonts/` — choose a different font in the dropdown |
| `[TEXT  ] … ffmpeg drawtext unavailable` | Normal on macOS Homebrew ffmpeg (compiled without `--enable-libfreetype`) — **Pillow fallback is used automatically**, no action required |
| GIF Search button is disabled | Install missing deps: `pip install duckduckgo-search requests` (or re-run `./launch_ui.sh`) |
| GIF Search returns 0 results | DuckDuckGo may throttle rapid searches — wait a few seconds and retry |
| Downloaded GIFs are very large | Normal for web GIFs — the converter will resize them to 128×32 automatically |
| GIF Search timeout errors | Some image hosts are slow — increase quantity to compensate for skipped URLs |

---

## 📄 License

MIT — free to use, modify and distribute.

---

## 🙏 Credits

- **[FFmpeg](https://ffmpeg.org/)** — video processing engine
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** — modern cross-platform UI framework
- **[Pillow](https://python-pillow.org/)** — image handling for the UI preview and text overlay fallback
- **[DuckDuckGo](https://duckduckgo.com/)** — image search API powering the GIF Search feature (no API key required)
- **[duckduckgo-search](https://github.com/deedy5/duckduckgo_search)** — Python wrapper for the DuckDuckGo search API
- **[Requests](https://docs.python-requests.org/)** — HTTP library used for GIF downloads
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — AnimatedGIF library for ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — high-performance DMA HUB75 driver for ESP32
- **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)** — the project this tool was built for
- **[Pixel Fonts Pack by ovate](https://github.com/ovate/Pixel-Fonts-Pack)** — pixel-perfect TTF fonts bundled in `media/fonts/`
