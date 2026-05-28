# 🎞️ dmd_gif_converter.py — GIF Converter for 128×32 DMD LED Panels

Converts any animated GIF into a format optimized for a **128×32 HUB75 LED matrix panel** driven by an ESP32 (compatible with [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) and the [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF) library).

## ✨ What it does

| Input GIF | Output behavior |
|---|---|
| **Taller than 32px** (character, scene) | Vertical **ping-pong scroll** (top→bottom→top) at constant speed |
| **Wider than tall** (logo, banner) | Vertical centering, natural GIF duration preserved |

**Processing pipeline:**
1. Black background composite → eliminates source transparency (no clock bleeding through)
2. Proportional scale to 128px wide
3. Colorimetry boost for LED panels (contrast, saturation, gamma, sharpening)
4. 128×32 crop with ping-pong scroll (triangle wave expression)
5. Palette generation on actually-displayed pixels only (256 colors)
6. GIF encoding with transparency compression disabled

---

## 📋 Requirements

### System dependencies

The script requires **Python 3.8+** and **FFmpeg** (including `ffprobe`).

---

### 🍎 macOS

**Option A — Homebrew (recommended)**
```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install FFmpeg
brew install ffmpeg
```

**Option B — MacPorts**
```bash
sudo port install ffmpeg
```

**Verify:**
```bash
python3 --version   # must be 3.8+
ffmpeg -version
ffprobe -version
```

> Python comes pre-installed on macOS. If needed: `brew install python`

---

### 🪟 Windows

**1. Python**

