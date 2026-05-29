# 🎞️ DMD GIF Converter — v2.0

Converts **any animated GIF or video** (MP4, MKV, MOV, AVI, WEBM…) into a format optimised for a **128×32 HUB75 LED matrix panel** driven by an ESP32 (compatible with [Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite) and the [AnimatedGIF](https://github.com/bitbank2/AnimatedGIF) library).

Now ships with a **full cross-platform graphical interface** — no command line needed.

## ✨ What it does

| Source | Output behaviour |
|---|---|
| **Taller than 32 px** (character, scene) | Scroll **top → bottom → centre → hold** then loop |
| **Wider than tall** (logo, banner) | Vertical centring, natural GIF duration preserved |

**Processing pipeline:**
1. Black background composite → eliminates source transparency (no clock bleed-through)
2. Proportional scale to 128 px wide, `bottom_crop_pct` % of bottom ignored (feet/floor)
3. Colorimetry boost for LED panels (contrast, saturation, gamma, sharpening)
4. 128×32 crop with smart scroll: top → bottom → centre → hold
5. Palette generation on actually-displayed pixels only (256 colours)
6. GIF encoding with transparency compression disabled

---

## 🖥️ Graphical interface — new in v2.0

### Screenshots

**Source preview** — animated playback of the original file, trim sliders, full parameter panel:

![Source preview](media/UI_SOURCE.png)

**DMD preview** — the actual 128×32 render scaled ×5, ready to flash:

![DMD preview](media/UI_PREVIEW.png)

### Features at a glance

| Feature | Details |
|---|---|
| **Import by file or folder** | ➕ individual files, 📂 entire folder — all video formats accepted |
| **Animated source preview** | Plays the source file directly in the app |
| **DMD preview** | Runs the full conversion pipeline and shows the 128×32 result scaled ×5 |
| **Trim / clip** | Set start and end time — single-file conversion only |
| **All parameters exposed** | Sliders and drop-downs for every setting |
| **Batch folder** | Convert an entire folder in one click |
| **Convert all listed files** | One click to process the whole current list |
| **Real-time log** | Live progress feed in the UI |
| **Cross-platform** | macOS · Windows · Linux |

### Launch

```bash
python3 dmd_gif_converter_ui.py      # macOS / Linux
python  dmd_gif_converter_ui.py      # Windows
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
pip install customtkinter Pillow
```

> `dmd_gif_converter.py` (CLI / engine) has **zero external dependencies** — standard library only.

---

## 🚀 Quick start

```bash
git clone https://github.com/fjgordillo86/RetroPixelLED-Lite.git
cd RetroPixelLED-Lite/dmd_gif_converter
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
cd my_folder
python3 dmd_gif_converter.py        # macOS / Linux
python  dmd_gif_converter.py        # Windows
```

Output folders are created automatically (`Arcade/`, `Consoles/`…).

**Sample log:**
```
12:34:01 [INFO   ] === Processing: gifs_Arcade → Arcade (42 file(s)) | mode=pixel_art ===
12:34:02 [INFO   ] [SCROLL ] metalslug.gif | src 320x240 → 128x96 (effective 128x82) | scroll=50px | fps=12.5 | total=4.54s
12:34:04 [INFO   ] [OK    ] metalslug.gif
```

---

## ⚙️ Parameters

All parameters are available as **sliders/drop-downs in the UI** and as constants at the top of the script for CLI use.

### Content mode

| Mode | Best for | Saturation | Sharpening |
|---|---|---|---|
| `pixel_art` | Retro sprites, arcade, consoles ★ default | `2.2` 🔥 | `1.8` aggressive |
| `anime` | Softer for complex gradients | `1.9` ✨ | `1.3` crisp |
| `cinema` | Live-action films, photography | `1.3` 🎞️ | `0.8` gentle |
| `custom` | Manual control | free | free |

### Full parameter reference

| Parameter | Default | Description |
|---|---|---|
| `max_workers` | `2` | Parallel ffmpeg processes |
| `scroll_speed` | `24.0` | Scroll speed (px/s) |
| `bottom_crop_pct` | `0.15` | Bottom fraction ignored (feet/floor) |
| `pause_center_s` | `1.5` | Pause at centre before restarting (s) |
| `fps_min` | `10.0` | Upsample sources below this FPS |
| `fps_max` | `25.0` | Hard cap (ESP32 compatibility) |
| `contrast` | `1.6` | Custom mode — 0.5 to 2.5 |
| `saturation` | `2.2` | Custom mode — 0.0 to 4.0 |
| `brightness` | `-0.03` | Custom mode — LED glow compensation |
| `gamma` | `0.85` | Custom mode — midtone correction |
| `sharpen_lum` | `1.8` | Luma sharpening |
| `sharpen_chr` | `0.5` | Chroma sharpening |
| `dither` | `none` | Recommended `none` for scrolling content |

### `MAX_WORKERS` tuning

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
top (y=0) ──scroll down──▶ bottom ──scroll up──▶ centre ──hold──▶ (loop to top)
```

- **Bottom crop**: bottom 15 % (feet, floor) ignored → shorter scroll distance
- **Centre hold**: 1.5 s pause at centre before restarting
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
| Very slow conversion | Increase `max_workers` (SSD + multi-core recommended) |
| Colours too saturated | Switch to `anime` or lower `saturation` in `custom` mode |
| Output too dark | Raise `brightness` (e.g. `0.05`) or `gamma` (e.g. `0.95`) |
| Scroll too fast / slow | Adjust `scroll_speed` (default `24.0`) |
| Banding on gradients | Switch to `anime` or `cinema` — dithering causes streaks with scrolling |

---

## 📄 License

MIT — free to use, modify and distribute.

---

## 🙏 Credits

- **[FFmpeg](https://ffmpeg.org/)** — video processing engine
- **[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter)** — modern cross-platform UI framework
- **[Pillow](https://python-pillow.org/)** — image handling for the UI preview
- **[Bitbank2](https://github.com/bitbank2/AnimatedGIF)** — AnimatedGIF library for ESP32
- **[Mrfaptastic](https://github.com/mrfaptastic/ESP32-HUB75-MatrixPanel-DMA)** — high-performance DMA HUB75 driver for ESP32
- **[Retro Pixel LED Lite](https://github.com/fjgordillo86/RetroPixelLED-Lite)** — the project this tool was built for

