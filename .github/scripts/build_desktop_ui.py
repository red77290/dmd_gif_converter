#!/usr/bin/env python3
"""
Hermetic Out-of-the-Box Desktop UI Builder for DMD GIF Converter (CI/CD only).

Builds standalone desktop UI packages with zero modification to the core library,
CLI, or `dmd_media_showcase` compatibility:
- Windows (`x64`): Single-file `DMD_GIF_Converter_Windows_x64.exe` (`--onefile --windowed`)
  bundling Python, CustomTkinter, OpenCV, ONNXRuntime, YOLOv8n (`yolov8n.onnx`),
  all pixel-art `.ttf` fonts, `ddgs` GIF search, MSVC runtime DLLs, and portable
  static `ffmpeg.exe` + `ffprobe.exe` (with `CREATE_NO_WINDOW` anti-flash hook).
- macOS (`arm64` / `x64`): Compressed `DMD_GIF_Converter_macOS_<arch>.dmg` containing
  `DMD GIF Converter.app` + `/Applications` drag-and-drop shortcut, portable
  `ffmpeg` + `ffprobe` with relocated `@loader_path` `.dylib`s (zero Homebrew
  runtime dependency), YOLOv8n ONNX model, pixel-art fonts, and deep codesign.
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DIST_DESKTOP_DIR = ROOT / "dist" / "desktop"
BUILD_DESKTOP_DIR = ROOT / "build" / "desktop_ui"

YOLO_MODEL_URL = (
    "https://huggingface.co/flightsnotights/yolov8n_onnx/resolve/main/yolov8n.onnx"
)
YOLO_MIN_BYTES = 5_000_000

RUNTIME_HOOK_CODE = r'''
import os
import re as _re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

# 1. Ensure sys.stdout / sys.stderr are valid streams under --windowed / --noconsole
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 2. Silence noisy OpenCV/FFmpeg stderr probes before cv2 imports
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "loglevel;quiet")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

# 3. Prepend bundled portable ffmpeg/ffprobe directory to PATH
_base_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
_candidate_bins = [
    _base_dir.parent / "Resources" / "ffmpeg_bin",  # macOS .app isolated FFmpeg dir
    _base_dir / "bin",                              # Windows / Linux --onefile FFmpeg dir
]
_prepend_paths = []
for _bdir in _candidate_bins:
    if _bdir.is_dir():
        if sys.platform != "win32":
            for _tool in ("ffmpeg", "ffprobe"):
                _tp = _bdir / _tool
                if _tp.is_file() and not os.access(_tp, os.X_OK):
                    try:
                        _tp.chmod(_tp.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                    except OSError:
                        pass
        _prepend_paths.append(str(_bdir))
if _prepend_paths:
    os.environ["PATH"] = os.pathsep.join([*_prepend_paths, str(_base_dir), os.environ.get("PATH", "")])

# 4. Configure bundled CA certificates for HTTPS (GIF search / requests / ddgs)
_cacert = _base_dir / "certifi" / "cacert.pem"
if _cacert.is_file():
    os.environ.setdefault("SSL_CERT_FILE", str(_cacert))
    os.environ.setdefault("REQUESTS_CA_BUNDLE", str(_cacert))

# 5. Pre-seed bundled YOLOv8n ONNX model into user cache for 100% offline Auto-Action
_bundled_yolo = _base_dir / "models" / "yolov8n.onnx"
if _bundled_yolo.is_file():
    try:
        _cache_dir = Path.home() / ".cache" / "dmd_gif_converter"
        _target_yolo = _cache_dir / "yolov8n.onnx"
        if not _target_yolo.is_file() or _target_yolo.stat().st_size < 1_000_000:
            _cache_dir.mkdir(parents=True, exist_ok=True)
            _tmp_yolo = _cache_dir / f".yolov8n.{os.getpid()}.tmp"
            shutil.copy2(_bundled_yolo, _tmp_yolo)
            os.replace(_tmp_yolo, _target_yolo)
    except OSError:
        pass

# 6. Prevent flashing cmd.exe console windows & escape Windows drive colons in drawtext fontfile
if sys.platform == "win32":
    _orig_popen_init = subprocess.Popen.__init__
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _DRAWTEXT_COLON_RE = _re.compile(r"(drawtext=fontfile=')([A-Za-z]):/")

    def _escape_drawtext_win(arg: str) -> str:
        return _DRAWTEXT_COLON_RE.sub(lambda m: m.group(1) + m.group(2) + "\\:/", arg)

    def _quiet_popen_init(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = _CREATE_NO_WINDOW
        if args and isinstance(args[0], (list, tuple)) and args[0]:
            prog = str(args[0][0]).lower()
            if prog.endswith(("ffmpeg", "ffmpeg.exe")):
                patched_cmd = [
                    _escape_drawtext_win(a) if isinstance(a, str) else a
                    for a in args[0]
                ]
                args = (patched_cmd, *args[1:])
        _orig_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _quiet_popen_init

# 7. Avoid read-only '/' cwd when launched from Finder / LaunchServices on macOS
if sys.platform == "darwin":
    try:
        if os.getcwd() == "/":
            os.chdir(Path.home())
    except OSError:
        pass
'''

ENTRYPOINT_CODE = r'''
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


def _run_standalone_selftest() -> int:
    lines = []

    def _log(msg: str) -> None:
        lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:
            pass

    class _SelftestLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING or "[FFMPEG]" in record.getMessage():
                _log(f"[CORE-LOG] {record.getMessage()}")

    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger().addHandler(_SelftestLogHandler())

    report_file = os.environ.get("DMD_SELFTEST_REPORT_FILE", "").strip()
    try:
        assert getattr(sys, "frozen", False), "Binary is not running in PyInstaller frozen mode"
        meipass = Path(getattr(sys, "_MEIPASS")).resolve()
        bundle_root = meipass.parent if sys.platform == "darwin" else meipass
        _log(f"[SELFTEST] Frozen _MEIPASS = {meipass} (bundle_root = {bundle_root})")

        # 1. Verify bundled portable ffmpeg & ffprobe take precedence over system PATH
        for tool in ("ffmpeg", "ffprobe"):
            found = shutil.which(tool)
            assert found, f"Bundled '{tool}' not found in PATH"
            resolved = Path(found).resolve()
            _log(f"[SELFTEST] {tool} -> {found} (resolved: {resolved})")
            assert bundle_root in resolved.parents or bundle_root in Path(found).parents, (
                f"{tool} did not resolve inside bundle ({found} vs {bundle_root})"
            )

        ff_filters = subprocess.run(
            ["ffmpeg", "-filters"], capture_output=True, text=True, timeout=15, check=True
        )
        flt_out = ff_filters.stdout + ff_filters.stderr
        for req_flt in ("palettegen", "paletteuse", "scale", "crop"):
            assert req_flt in flt_out, f"Bundled ffmpeg missing required filter: {req_flt}"
        _log(f"[SELFTEST] ffmpeg drawtext={'drawtext' in flt_out}")

        ff_enc = subprocess.run(
            ["ffmpeg", "-encoders"], capture_output=True, text=True, timeout=15, check=True
        )
        assert "libx264" in (ff_enc.stdout + ff_enc.stderr), "Bundled ffmpeg missing libx264 encoder"
        subprocess.run(["ffprobe", "-version"], capture_output=True, text=True, timeout=15, check=True)
        _log("[SELFTEST] Portable ffmpeg + ffprobe + libx264 verified")

        # 2. Verify all 10 pixel-art fonts at both core.py and pillow_overlay.py paths
        import src.engine.conversion.core as conv_core
        import src.engine.conversion.services.pillow_overlay as pil_ov

        expected_fonts = [
            "HelvetiPixel.ttf",
            "PixelMordred.ttf",
            "BitCasual.ttf",
            "CursivePixel.ttf",
            "justabit.ttf",
            "KarenBook.ttf",
            "OldWizard.ttf",
            "OrdinaryBasis.ttf",
            "Quintet.ttf",
            "TimesNewPixel.ttf",
        ]
        core_fonts_dir = Path(conv_core.__file__).parent.parent.parent.parent / "media" / "fonts"
        pil_fonts_dir = Path(pil_ov.__file__).parent.parent.parent.parent / "media" / "fonts"
        for fname in expected_fonts:
            assert (core_fonts_dir / fname).is_file(), f"Missing core font: {core_fonts_dir / fname}"
            assert (pil_fonts_dir / fname).is_file(), f"Missing overlay font: {pil_fonts_dir / fname}"
        _log(f"[SELFTEST] All {len(expected_fonts)} pixel-art fonts verified")

        # 3. Verify offline-seeded YOLOv8n ONNX model & ONNXRuntime session inference
        import numpy as np
        from src.plugins.detectors.detector import _FrameDetector, _get_model_path

        yolo_cached = Path(_get_model_path())
        assert yolo_cached.is_file() and yolo_cached.stat().st_size > 5_000_000, (
            f"Seeded YOLOv8n model missing or truncated at {yolo_cached}"
        )
        det = _FrameDetector()
        assert det.model_type == "onnx", f"Expected ONNX detector, got '{det.model_type}'"
        dummy_frame = np.zeros((360, 640, 3), dtype=np.uint8)
        det.detect(dummy_frame, "person")
        _log("[SELFTEST] Offline YOLOv8n ONNX + ONNXRuntime inference verified")

        # 4. Verify UI, Tkinter >= 8.6, ImageTk, CustomTkinter, GIF search & Trash modules
        import certifi
        import customtkinter  # noqa: F401
        import cv2
        import darkdetect  # noqa: F401
        import ddgs  # noqa: F401
        import PIL.ImageTk  # noqa: F401
        import requests  # noqa: F401
        import send2trash  # noqa: F401
        import tkinter as tk
        import _tkinter  # noqa: F401
        from dmd_gif_converter import DmdMediaProcessor, read_rgb565_stream_header
        from src.ui.app import DMDConverterApp  # noqa: F401

        assert float(tk.TkVersion) >= 8.6, f"Incompatible Tk version {tk.TkVersion} (< 8.6)"
        assert Path(certifi.where()).is_file(), "Bundled certifi CA bundle missing"
        _log(f"[SELFTEST] UI & search stack verified (Tk {tk.TkVersion})")

        # 5. End-to-end conversion test (synthetic MP4 + Auto-Action + text overlay + DMDS)
        with tempfile.TemporaryDirectory(prefix="dmd_selftest_") as tmp:
            tmp_dir = Path(tmp)
            src_mp4 = tmp_dir / "sample.mp4"
            writer = cv2.VideoWriter(
                str(src_mp4), cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (320, 180)
            )
            assert writer.isOpened(), "cv2.VideoWriter failed to open synthetic MP4"
            for idx in range(24):
                frm = np.zeros((180, 320, 3), dtype=np.uint8)
                x0 = (idx * 8) % 240
                cv2.rectangle(frm, (x0, 40), (x0 + 60, 140), (0, 200, 255), -1)
                writer.write(frm)
            writer.release()

            out_gif = tmp_dir / "out.gif"
            params = dict(conv_core.DEFAULT_PARAMS)
            params.update(
                {
                    "target_width": 128,
                    "target_height": 32,
                    "fps": 12,
                    "text_overlay_enabled": True,
                    "text_content": "ARCADE",
                    "text_font_file": "HelvetiPixel.ttf",
                    "verbose": True,
                    "log_level": "DEBUG",
                }
            )
            ok, msg = conv_core.process_file(str(src_mp4), str(out_gif), params)
            assert ok and out_gif.is_file() and out_gif.stat().st_size > 200, (
                f"End-to-end GIF conversion failed: ok={ok}, msg={msg}"
            )

            # Verify Auto-Action AI pipeline (YOLOv8 + TrackingEngine + FFmpegWriter)
            from src.engine.auto_action.pipeline import preprocess_video_for_dmd
            from src.engine.config.auto_action_config import AutoActionConfig

            aa_ok, aa_mp4, aa_msg = preprocess_video_for_dmd(
                str(src_mp4),
                cfg=AutoActionConfig(intro_duration=0.0),
                target_width=128,
                target_height=32,
            )
            assert aa_ok and aa_mp4 and Path(aa_mp4).is_file(), (
                f"Auto-Action pipeline failed in frozen bundle: {aa_msg}"
            )
            try:
                Path(aa_mp4).unlink(missing_ok=True)
            except OSError:
                pass

            from PIL import Image

            art_png = tmp_dir / "art.png"
            Image.fromarray(np.full((240, 320, 3), 180, dtype=np.uint8)).save(art_png)
            pan = DmdMediaProcessor().process_image_panorama(
                art_png, tmp_dir, width=128, height=32, duration_s=1.5, fps=12, stem="pan"
            )
            assert pan.rgb565_stream_path and pan.rgb565_stream_path.is_file()
            hdr = read_rgb565_stream_header(pan.rgb565_stream_path)
            assert hdr["magic"] == "DMDS" and hdr["width"] == 128 and hdr["height"] == 32
        _log("[SELFTEST] End-to-end GIF + Auto-Action AI + text overlay + DMDS stream PASSED")
        rc = 0
    except Exception:
        _log("[SELFTEST] FAILED:\n" + traceback.format_exc())
        rc = 1

    if report_file:
        try:
            Path(report_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
    return rc


def main() -> None:
    multiprocessing.freeze_support()
    if os.environ.get("DMD_STANDALONE_SELFTEST") == "1":
        sys.exit(_run_standalone_selftest())
    from src.ui.app import main as ui_main

    ui_main()


if __name__ == "__main__":
    main()
'''


def _read_app_version() -> str:
    constants_py = ROOT / "src" / "ui" / "constants.py"
    if constants_py.is_file():
        match = re.search(
            r'^APP_VERSION\s*=\s*"v?([^"]+)"',
            constants_py.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1).strip()
    return "8.0.14"


def _detect_arch_tag() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine or "x64"


def _ensure_bundled_yolo_model(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "yolov8n.onnx"
    if target.is_file() and target.stat().st_size >= YOLO_MIN_BYTES:
        return target

    user_cached = Path.home() / ".cache" / "dmd_gif_converter" / "yolov8n.onnx"
    if user_cached.is_file() and user_cached.stat().st_size >= YOLO_MIN_BYTES:
        shutil.copy2(user_cached, target)
        return target

    for attempt in range(1, 4):
        try:
            print(f"[MODEL] Downloading YOLOv8n ONNX model (attempt {attempt}/3) ...")
            req = urllib.request.Request(
                YOLO_MODEL_URL, headers={"User-Agent": "dmd-gif-converter-ci/1.0"}
            )
            with urllib.request.urlopen(req, timeout=90) as resp, target.open("wb") as out:
                shutil.copyfileobj(resp, out)
            if target.is_file() and target.stat().st_size >= YOLO_MIN_BYTES:
                print(
                    f"[MODEL] Ready: {target} "
                    f"({target.stat().st_size / (1024 * 1024):.1f} MB)"
                )
                return target
        except (OSError, urllib.error.URLError) as exc:
            print(f"[MODEL] Attempt {attempt} failed: {exc}")
            time.sleep(2 * attempt)

    raise RuntimeError(
        f"Failed to download valid yolov8n.onnx (>={YOLO_MIN_BYTES} bytes) from {YOLO_MODEL_URL}"
    )


def _render_app_icon_image():
    from PIL import Image, ImageDraw

    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = 64
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=210,
        fill=(13, 15, 28, 255),
        outline=(255, 168, 0, 255),
        width=16,
    )

    # Retro HUB75 12x6 glowing LED matrix motif with filmstrip border & play glyph
    cols, rows = 12, 6
    grid_w, grid_h = 736, 396
    x0 = (size - grid_w) // 2
    y0 = (size - grid_h) // 2
    cell_w = grid_w / cols
    cell_h = grid_h / rows
    dot_r = int(min(cell_w, cell_h) * 0.35)

    border_palette = [
        (56, 189, 248, 255),   # Arcade Cyan
        (255, 168, 0, 255),    # DMD Amber
        (244, 63, 94, 255),    # Neon Magenta
        (46, 204, 113, 255),   # Matrix Emerald
    ]
    play_lit = {
        (4, 1), (4, 2), (4, 3), (4, 4),
        (5, 1), (5, 2), (5, 3), (5, 4),
        (6, 2), (6, 3),
        (7, 2), (7, 3),
    }
    for r in range(rows):
        for c in range(cols):
            cx = int(x0 + (c + 0.5) * cell_w)
            cy = int(y0 + (r + 0.5) * cell_h)
            if (c, r) in play_lit:
                color = (255, 196, 32, 255)
            elif c in (0, cols - 1) and r % 2 == 0:
                color = (56, 189, 248, 255)
            elif r in (0, rows - 1):
                color = border_palette[(c + r) % len(border_palette)]
            else:
                color = (34, 40, 66, 255)
            draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)
    return img


def _generate_windows_ico(dest_ico: Path) -> Path | None:
    try:
        img = _render_app_icon_image()
        dest_ico.parent.mkdir(parents=True, exist_ok=True)
        img.save(
            dest_ico,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        return dest_ico if dest_ico.is_file() else None
    except (ImportError, OSError, ValueError) as exc:
        print(f"[ICON] Warning: could not generate Windows .ico: {exc}")
        return None


def _generate_macos_icns(dest_icns: Path) -> Path | None:
    iconutil = shutil.which("iconutil")
    if not iconutil:
        return None
    try:
        from PIL import Image

        img = _render_app_icon_image()
        with tempfile.TemporaryDirectory(prefix="dmd_icns_") as tmp:
            iconset = Path(tmp) / "AppIcon.iconset"
            iconset.mkdir(parents=True, exist_ok=True)
            specs = [
                ("icon_16x16.png", 16),
                ("icon_16x16@2x.png", 32),
                ("icon_32x32.png", 32),
                ("icon_32x32@2x.png", 64),
                ("icon_128x128.png", 128),
                ("icon_128x128@2x.png", 256),
                ("icon_256x256.png", 256),
                ("icon_256x256@2x.png", 512),
                ("icon_512x512.png", 512),
                ("icon_512x512@2x.png", 1024),
            ]
            for fname, px in specs:
                img.resize((px, px), Image.Resampling.LANCZOS).save(
                    iconset / fname, format="PNG"
                )
            dest_icns.parent.mkdir(parents=True, exist_ok=True)
            res = subprocess.run(
                [iconutil, "-c", "icns", str(iconset), "-o", str(dest_icns)],
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and dest_icns.is_file():
                return dest_icns
    except (ImportError, OSError, ValueError) as exc:
        print(f"[ICON] Warning: could not generate macOS .icns: {exc}")
    return None


def _write_windows_version_info(dest_txt: Path, app_ver: str, exe_name: str) -> Path:
    nums = [int(x) for x in re.findall(r"\d+", app_ver)[:4]]
    while len(nums) < 4:
        nums.append(0)
    ver_tuple = tuple(nums[:4])
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'ArcadeMatrix'),
        StringStruct('FileDescription', 'DMD GIF Converter — Standalone Desktop UI'),
        StringStruct('FileVersion', '{app_ver}'),
        StringStruct('InternalName', 'DMD_GIF_Converter'),
        StringStruct('LegalCopyright', 'MIT License — red77290'),
        StringStruct('OriginalFilename', '{exe_name}'),
        StringStruct('ProductName', 'DMD GIF Converter'),
        StringStruct('ProductVersion', '{app_ver}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    dest_txt.write_text(content, encoding="utf-8")
    return dest_txt


def _discover_project_modules() -> list[str]:
    modules: list[str] = ["dmd_gif_converter"]
    for py_file in sorted((ROOT / "src").rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        rel = py_file.relative_to(ROOT).with_suffix("")
        mod_name = ".".join(rel.parts).removesuffix(".__init__")
        if mod_name == "src.engine.auto_action.cli":
            continue
        modules.append(mod_name)
    return modules


def _prepare_common_pyinstaller_args(
    name: str,
    work_dir: Path,
    dist_dir: Path,
) -> tuple[list[str], Path]:
    sep = ";" if sys.platform == "win32" else ":"
    work_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    rthook_path = work_dir / "rthook_dmd_portable.py"
    rthook_path.write_text(RUNTIME_HOOK_CODE, encoding="utf-8")

    entry_path = work_dir / "desktop_ui_entry.py"
    entry_path.write_text(ENTRYPOINT_CODE, encoding="utf-8")

    yolo_path = _ensure_bundled_yolo_model(work_dir / "models_staging")
    fonts_dir = ROOT / "media" / "fonts"
    if not fonts_dir.is_dir():
        raise RuntimeError(f"Expected fonts directory missing: {fonts_dir}")

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if not ffmpeg_path or not ffprobe_path:
        raise RuntimeError(
            "Both 'ffmpeg' and 'ffprobe' must be available in PATH during build"
        )

    args: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        name,
        "--workpath",
        str(work_dir / "pyi_work"),
        "--specpath",
        str(work_dir / "pyi_spec"),
        "--distpath",
        str(dist_dir),
        "--paths",
        str(ROOT),
        "--runtime-hook",
        str(rthook_path),
        # Bundle pixel-art fonts for both core.py and pillow_overlay.py relative lookups
        "--add-data",
        f"{fonts_dir}{sep}media/fonts",
        "--add-data",
        f"{fonts_dir}{sep}src/media/fonts",
        # Bundle YOLOv8n ONNX model for 100% offline out-of-the-box Auto-Action
        "--add-data",
        f"{yolo_path}{sep}models",
        # Collect GUI, AI, search, and SSL packages + data assets
        "--collect-all",
        "customtkinter",
        "--collect-submodules",
        "darkdetect",
        "--hidden-import",
        "send2trash",
        "--collect-data",
        "ddgs",
        "--collect-submodules",
        "ddgs.engines",
        "--exclude-module",
        "ddgs.api_server",
        "--collect-all",
        "primp",
        "--collect-submodules",
        "lxml",
        "--collect-data",
        "certifi",
        "--collect-binaries",
        "onnxruntime",
        "--copy-metadata",
        "onnxruntime",
        "--hidden-import",
        "onnxruntime",
        "--exclude-module",
        "onnxruntime.tools",
        "--exclude-module",
        "onnxruntime.transformers",
        "--exclude-module",
        "onnxruntime.quantization",
        "--hidden-import",
        "PIL._tkinter_finder",
        "--hidden-import",
        "PIL.ImageTk",
        # Exclude dev/test frameworks to keep bundle clean and fast
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "_pytest",
        "--exclude-module",
        "ruff",
    ]

    # On Windows/Linux (--onefile), bundle static ffmpeg/ffprobe via --add-binary;
    # on macOS (.app), bundle into isolated Contents/Resources/ffmpeg_bin/lib to avoid
    # dylib filename collisions with Pillow / OpenCV inside Contents/Frameworks/.
    if sys.platform != "darwin":
        args += [
            "--add-binary",
            f"{Path(ffmpeg_path).resolve()}{sep}bin",
            "--add-binary",
            f"{Path(ffprobe_path).resolve()}{sep}bin",
        ]

    if sys.platform == "win32":
        args += ["--collect-submodules", "send2trash.win"]
    elif sys.platform == "darwin":
        args += ["--collect-submodules", "send2trash.mac"]

    for mod in _discover_project_modules():
        args += ["--hidden-import", mod]

    return args, entry_path


def _otool_deps(macho_file: Path) -> list[str]:
    res = subprocess.run(
        ["otool", "-L", str(macho_file)], capture_output=True, text=True, check=False
    )
    if res.returncode != 0:
        return []
    deps: list[str] = []
    for line in res.stdout.splitlines()[1:]:
        part = line.strip().split(" (", 1)[0].strip()
        if part:
            deps.append(part)
    return deps


def _bundle_and_audit_macos_ffmpeg(app_bundle: Path) -> None:
    """
    Copy `ffmpeg` + `ffprobe` into `Contents/Resources/ffmpeg_bin/` and relocate all of
    their Homebrew `.dylib` dependencies into a private `Contents/Resources/ffmpeg_bin/lib/`
    folder (100% isolated from Pillow/OpenCV `.dylib`s in `Contents/Frameworks/`), then
    audit the entire `.app` for zero `/opt/homebrew` or `/usr/local` dylib leaks.
    """
    ff_bin_dir = app_bundle / "Contents" / "Resources" / "ffmpeg_bin"
    ff_lib_dir = ff_bin_dir / "lib"
    ff_lib_dir.mkdir(parents=True, exist_ok=True)

    external_prefixes = (
        "/opt/homebrew/",
        "/usr/local/opt/",
        "/usr/local/Cellar/",
        "/usr/local/lib/",
    )

    for tool in ("ffmpeg", "ffprobe"):
        found = shutil.which(tool)
        if not found:
            raise RuntimeError(f"macOS build missing '{tool}' in PATH")
        dst_tool = ff_bin_dir / tool
        shutil.copy2(Path(found).resolve(), dst_tool)
        dst_tool.chmod(0o755)

    # Relocate private FFmpeg dylib closure inside Contents/Resources/ffmpeg_bin/lib/
    for _pass in range(12):
        progressed = False
        ff_targets = [
            ff_bin_dir / "ffmpeg",
            ff_bin_dir / "ffprobe",
            *sorted(ff_lib_dir.glob("*.dylib")),
        ]
        for target in ff_targets:
            deps = _otool_deps(target)
            if not deps:
                continue
            is_exe = target.parent == ff_bin_dir
            loader_prefix = "@loader_path/lib" if is_exe else "@loader_path"
            for dep in deps:
                if not dep.startswith(external_prefixes):
                    continue
                src_dylib = Path(dep).resolve()
                if not src_dylib.is_file():
                    raise RuntimeError(
                        f"Missing external dylib '{dep}' referenced by {target}"
                    )
                bundled_dylib = ff_lib_dir / src_dylib.name
                if not bundled_dylib.exists():
                    shutil.copy2(src_dylib, bundled_dylib)
                    bundled_dylib.chmod(0o755)
                    subprocess.run(
                        [
                            "install_name_tool",
                            "-id",
                            f"@loader_path/{bundled_dylib.name}",
                            str(bundled_dylib),
                        ],
                        check=True,
                    )
                    progressed = True

                new_ref = f"{loader_prefix}/{bundled_dylib.name}"
                if dep != new_ref:
                    target.chmod(target.stat().st_mode | stat.S_IWUSR)
                    subprocess.run(
                        ["install_name_tool", "-change", dep, new_ref, str(target)],
                        check=True,
                    )
                    progressed = True
        if not progressed:
            break

    # Audit the entire .app bundle (both Contents/Frameworks and Contents/Resources/ffmpeg_bin)
    leaks: list[str] = []
    macho_count = 0
    for target in app_bundle.rglob("*"):
        if target.is_symlink() or not target.is_file():
            continue
        if target.suffix in (".dylib", ".so") or target.parent.name in ("MacOS", "ffmpeg_bin"):
            deps = _otool_deps(target)
            if deps:
                macho_count += 1
            for dep in deps:
                if dep.startswith(external_prefixes):
                    leaks.append(f"{target.relative_to(app_bundle)} -> {dep}")
    if leaks:
        raise RuntimeError(
            "Unrelocated Homebrew / usr-local dylib references detected:\n  "
            + "\n  ".join(leaks[:15])
        )
    print(
        f"[MACOS] Bundled isolated FFmpeg ({len(list(ff_lib_dir.glob('*.dylib')))} dylibs) "
        f"& audited {macho_count} Mach-O files: 0 external leaks."
    )


def _sign_macos_app_bundle(app_bundle: Path, signing_identity: str) -> None:
    base_sign = ["codesign", "--force"]
    if signing_identity != "-":
        base_sign += ["--options", "runtime", "--timestamp"]

    print(
        f"[MACOS] Signing {app_bundle.name} inside-out "
        f"(identity={'Developer ID' if signing_identity != '-' else 'ad-hoc'}) ..."
    )
    ff_bin_dir = app_bundle / "Contents" / "Resources" / "ffmpeg_bin"
    if ff_bin_dir.is_dir():
        for dylib in sorted((ff_bin_dir / "lib").glob("*.dylib")):
            subprocess.run([*base_sign, "--sign", signing_identity, str(dylib)], check=True)
        for tool in ("ffmpeg", "ffprobe"):
            tp = ff_bin_dir / tool
            if tp.is_file():
                subprocess.run([*base_sign, "--sign", signing_identity, str(tp)], check=True)

    fw_dir = app_bundle / "Contents" / "Frameworks"
    if fw_dir.is_dir():
        for item in sorted(fw_dir.rglob("*")):
            if item.is_symlink() or not item.is_file():
                continue
            if item.suffix in (".dylib", ".so"):
                subprocess.run([*base_sign, "--sign", signing_identity, str(item)], check=True)

    subprocess.run(
        [*base_sign, "--deep", "--sign", signing_identity, str(app_bundle)], check=True
    )
    subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app_bundle)], check=True
    )


def _create_and_notarize_macos_dmg(
    app_bundle: Path, dmg_path: Path, signing_identity: str
) -> None:
    if dmg_path.exists():
        dmg_path.unlink()
    dmg_path.parent.mkdir(parents=True, exist_ok=True)

    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            subprocess.run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    "DMD GIF Converter",
                    "-fs",
                    "HFS+",
                    "-srcfolder",
                    str(app_bundle.parent),
                    "-ov",
                    "-format",
                    "UDZO",
                    str(dmg_path),
                ],
                check=True,
            )
            last_err = None
            break
        except subprocess.CalledProcessError as exc:
            last_err = exc
            print(f"[MACOS] hdiutil attempt {attempt}/3 transient error, retrying ...")
            time.sleep(3 * attempt)
    if last_err is not None:
        raise last_err

    subprocess.run(
        ["codesign", "--force", "--sign", signing_identity, str(dmg_path)], check=True
    )

    apple_id = (os.environ.get("APPLE_ID") or "").strip()
    team_id = (os.environ.get("APPLE_TEAM_ID") or "").strip()
    app_pw = (os.environ.get("APPLE_APP_SPECIFIC_PASSWORD") or "").strip()
    if signing_identity != "-" and apple_id and team_id and app_pw:
        print(f"[MACOS] Submitting {dmg_path.name} to Apple Notary Service ...")
        subprocess.run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(dmg_path),
                "--apple-id",
                apple_id,
                "--team-id",
                team_id,
                "--password",
                app_pw,
                "--wait",
            ],
            check=True,
        )
        subprocess.run(["xcrun", "stapler", "staple", str(dmg_path)], check=True)


def _run_hermetic_selftest(executable_path: Path) -> None:
    """
    Execute the built standalone binary in an isolated environment with stripped PATH
    (no system Python, no system FFmpeg) and empty HOME cache to prove out-of-the-box
    functionality.
    """
    print(f"[SELFTEST] Running hermetic out-of-the-box check on: {executable_path}")
    with tempfile.TemporaryDirectory(prefix="dmd_hermetic_home_") as clean_home:
        report_path = Path(clean_home) / "selftest_report.txt"
        env = dict(os.environ)
        env["DMD_STANDALONE_SELFTEST"] = "1"
        env["DMD_SELFTEST_REPORT_FILE"] = str(report_path)
        env["HOME"] = clean_home
        if sys.platform == "win32":
            sys_root = os.environ.get("SystemRoot", r"C:\Windows")
            env["PATH"] = f"{sys_root}\\System32;{sys_root}"
            env["USERPROFILE"] = clean_home
            env["APPDATA"] = str(Path(clean_home) / "AppData" / "Roaming")
            env["LOCALAPPDATA"] = str(Path(clean_home) / "AppData" / "Local")
        else:
            env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"

        res = subprocess.run(
            [str(executable_path)],
            env=env,
            cwd=clean_home,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        report_txt = (
            report_path.read_text(encoding="utf-8")
            if report_path.is_file()
            else (res.stdout + "\n" + res.stderr)
        )
        print(report_txt.strip())
        if res.returncode != 0:
            raise RuntimeError(
                f"Standalone self-test failed with exit code {res.returncode}"
            )
    print("[SELFTEST] Hermetic out-of-the-box verification PASSED.")


def _build_windows_exe(run_selftest: bool) -> Path:
    app_ver = _read_app_version()
    arch = _detect_arch_tag()
    exe_stem = f"DMD_GIF_Converter_Windows_{arch}"
    exe_name = f"{exe_stem}.exe"

    pyi_cmd, entry_path = _prepare_common_pyinstaller_args(
        exe_stem, BUILD_DESKTOP_DIR, DIST_DESKTOP_DIR
    )
    pyi_cmd += ["--onefile", "--windowed"]

    ico_path = _generate_windows_ico(BUILD_DESKTOP_DIR / "AppIcon.ico")
    if ico_path:
        pyi_cmd += ["--icon", str(ico_path)]

    ver_file = _write_windows_version_info(
        BUILD_DESKTOP_DIR / "version_info.txt", app_ver, exe_name
    )
    pyi_cmd += ["--version-file", str(ver_file)]

    # Bundle MSVC C++ runtime DLLs so fresh Windows installs need zero redistributables
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for dll_name in (
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "concrt140.dll",
        "vcomp140.dll",
    ):
        cand = sys32 / dll_name
        if cand.is_file():
            pyi_cmd += ["--add-binary", f"{cand};."]

    pyi_cmd.append(str(entry_path))
    print(f"[WINDOWS] Building standalone {exe_name} (v{app_ver}) ...")
    subprocess.run(pyi_cmd, cwd=str(ROOT), check=True)

    exe_path = DIST_DESKTOP_DIR / exe_name
    if not exe_path.is_file():
        raise RuntimeError(f"Expected Windows executable was not created: {exe_path}")

    if run_selftest:
        _run_hermetic_selftest(exe_path)

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"[WINDOWS] Ready: {exe_path} ({size_mb:.1f} MB)")
    return exe_path


def _build_macos_dmg(run_selftest: bool) -> Path:
    import tkinter as tk

    if float(tk.TkVersion) < 8.6:
        raise RuntimeError(
            f"macOS build Python uses Tcl/Tk {tk.TkVersion} (< 8.6), which crashes on modern macOS"
        )

    app_ver = _read_app_version()
    arch = _detect_arch_tag()
    app_name = "DMD GIF Converter"
    pyi_dist = BUILD_DESKTOP_DIR / "macos_dist"
    if pyi_dist.exists():
        shutil.rmtree(pyi_dist)

    pyi_cmd, entry_path = _prepare_common_pyinstaller_args(
        app_name, BUILD_DESKTOP_DIR, pyi_dist
    )
    pyi_cmd += [
        "--onedir",
        "--windowed",
        "--osx-bundle-identifier",
        "com.arcadematrix.dmdgifconverter",
    ]

    icns_path = _generate_macos_icns(BUILD_DESKTOP_DIR / "AppIcon.icns")
    if icns_path:
        pyi_cmd += ["--icon", str(icns_path)]

    pyi_cmd.append(str(entry_path))
    print(f"[MACOS] Building '{app_name}.app' ({arch}, v{app_ver}) ...")
    subprocess.run(pyi_cmd, cwd=str(ROOT), check=True)

    raw_app = pyi_dist / f"{app_name}.app"
    if not raw_app.is_dir():
        raise RuntimeError(f"Expected macOS .app bundle missing: {raw_app}")

    staging_dir = BUILD_DESKTOP_DIR / "dmg_staging"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)

    final_app = staging_dir / f"{app_name}.app"
    shutil.move(str(raw_app), str(final_app))

    plist_path = final_app / "Contents" / "Info.plist"
    with plist_path.open("rb") as fp:
        plist_data = plistlib.load(fp)
    plist_data["CFBundleName"] = app_name
    plist_data["CFBundleDisplayName"] = app_name
    plist_data["CFBundleIdentifier"] = "com.arcadematrix.dmdgifconverter"
    plist_data["CFBundleShortVersionString"] = app_ver
    plist_data["CFBundleVersion"] = app_ver
    plist_data["LSMinimumSystemVersion"] = "12.0"
    plist_data["NSHighResolutionCapable"] = True
    if icns_path:
        shutil.copy2(icns_path, final_app / "Contents" / "Resources" / "AppIcon.icns")
        plist_data["CFBundleIconFile"] = "AppIcon"
    with plist_path.open("wb") as fp:
        plistlib.dump(plist_data, fp)

    _bundle_and_audit_macos_ffmpeg(final_app)

    signing_identity = (os.environ.get("APPLE_SIGNING_IDENTITY") or "").strip() or "-"
    _sign_macos_app_bundle(final_app, signing_identity)

    if run_selftest:
        macos_bin = final_app / "Contents" / "MacOS" / app_name
        _run_hermetic_selftest(macos_bin)

    os.symlink("/Applications", staging_dir / "Applications")
    dmg_path = DIST_DESKTOP_DIR / f"DMD_GIF_Converter_macOS_{arch}.dmg"
    _create_and_notarize_macos_dmg(final_app, dmg_path, signing_identity)

    shutil.rmtree(staging_dir, ignore_errors=True)
    size_mb = dmg_path.stat().st_size / (1024 * 1024)
    print(f"[MACOS] Ready: {dmg_path} ({size_mb:.1f} MB)")
    return dmg_path


def _build_linux_binary(run_selftest: bool) -> Path:
    """Local Linux verification target exercising the exact same `--onefile` bundle."""
    app_ver = _read_app_version()
    arch = _detect_arch_tag()
    bin_name = f"DMD_GIF_Converter_Linux_{arch}"
    pyi_cmd, entry_path = _prepare_common_pyinstaller_args(
        bin_name, BUILD_DESKTOP_DIR, DIST_DESKTOP_DIR
    )
    pyi_cmd += ["--onefile", str(entry_path)]
    print(f"[LINUX] Building standalone {bin_name} (v{app_ver}) ...")
    subprocess.run(pyi_cmd, cwd=str(ROOT), check=True)

    bin_path = DIST_DESKTOP_DIR / bin_name
    if run_selftest:
        _run_hermetic_selftest(bin_path)

    size_mb = bin_path.stat().st_size / (1024 * 1024)
    print(f"[LINUX] Ready: {bin_path} ({size_mb:.1f} MB)")
    return bin_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build standalone out-of-the-box Desktop UI (.exe / .dmg)."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run hermetic stripped-PATH out-of-the-box verification on the built binary.",
    )
    args = parser.parse_args()

    if BUILD_DESKTOP_DIR.exists():
        shutil.rmtree(BUILD_DESKTOP_DIR)
    DIST_DESKTOP_DIR.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        _build_windows_exe(args.self_test)
    elif sys.platform == "darwin":
        _build_macos_dmg(args.self_test)
    else:
        _build_linux_binary(args.self_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