Download and install from [python.org](https://www.python.org/downloads/).  
⚠️ Check **"Add Python to PATH"** during installation.

**2. FFmpeg**

**Option A — winget (Windows 10/11, recommended)**
```powershell
winget install Gyan.FFmpeg
```

**Option B — Manual**
1. Download the *full build* from [ffmpeg.org/download.html](https://ffmpeg.org/download.html) → Windows → gyan.dev
2. Extract to a permanent location (e.g. `C:\ffmpeg\`)
3. Add `C:\ffmpeg\bin` to your **PATH** environment variable:
   - Search "Environment variables" in Start menu
   - `System variables` → `Path` → `Edit` → `New` → `C:\ffmpeg\bin`
4. Restart your terminal

**Verify (PowerShell or cmd):**
```powershell
python --version
ffmpeg -version
ffprobe -version
```

---

### 🐧 Linux

**Debian / Ubuntu / Mint**
```bash
sudo apt update
sudo apt install python3 ffmpeg
```

**Fedora / RHEL / CentOS**
```bash
sudo dnf install python3 ffmpeg
# If ffmpeg is not in official repos:
sudo dnf install https://download1.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install ffmpeg
```

**Arch Linux**
```bash
sudo pacman -S python ffmpeg
```

**Verify:**
```bash
python3 --version
ffmpeg -version
ffprobe -version
```

---

## 🐍 Python dependencies

**`dmd_gif_converter.py` has zero external dependencies** — it uses only the Python standard library (`os`, `subprocess`, `math`, `json`, `logging`, `concurrent.futures`).

> ⚠️ The `requirements.txt` in this repository applies to **other scripts** in the project (older versions using Pillow / numpy / imageio). It is **not needed** for `dmd_gif_converter.py`.

No `pip install` is required. If you want an isolated environment anyway:

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 dmd_gif_converter.py
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python dmd_gif_converter.py
```

---

## 📁 Folder structure

The script auto-detects all folders starting with `gifs_` in the **current working directory** and creates a matching output folder with the prefix removed.

```
my_folder/
├── dmd_gif_converter.py
│
├── gifs_Arcade/             ← source folder (must start with "gifs_")
│   ├── metalslug.gif
│   ├── kof98.gif
│   └── ...
├── gifs_Consoles/           ← another source folder
│   ├── mario.gif
│   └── ...
│
│   (after running the script)
│
├── Arcade/                  ← generated output (same name without "gifs_")
│   ├── metalslug.gif        ← 128×32, ping-pong scroll
│   └── kof98.gif
└── Consoles/
    └── mario.gif            ← 128×32, centered or scrolled
```

---

## ▶️ Usage

```bash
# Place the script in the folder that contains your gifs_* folders
cd /path/to/my_folder

# Run
python3 dmd_gif_converter.py        # macOS / Linux
python  dmd_gif_converter.py        # Windows
```

**Sample log output:**
```
12:34:01 [INFO   ] === Processing: gifs_Arcade → Arcade (42 file(s)) ===
12:34:02 [INFO   ] [SCROLL ] metalslug.gif | src 320x240 → 128x96 (crop→128x32) | scroll=64px | fps_src=12.0 → render=12.5fps (8cs/frame) | step=3px | speed≈37px/s | cycle=10.67s×1=10.67s
12:34:04 [INFO   ] [OK    ] metalslug.gif
12:34:02 [INFO   ] [CENTER ] logo.gif | src 640x80 → 128x16 (centered) | fps_src=10.0 → render=10 | duration=3.00s
12:34:05 [INFO   ] [OK    ] logo.gif
```

---

## ⚙️ Configuration

All parameters are grouped at the **top of the file** with inline documentation:

### Content mode (`MODE`)

**This is the only setting you need to change** based on your source GIFs. It automatically adjusts all colorimetry and dithering:

```python
MODE = "pixel_art"   # "pixel_art" | "anime" | "cinema" | "custom"
```

| Mode | Best for | Saturation | Sharpening | Dithering |
|---|---|---|---|---|
| `"pixel_art"` | Retro sprites, arcade, consoles, **anime** ★ default | `2.2` 🔥 max | `1.8` aggressive | `none` |
| `"anime"` | Softer alternative if `pixel_art` feels too aggressive | `1.9` ✨ vibrant | `1.3` crisp outlines | `none` |
| `"cinema"` | Live-action films, real photography | `1.3` 🎞️ natural | `0.8` gentle | `none` |
| `"custom"` | Manual tuning of each constant | free | free | free |

> ✅ **`"pixel_art"` is the default and produces output identical to the original `moving_gif_V0.py`** — same contrast, saturation, gamma, sharpening and filter graph. If your anime GIFs looked great in V0, keep this mode.  
> The `"anime"` preset is only an optional softer alternative to try if a specific source looks over-saturated or too sharp.  
> Bayer dithering applies its grid pattern in **output frame coordinates** (fixed on screen). As content scrolls, the same pixel appears at a different Y position each frame while the Bayer grid stays still → **persistent vertical streaks in the scroll direction**.  
> Error-diffusion (`sierra2_4a`) causes temporal noise that "crawls" frame to frame.  
> At 128×32 with 256 colors, flat quantization (`"none"`) gives cleaner results than any dithering for scrolling content.  
> If your source never scrolls (logo/banner, `distance ≤ 0`), you can set `DITHER = "bayer:bayer_scale=1"` in `"custom"` mode for smoother gradients.

### Detailed parameters

```python
# ── Parallelism ────────────────────────────────────────────────────────────────
MAX_WORKERS = 2        # Number of parallel ffmpeg conversions

# ── Scroll ─────────────────────────────────────────────────────────────────────
SCROLL_SPEED_PX_S = 32.0   # Scroll speed (pixels per second)

# ── Render FPS ──────────────────────────────────────────────────────────────────
FPS_MIN = 10.0             # Upsample sources below this FPS
FPS_MAX = 25.0             # Hard cap for ESP32 compatibility

# ── Manual colorimetry (MODE = "custom" only) ───────────────────────────────────
CONTRAST    = 1.6          # 0.5–2.0  Dark/bright plane separation
SATURATION  = 2.2          # 0.0–3.0  Color vividness
BRIGHTNESS  = -0.03        # -1–+1    LED glow compensation
GAMMA       = 0.85         # 0.1–2.0  Midtone correction (< 1 = darker mids)
SHARPEN_LUM = 1.8          # Luma sharpening  → crisp edges
SHARPEN_CHR = 0.5          # Chroma sharpening → no color fringing
DITHER      = "none"       # "none" | "bayer:bayer_scale=1" | "bayer:bayer_scale=2"
```

### `MAX_WORKERS` tuning guide

| Machine | `MAX_WORKERS` |
|---|---|
| MacBook Pro M3 Pro (11 cores, 36GB) | `8` |
| Desktop SSD, 8+ cores, 16GB+ RAM | `6` to `8` |
| Desktop SSD, 4 cores, 8GB RAM | `3` to `4` |
| Laptop or HDD | `2` |

---

## 🔍 How it works

### Tall GIFs — ping-pong scroll

When the source GIF is taller than 32px after scaling, the script generates a **ping-pong scroll**: the content slides from top to bottom, then back up, in a seamless loop. The center of the image (where the action usually is) appears on both the downward and upward passes.

- Scroll speed is **constant in px/second** regardless of source FPS
- Output FPS is snapped to a **clean GIF value** (10, 12.5, 20 or 25fps) to avoid judder from centisecond quantization
- Output duration covers at least one full ping-pong cycle **and** the full source GIF animation

### Wide GIFs — static centering

When the GIF is wider than tall (logo, banner), it is **vertically centered** on the 32px panel. The natural source duration is respected (minimum 1 second).

### Transparency elimination

Two layers of protection against the ESP32 frame buffer (clock) showing through:

| Layer | Mechanism | Blocks |
|---|---|---|
| `color=black` + `overlay` | ffmpeg compositor | Source alpha / transparent frames (sprite with transparent background) |
| `-gifflags -offsetting-transdiff` | GIF muxer option | Delta encoding (unchanged pixels marked transparent → clock bleeds through) |

### GIF FPS quantization

GIF stores frame delays as **whole centiseconds**. Using a non-clean FPS causes rounding:

```
Requested FPS  → Frame delay  → Actual FPS    → Effect
─────────────────────────────────────────────────────────
15.0 fps       → 6.67cs → 7cs → 14.28 fps  ❌ visible judder
12.0 fps       → 8.33cs → 8cs → 12.5  fps  ⚠️ slight
10.0 fps       → 10cs         → 10.0  fps  ✅ clean
12.5 fps       → 8cs          → 12.5  fps  ✅ clean
20.0 fps       → 5cs          → 20.0  fps  ✅ clean
25.0 fps       → 4cs          → 25.0  fps  ✅ clean
```

The `snap_to_clean_fps()` function always selects a value from `[10, 12.5, 20, 25]`.

---

## ❓ Troubleshooting

| Problem | Solution |
|---|---|
| `ffmpeg: command not found` | FFmpeg is not in PATH → re-read the installation section |
| `[ERROR] xxx.gif - metadata unreadable` | Corrupted or unsupported GIF → inspect the file |
| No folders found | Check that source folders start with `gifs_` and that you run the script from the right directory |
| Very slow conversion | Increase `MAX_WORKERS` if you have an SSD and multiple CPU cores |
| Colors look too saturated | Switch to `MODE = "anime"` or lower `SATURATION` in `"custom"` mode |
| Output looks too dark | Raise `BRIGHTNESS` (e.g. `0.05`) or `GAMMA` (e.g. `0.95`) |
| Scroll too fast / too slow | Adjust `SCROLL_SPEED_PX_S` |
| Color banding on gradients (sky, shadows) | Switch to `MODE = "anime"` or `MODE = "cinema"` for gentler colorimetry — dithering cannot be used with scrolling content (causes streaks) |

---

## 📄 License

MIT — free to use, modify and distribute.

---

## 🙏 Credits

- **[FFmpeg](https://ffmpeg.org/)** — video processing engine
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — AnimatedGIF library for ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — high-performance DMA HUB75 driver for ESP32
- **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)** — the project this tool was built for

