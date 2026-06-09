import os
import re
import sys
import glob
import logging
import shutil
import threading
import tempfile
import subprocess
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox

from src.converter.core import (
    get_metadata, process_file, process_folder,
    DEFAULT_PARAMS, SUPPORTED_EXTENSIONS,
)
from src.auto_action.main import AutoActionConfig, preprocess_video_for_dmd
from src.converter.colorimetry import analyze_and_compensate as _ui_analyze_color
from src.ui.widgets import _InfoBadge
from src.ui.constants import *
import os
import glob
import logging
import shutil
import tempfile
import threading
from pathlib import Path
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk
from src.ui.dmd_led_sim import LED_SIM_SCALE, LED_SIM_GAP, LED_SIM_MAX_W, apply_led_grid as _apply_led_grid

class PreviewPanelMixin:
    def _build_preview_area(self, parent):
        pf = ctk.CTkFrame(parent)
        pf.grid(row=0, column=0, padx=4, pady=(4, 2), sticky="ew")
        pf.grid_columnconfigure(0, weight=1)

        # Title row
        tr = ctk.CTkFrame(pf, fg_color="transparent")
        tr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))
        tr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            tr, text="🖥️  Preview  —  SOURCE → AUTO ACTION → DMD",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, sticky="w")

        pb = ctk.CTkFrame(tr, fg_color="transparent")
        pb.grid(row=0, column=1, sticky="e")
        self._btn_all_prev = ctk.CTkButton(
            pb, text="🔄 Refresh All", width=120, height=28,
            command=self.refresh_all_previews
        )
        self._btn_all_prev.pack(side="left", padx=3)
        self._btn_src = ctk.CTkButton(
            pb, text="▶ Source", width=92, height=28,
            command=self.show_source_preview
        )
        self._btn_src.pack(side="left", padx=3)
        self._btn_auto = ctk.CTkButton(
            pb, text="🎯 Auto", width=92, height=28,
            fg_color="#2b4b8a", hover_color="#234073",
            command=self.show_auto_preview
        )
        self._btn_auto.pack(side="left", padx=3)
        self._btn_dmd = ctk.CTkButton(
            pb, text="🔬 DMD", width=92, height=28,
            fg_color="#1e6a3c", hover_color="#155230",
            command=self.show_dmd_preview
        )
        self._btn_dmd.pack(side="left", padx=3)

        self._btn_led_sim = ctk.CTkButton(
            pb, text="💡 LED Sim  ✓", width=96, height=28,
            fg_color="#5a4a00", hover_color="#7a6400",
            command=self._toggle_led_sim
        )
        self._btn_led_sim.pack(side="left", padx=3)

        # Preview container
        dc = ctk.CTkFrame(pf, fg_color="transparent")
        dc.grid(row=1, column=0, padx=6, pady=4, sticky="nsew")
        dc.grid_columnconfigure((0, 1), weight=1)

        # Source canvas (top left)
        src_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        src_wrap.grid(row=0, column=0, padx=(0, 4), pady=4, sticky="ne")
        ctk.CTkLabel(
            src_wrap, text="SOURCE",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#556677"
        ).pack(pady=(4, 0))
        self._src_canvas = tk.Canvas(
            src_wrap, width=SRC_CANVAS_W, height=SRC_CANVAS_H,
            bg=BG_CANVAS, highlightthickness=0
        )
        self._src_canvas.pack(padx=2, pady=(2, 2))
        self._src_info = _InfoBadge(src_wrap, width=SRC_CANVAS_W)
        self._src_info.pack(pady=(0, 4))

        # Auto-action canvas (top right)
        auto_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        auto_wrap.grid(row=0, column=1, padx=(4, 0), pady=4, sticky="nw")
        ctk.CTkLabel(
            auto_wrap, text="AUTO ACTION",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#4f7bd9"
        ).pack(pady=(4, 0))
        self._auto_canvas = tk.Canvas(
            auto_wrap, width=AUTO_CANVAS_W, height=AUTO_CANVAS_H,
            bg=BG_CANVAS, highlightthickness=0
        )
        self._auto_canvas.pack(padx=2, pady=(2, 2))
        self._auto_info = _InfoBadge(auto_wrap, width=AUTO_CANVAS_W)
        self._auto_info.pack(pady=(0, 4))

        # DMD canvas (bottom center)
        dmd_wrap = ctk.CTkFrame(dc, fg_color=BG_CANVAS, corner_radius=6)
        dmd_wrap.grid(row=1, column=0, columnspan=2, padx=4, pady=(8, 4), sticky="n")
        self._dmd_title_label = ctk.CTkLabel(
            dmd_wrap,
            text=f"DMD OUTPUT {DEFAULT_PARAMS['target_width']}×{DEFAULT_PARAMS['target_height']}",
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#2e7a4a"
        )
        self._dmd_title_label.pack(pady=(4, 0))
        # Initialize with default dimensions, will be updated dynamically
        self._dmd_canvas = tk.Canvas(
            dmd_wrap, width=int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR),
            height=int(DEFAULT_PARAMS["target_height"] * DMD_DISPLAY_SCALE_FACTOR),
            bg=BG_CANVAS, highlightthickness=0
        )
        self._dmd_canvas.pack(padx=2, pady=(2, 2))
        self._dmd_info = _InfoBadge(
            dmd_wrap,
            width=int(DEFAULT_PARAMS["target_width"] * DMD_DISPLAY_SCALE_FACTOR),
        )
        self._dmd_info.pack(pady=(0, 4))

        # Backward-compat aliases
        self._canvas       = self._src_canvas
        self._preview_info = self._src_info

        # Keep canvas size + title label in sync with dimension vars (including Custom mode)
        self.v_target_width.trace_add("write",  self._update_dmd_canvas_size)
        self.v_target_height.trace_add("write", self._update_dmd_canvas_size)

        self._draw_canvas_idle()
        self._draw_auto_canvas_idle()
        self._draw_dmd_canvas_idle()

        # Trim controls
        self._trim_frame = ctk.CTkFrame(pf, fg_color="#16213e")
        self._trim_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self._trim_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self._trim_frame, text="✂️  Trim  (single-file conversion only)",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#7ec8e3"
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(8, 4), sticky="w")

        ctk.CTkLabel(self._trim_frame, text="Start", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=(10, 4), pady=2)
        self._sl_start = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_start,
            command=self._on_start_drag
        )
        self._sl_start.grid(row=1, column=1, sticky="ew", padx=4)
        self._lbl_start = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                        font=ctk.CTkFont(size=11))
        self._lbl_start.grid(row=1, column=2, padx=4)

        ctk.CTkLabel(self._trim_frame, text="End", width=44,
                     font=ctk.CTkFont(size=11)).grid(row=2, column=0, padx=(10, 4), pady=2)
        self._sl_end = ctk.CTkSlider(
            self._trim_frame, from_=0, to=1, variable=self.v_trim_end,
            command=self._on_end_drag
        )
        self._sl_end.grid(row=2, column=1, sticky="ew", padx=4, pady=(2, 8))
        self._lbl_end = ctk.CTkLabel(self._trim_frame, text="0.0 s", width=54,
                                      font=ctk.CTkFont(size=11))
        self._lbl_end.grid(row=2, column=2, padx=4)

        ctk.CTkButton(
            self._trim_frame, text="↺ Reset", command=self._reset_trim,
            width=70, height=24, fg_color="transparent", border_width=1
        ).grid(row=1, column=3, rowspan=2, padx=(4, 10))

        self._trim_frame.grid_remove()

        # Diagnosis info for converted files
        self._diagnosis_frame = ctk.CTkFrame(pf, fg_color="#1a1a2e", corner_radius=6)
        self._diagnosis_frame.grid(row=3, column=0, sticky="ew", padx=10, pady=(4, 8))
        self._diagnosis_frame.grid_columnconfigure(1, weight=1)
        
        self._lbl_score = ctk.CTkLabel(self._diagnosis_frame, text="", font=ctk.CTkFont(size=18, weight="bold"))
        self._lbl_score.grid(row=0, column=0, padx=12, pady=10)
        self._lbl_reasons = ctk.CTkLabel(self._diagnosis_frame, text="", justify="left", anchor="w")
        self._lbl_reasons.grid(row=0, column=1, sticky="w", padx=10)
        self._diagnosis_frame.grid_remove()

    # ── Bottom : params + actions ─────────────────────────────────────────────
    def _compute_led_sim_display_size(self):
        """Return (display_w, display_h, scale) for LED sim mode, clamped to LED_SIM_MAX_W."""
        try:
            w = self.v_target_width.get()
            h = self.v_target_height.get()
        except Exception:
            w, h = 128, 32
        scale = LED_SIM_SCALE
        while w * scale > LED_SIM_MAX_W and scale > 2:
            scale -= 1
        return w * scale, h * scale, scale

    def _get_final_canvas_size(self):
        try:
            w = self.v_target_width.get()
            h = self.v_target_height.get()
        except Exception:
            w, h = 128, 32
            
        if getattr(self, "v_led_sim", None) and self.v_led_sim.get():
            display_w, display_h, _ = self._compute_led_sim_display_size()
        else:
            display_w = int(w * DMD_DISPLAY_SCALE_FACTOR)
            display_h = int(h * DMD_DISPLAY_SCALE_FACTOR)
            
        # Clamp to max dimensions to prevent UI pushing
        MAX_W, MAX_H = 640, 360
        if display_w > MAX_W or display_h > MAX_H:
            scale = min(MAX_W / display_w, MAX_H / display_h)
            display_w = int(display_w * scale)
            display_h = int(display_h * scale)
            
        return display_w, display_h

    def _update_dmd_canvas_size(self, *_):
        try:
            w = self.v_target_width.get()
            h = self.v_target_height.get()
        except Exception:
            return
            
        new_width, new_height = self._get_final_canvas_size()
        self._dmd_canvas.configure(width=new_width, height=new_height)
        # Update the title label to reflect the current output dimensions
        if hasattr(self, "_dmd_title_label"):
            sim_badge = "  💡" if (getattr(self, "v_led_sim", None) and self.v_led_sim.get()) else ""
            self._dmd_title_label.configure(text=f"DMD OUTPUT {w}×{h}{sim_badge}")
        # Re-center the idle text if it's showing
        if not self._dmd_frames and not self._dmd_rendering:
            self._draw_dmd_canvas_idle()


    def _draw_canvas_idle(self):
        self._src_canvas.delete("all")
        self._src_canvas.create_text(
            SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
            text="← Select a file to preview",
            fill="#445566", font=("Helvetica", 12)
        )
        if hasattr(self, "_src_info"):
            self._src_info.configure(text="")
        if hasattr(self, "_btn_convert"):
            self._btn_convert.configure(state="disabled")

    def _draw_dmd_canvas_idle(self):
        self._dmd_canvas.delete("all")
        # Use current target dimensions for idle text positioning
        try:
            current_dmd_width, current_dmd_height = self._get_final_canvas_size()
        except Exception:
            current_dmd_width = int(128 * DMD_DISPLAY_SCALE_FACTOR)
            current_dmd_height = int(32 * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(
            current_dmd_width // 2, current_dmd_height // 2,
            text="← Select a file then\n  click 🔬 Refresh DMD",
            fill="#334455", font=("Helvetica", 11), justify="center"
        )
        if hasattr(self, "_dmd_info"):
            self._dmd_info.configure(text="")

    def _draw_auto_canvas_idle(self):
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="Auto action preview\n(disabled by default)",
            fill="#334466", font=("Helvetica", 11), justify="center"
        )
        if hasattr(self, "_auto_info"):
            self._auto_info.configure(text="")

    def _stop_src_preview(self):
        if self._src_job:
            self.after_cancel(self._src_job)
            self._src_job = None
        self._src_pil_frames.clear()
        self._src_frames.clear()
        self._src_delays.clear()
        self._src_idx = 0
        if self._src_tmpdir and os.path.isdir(self._src_tmpdir):
            shutil.rmtree(self._src_tmpdir, ignore_errors=True)
            self._src_tmpdir = None

    def _stop_auto_preview(self):
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None
        self._auto_pil_frames.clear()
        self._auto_frames.clear()
        self._auto_delays.clear()
        self._auto_idx = 0
        if self._auto_tmpdir and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None

    # Backward-compat alias
    def _stop_preview(self):
        self._stop_src_preview()

    def _load_preview(self, file_path, is_converted=False, converted_data=None):
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        self._src_canvas.delete("all")
        self._auto_canvas.delete("all")
        self._dmd_canvas.delete("all")
        
        self._src_canvas.create_text(
            SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
            text="⏳  Loading preview…",
            fill="#7ec8e3", font=("Helvetica", 12)
        )
        w, h, fps, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self._update_trim_sliders()
        
        if is_converted:
            self._trim_frame.grid_remove()
            self._diagnosis_frame.grid()
            
            if converted_data:
                score = converted_data.get("score", 0)
                color = converted_data.get("color", "")
                rating = converted_data.get("rating", "")
                reasons = converted_data.get("reasons", [])
                self._lbl_score.configure(text=f"{score}%\n{rating}", text_color=color if color and "#" in color else "#ffffff")
                self._lbl_reasons.configure(text=" • " + "\n • ".join(reasons) if reasons else "No specific reasons.")
            
            # For converted files, just load it into DMD preview
            # We don't generate source/auto because it's already a DMD GIF
            self._start_dmd_generation(file_path, is_already_converted=True)
            self._draw_canvas_idle()
            self._draw_auto_canvas_idle()
        else:
            self._trim_frame.grid()
            self._diagnosis_frame.grid_remove()
            threading.Thread(
                target=self._extract_source_frames,
                args=(file_path,), daemon=True
            ).start()
            self._start_auto_generation(file_path)
            self._start_dmd_generation(file_path)

    def _extract_source_frames(self, file_path):
        tmpdir = tempfile.mkdtemp(prefix="dmd_src_")
        fps_prev = 12.5
        dur = min(self._source_duration, 10.0)
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-t", str(dur),
            "-vf", (
                f"fps={fps_prev},"
                f"scale={SRC_CANVAS_W}:{SRC_CANVAS_H}:"
                f"force_original_aspect_ratio=decrease,"
                f"pad={SRC_CANVAS_W}:{SRC_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                f":color={BG_CANVAS[1:]}"
            ),
            "-f", "image2", os.path.join(tmpdir, "f%04d.png")
        ]
        subprocess.run(cmd, capture_output=True)
        paths = sorted(glob.glob(os.path.join(tmpdir, "f*.png")))
        # Decode as plain PIL Images — PhotoImage must be created on the main thread
        pil_frames, delays = [], []
        delay_ms = int(1000 / fps_prev)
        for fp in paths:
            try:
                pil_frames.append(Image.open(fp).convert("RGB").copy())
                delays.append(delay_ms)
            except Exception:
                pass
        self.after(0, lambda: self._on_source_frames_ready(pil_frames, delays, tmpdir, file_path))

    def _on_source_frames_ready(self, pil_frames, delays, tmpdir, file_path):
        if not pil_frames:
            self._src_canvas.delete("all")
            self._src_canvas.create_text(
                SRC_CANVAS_W // 2, SRC_CANVAS_H // 2,
                text="⚠️  Preview unavailable\n(ffmpeg missing?)",
                fill="#e74c3c", font=("Helvetica", 11), justify="center"
            )
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._src_tmpdir = tmpdir
        self._src_pil_frames = pil_frames
        self._src_frames = [None] * len(pil_frames)   # lazy PhotoImage cache
        self._src_delays = delays
        self._src_idx    = 0
        name = Path(file_path).name
        self._src_info.configure(
            text=f"{name}   ·   {len(pil_frames)} frames   ·   {self._source_duration:.1f} s"
        )
        self._animate_src()

    def _animate_src(self):
        if not self._src_pil_frames:
            return
        num_frames = len(self._src_pil_frames)
        idx = self._src_idx % (num_frames + 1)
        
        if idx == num_frames:
            self._src_canvas.delete("all")
            self._src_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
            self._src_idx += 1
            self._src_job = self.after(1000, self._animate_src)
            return
            
        # Lazy PhotoImage creation — one frame at a time on the main thread
        if self._src_frames[idx] is None:
            self._src_frames[idx] = ImageTk.PhotoImage(self._src_pil_frames[idx])
        self._src_canvas.delete("all")
        self._src_canvas.create_image(0, 0, anchor="nw", image=self._src_frames[idx])
        self._src_idx += 1
        delay = self._src_delays[idx] if self._src_delays else 80
        self._src_job = self.after(delay, self._animate_src)

    def show_source_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._load_preview(src)

    def refresh_all_previews(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        path = self._file_data.get(self._selected_iid)
        if not path:
            return
        self._load_preview(path)
        self._start_auto_generation(path)
        self._start_dmd_generation(path)

    def show_auto_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._start_auto_generation(src)

    def _start_auto_generation(self, src):
        if self._auto_rendering:
            # Queue the latest request — will start once the current render finishes
            self._auto_pending_src = src
            return
        if not self.v_auto_action_enabled.get():
            self._stop_auto_preview()
            self._draw_auto_canvas_idle()
            self._auto_info.configure(text="Auto action disabled")
            return
        if preprocess_video_for_dmd is None or AutoActionConfig is None:
            self._draw_auto_canvas_idle()
            self._auto_info.configure(text="Auto action unavailable (module missing)")
            return

        self._auto_pending_src = None
        self._auto_rendering = True
        self._stop_auto_preview()
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="⏳  Generating auto-action preview…",
            fill="#7aa2ff", font=("Helvetica", 11), justify="center"
        )
        self._btn_auto.configure(state="disabled", text="⏳ Auto…")

        start_s, end_s = self._get_trim()
        cfg = AutoActionConfig(
            detector=self.v_action_detector.get(),
            strength=float(self.v_action_strength.get()),
            smoothness=float(self.v_action_smoothness.get()),
            zoom_max=float(self.v_action_zoom_max.get()),
            padding=float(self.v_action_padding.get()),
            intro_duration=float(self.v_action_intro.get()),
            bg_sub_enable=self.v_bg_sub_enable.get(),
            bottom_crop_pct=float(self.v_action_bottom_crop.get()),
            auto_bottom_crop=bool(self.v_action_auto_bottom_crop.get()),
            top_crop_pct=float(self.v_action_top_crop.get()),
            auto_top_crop=bool(self.v_action_auto_top_crop.get()),
            vertical_bias=float(self.v_action_vertical_bias.get()),
            auto_vertical_bias=bool(self.v_action_auto_vertical_bias.get()),
            smart_auto_crop=bool(self.v_action_smart_auto_crop.get()),
            auto_pillarbox_crop=bool(self.v_action_auto_pillarbox.get()),
            dmd_visibility_score_enabled=bool(self.v_dmd_visibility_score_enabled.get()), # NEW
            dmd_readability_score_enabled=bool(self.v_dmd_readability_score_enabled.get()), # NEW
            start_s=start_s,
            end_s=end_s,
            target_width=self.v_target_width.get(),
            target_height=self.v_target_height.get(),
        )
        threading.Thread(
            target=self._generate_auto_preview,
            args=(src, cfg), daemon=True
        ).start()

    def _generate_auto_preview(self, src, cfg):
        """Run in a background thread. Returns PIL images (NOT PhotoImage) to the main thread."""
        try:
            ok, out_mp4, msg = preprocess_video_for_dmd(src, cfg)
            if not ok or not out_mp4:
                self.after(0, lambda: self._on_auto_fail(msg))
                return

            tmpdir = os.path.dirname(out_mp4)
            fps_prev = 12.5
            cmd = [
                "ffmpeg", "-y", "-i", out_mp4,
                "-vf", (
                    f"fps={fps_prev},"
                    f"scale={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:"
                    f"force_original_aspect_ratio=decrease,"
                    f"pad={AUTO_CANVAS_W}:{AUTO_CANVAS_H}:(ow-iw)/2:(oh-ih)/2"
                    f":color={BG_CANVAS[1:]}"
                ),
                "-f", "image2", os.path.join(tmpdir, "a%04d.png"),
            ]
            subprocess.run(cmd, capture_output=True)

            paths = sorted(glob.glob(os.path.join(tmpdir, "a*.png")))
            # Decode as plain PIL Images — PhotoImage must be created on the main thread
            pil_frames, delays = [], []
            delay_ms = int(1000 / fps_prev)
            for fp in paths:
                try:
                    pil_frames.append(Image.open(fp).convert("RGB").copy())
                    delays.append(delay_ms)
                except Exception:
                    pass

            self.after(0, lambda: self._on_auto_ready(pil_frames, delays, tmpdir, msg))

        except Exception as exc:
            # Safety net: always unblock the rendering flag even on unexpected errors.
            # NOTE: Python 3 deletes 'exc' at the end of the except block, so we must
            # snapshot it into a default argument (_e=exc) to avoid NameError in the lambda.
            _msg = f"Unexpected error: {exc}"
            self.after(0, lambda _m=_msg: self._on_auto_fail(_m))

    def _on_auto_ready(self, pil_frames, delays, tmpdir, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        if not pil_frames:
            self._on_auto_fail("No frames produced for auto-action preview")
            shutil.rmtree(tmpdir, ignore_errors=True)
            return
        self._stop_auto_preview()
        self._auto_tmpdir = tmpdir
        # Store PIL Images; PhotoImages are created lazily in _animate_auto (main thread, one per tick)
        self._auto_pil_frames = pil_frames
        self._auto_frames = [None] * len(pil_frames)
        self._auto_delays = delays
        self._auto_idx = 0
        self._auto_info.configure(text=f"{msg}  ·  {len(pil_frames)} frames")
        self._animate_auto()
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_auto_pending()

    def _on_auto_fail(self, msg):
        self._auto_rendering = False
        self._btn_auto.configure(state="normal", text="🎯 Auto")
        # Ensure tmpdir is defined before trying to remove it
        if hasattr(self, '_auto_tmpdir') and self._auto_tmpdir and os.path.isdir(self._auto_tmpdir):
            shutil.rmtree(self._auto_tmpdir, ignore_errors=True)
            self._auto_tmpdir = None
        self._auto_canvas.delete("all")
        self._auto_canvas.create_text(
            AUTO_CANVAS_W // 2, AUTO_CANVAS_H // 2,
            text="❌  Auto-action failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._auto_info.configure(text=msg)
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_auto_pending()

    def _flush_auto_pending(self):
        """If an Auto render was requested while we were busy, start it now."""
        pending = self._auto_pending_src
        self._auto_pending_src = None
        if pending and self._selected_iid:
            self.after(50, lambda: self._start_auto_generation(pending))

    def _animate_auto(self):
        if not self._auto_pil_frames:
            return
        num_frames = len(self._auto_pil_frames)
        idx = self._auto_idx % (num_frames + 1)
        
        if idx == num_frames:
            self._auto_canvas.delete("all")
            self._auto_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
            self._auto_idx += 1
            self._auto_job = self.after(1000, self._animate_auto)
            return

        # Lazy PhotoImage creation — one frame at a time on the main thread
        if self._auto_frames[idx] is None:
            self._auto_frames[idx] = ImageTk.PhotoImage(self._auto_pil_frames[idx])
        self._auto_canvas.delete("all")
        self._auto_canvas.create_image(0, 0, anchor="nw", image=self._auto_frames[idx])
        self._auto_idx += 1
        delay = self._auto_delays[idx] if self._auto_delays else 80
        self._auto_job = self.after(delay, self._animate_auto)

    # ══════════════════════════════════════════════════════════════════════════
    #  DMD PREVIEW  (independent canvas + animation loop)
    # ══════════════════════════════════════════════════════════════════════════

    def _stop_dmd_preview(self):
        if self._dmd_job:
            self.after_cancel(self._dmd_job)
            self._dmd_job = None
        self._dmd_pil_frames.clear()
        self._dmd_frames.clear()
        self._dmd_delays.clear()
        self._dmd_idx = 0
        if self._dmd_tmpdir and os.path.isdir(self._dmd_tmpdir):
            shutil.rmtree(self._dmd_tmpdir, ignore_errors=True)
            self._dmd_tmpdir = None

    def show_dmd_preview(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file first.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        self._start_dmd_generation(src)

    def _start_dmd_generation(self, src, is_already_converted=False):
        if self._dmd_rendering:
            # Queue the latest request — will start once the current render finishes
            self._dmd_pending_src = src
            return
        self._dmd_pending_src = None
        self._dmd_rendering = True
        self._btn_dmd.configure(state="disabled", text="⏳ DMD…")

        try:
            current_dmd_width, current_dmd_height = self._get_final_canvas_size()
        except Exception:
            current_dmd_width, current_dmd_height = 128, 32

        # ── Keep the canvas visible during re-render in ALL cases ────────────────
        self._dmd_canvas.delete("refresh_tag")
        self._dmd_canvas.create_text(
            current_dmd_width - 4, 4,
            text="↻", fill="#f39c12",
            font=("Helvetica", 10, "bold"),
            anchor="ne", tags="refresh_tag",
        )

        params  = self._collect_params()
        start_s, end_s = self._get_trim()
        led_sim = self.v_led_sim.get()
        if led_sim:
            dmd_display_w, dmd_display_h, sim_scale = self._compute_led_sim_display_size()
        else:
            dmd_display_w = current_dmd_width
            dmd_display_h = current_dmd_height
            sim_scale = 0
            
        if is_already_converted:
            threading.Thread(
                target=self._generate_dmd_preview,
                args=(src, params, start_s, end_s, dmd_display_w, dmd_display_h,
                      led_sim, sim_scale, current_dmd_width, current_dmd_height, True), daemon=True
            ).start()
        else:
            threading.Thread(
                target=self._generate_dmd_preview,
                args=(src, params, start_s, end_s, dmd_display_w, dmd_display_h,
                      led_sim, sim_scale, current_dmd_width, current_dmd_height, False), daemon=True
            ).start()

    def _generate_dmd_preview(self, src, params, start_s, end_s,
                              dmd_display_w, dmd_display_h,
                              led_sim: bool = False, sim_scale: int = 0, 
                              final_canvas_w: int = 128, final_canvas_h: int = 32,
                              is_already_converted: bool = False):
        """Run in a background thread. Returns PIL images (NOT PhotoImage) to the main thread."""
        tmpdir  = tempfile.mkdtemp(prefix="dmd_dmd_")
        try:
            if is_already_converted:
                out_gif = src
            else:
                out_gif = os.path.join(tmpdir, "preview.gif")
                success, msg = process_file(
                    src, out_gif, params, start_s, end_s,
                    callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: getattr(self, "_log", lambda x, y: None)(_m, _lv))
                )

                if not success or not os.path.isfile(out_gif):
                    self.after(0, lambda: self._on_dmd_fail(msg, tmpdir))
                    return

            # Decode frames as plain PIL Images — PhotoImage must be created on the main thread
            pil_frames, delays = [], []
            try:
                if out_gif.lower().endswith(('.mp4', '.mkv', '.mov', '.avi', '.webm')):
                    import cv2
                    cap = cv2.VideoCapture(out_gif)
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    delay_ms = int(1000 / fps) if fps > 0 else 40
                    while True:
                        ret, frame = cap.read()
                        if not ret:
                            break
                        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        comp = Image.fromarray(frame_rgb)
                        comp = comp.resize((dmd_display_w, dmd_display_h), Image.NEAREST)
                        if led_sim and sim_scale >= 2:
                            comp = self._apply_led_grid(comp, sim_scale)
                        if comp.size != (final_canvas_w, final_canvas_h):
                            comp = comp.resize((final_canvas_w, final_canvas_h), Image.LANCZOS)
                        pil_frames.append(comp)
                        delays.append(delay_ms)
                    cap.release()
                else:
                    from PIL import ImageSequence
                    img = Image.open(out_gif)
                    # FFmpeg often optimizes GIFs by only saving transparent delta pixels.
                    # Accumulating them onto a black background prevents glitches and transparent black artifacts.
                    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
                    for frame in ImageSequence.Iterator(img):
                        bg.paste(frame, (0, 0), frame.convert("RGBA"))
                        comp = bg.copy().convert("RGB").resize(
                            (dmd_display_w, dmd_display_h), Image.NEAREST
                        )
                        if led_sim and sim_scale >= 2:
                            comp = self._apply_led_grid(comp, sim_scale)
                            
                        if comp.size != (final_canvas_w, final_canvas_h):
                            comp = comp.resize((final_canvas_w, final_canvas_h), Image.LANCZOS)
                            
                        pil_frames.append(comp)
                        delays.append(max(img.info.get("duration", 80), 20))
            except Exception as exc:
                _msg = str(exc)
                self.after(0, lambda _m=_msg, _td=tmpdir: self._on_dmd_fail(_m, _td))
                return

            if not pil_frames:
                self.after(0, lambda: self._on_dmd_fail("No frames decoded from GIF", tmpdir))
                return

            self.after(0, lambda: self._on_dmd_ready(pil_frames, delays, tmpdir, out_gif))

        except Exception as exc:
            import traceback as _tb
            _detail = _tb.format_exc()
            # Safety net: snapshot exc before the except block clears it.
            _msg = f"Unexpected error: {exc}\n{_detail}"
            self.after(0, lambda _m=_msg, _td=tmpdir: self._on_dmd_fail(_m, _td))

    def _on_dmd_ready(self, pil_frames, delays, tmpdir, out_gif):
        try:
            self._dmd_rendering = False
            self._btn_dmd.configure(state="normal", text="🔬 DMD")
            self._stop_dmd_preview()      # cancels animation, cleans up old tmpdir
            self._dmd_tmpdir = tmpdir
            self._dmd_pil_frames = pil_frames
            self._dmd_frames = [None] * len(pil_frames)
            self._dmd_delays = delays
            self._dmd_idx    = 0
            size_kb = os.path.getsize(out_gif) // 1024
            self._dmd_info.configure(
                text=f"✅  {self.v_target_width.get()}×{self.v_target_height.get()}  ·  {len(pil_frames)} frames  ·  {size_kb} KB"
            )
            self._animate_dmd()
            # Start the pending render (if any new settings changed while we were busy)
            self._flush_dmd_pending()
        except Exception as _e:
            logger.exception("_on_dmd_ready exception: %s", _e)

    def _on_dmd_fail(self, msg, tmpdir):
        self._dmd_rendering = False
        self._btn_dmd.configure(state="normal", text="🔬 DMD")
        shutil.rmtree(tmpdir, ignore_errors=True)
        # Stop any ongoing animation so it cannot overwrite the error message
        self._stop_dmd_preview()
        self._dmd_canvas.delete("all")
        # Use current target dimensions for idle text positioning
        try:
            current_dmd_width, current_dmd_height = self._get_final_canvas_size()
        except Exception:
            current_dmd_width = int(128 * DMD_DISPLAY_SCALE_FACTOR)
            current_dmd_height = int(32 * DMD_DISPLAY_SCALE_FACTOR)
        self._dmd_canvas.create_text(
            current_dmd_width // 2, current_dmd_height // 2,
            text="❌  DMD render failed", fill="#e74c3c", font=("Helvetica", 11)
        )
        self._log(f"❌  DMD preview: {msg}", "error")
        # Start the pending render (if any new settings changed while we were busy)
        self._flush_dmd_pending()

    def _flush_dmd_pending(self):
        """If a DMD render was requested while we were busy, start it now."""
        pending = self._dmd_pending_src
        self._dmd_pending_src = None
        if pending and self._selected_iid:
            self.after(50, lambda: self._start_dmd_generation(pending))

    def _toggle_led_sim(self):
        """Toggle LED pixel-simulation mode and immediately re-render the DMD preview."""
        is_on = not self.v_led_sim.get()
        self.v_led_sim.set(is_on)
        # Update button appearance
        if is_on:
            self._btn_led_sim.configure(
                fg_color="#5a4a00", hover_color="#7a6400",
                text="💡 LED Sim  ✓"
            )
        else:
            self._btn_led_sim.configure(
                fg_color="#1a1a2e", hover_color="#2a2a4a",
                text="💡 LED Sim"
            )
        # Resize canvas to match new mode
        self._update_dmd_canvas_size()
        # Invalidate cached PhotoImages (scale changed) and re-render
        self._dmd_frames = [None] * len(self._dmd_pil_frames)  # force re-bake
        if self._selected_iid and not self._dmd_rendering:
            src = self._file_data.get(self._selected_iid)
            if src:
                self._start_dmd_generation(src)

    @staticmethod
    def _apply_led_grid(pil_img: "Image.Image", sim_scale: int,
                        gap: int = LED_SIM_GAP) -> "Image.Image":
        """Fast NumPy LED pixel-grid overlay.

        Each logical pixel occupies a (sim_scale × sim_scale) cell in the
        display image.  A dark border of `gap` px on every edge simulates the
        physical gap between LED emitters on an HUB75 matrix.

        The operation is fully vectorised — no Python loops over pixels.
        """
        return _apply_led_grid(pil_img, sim_scale, gap)

    def _animate_dmd(self):
        if not self._dmd_pil_frames:
            return
        try:
            num_frames = len(self._dmd_pil_frames)
            idx = self._dmd_idx % (num_frames + 1)
            
            if idx == num_frames:
                self._dmd_canvas.delete("all")
                self._dmd_canvas.create_rectangle(0, 0, 9999, 9999, fill="black", outline="")
                self._dmd_idx += 1
                self._dmd_job = self.after(1000, self._animate_dmd)
                return

            # Lazy PhotoImage creation — one frame at a time on the main thread
            if self._dmd_frames[idx] is None:
                self._dmd_frames[idx] = ImageTk.PhotoImage(self._dmd_pil_frames[idx])
            self._dmd_canvas.delete("all")
            self._dmd_canvas.create_image(0, 0, anchor="nw", image=self._dmd_frames[idx])
            self._dmd_idx += 1
            delay = self._dmd_delays[idx] if self._dmd_delays else 80
            self._dmd_job = self.after(delay, self._animate_dmd)
        except Exception as _exc:
            logger.exception("_animate_dmd exception: %s", _exc)

    # ── Auto-refresh debounce ─────────────────────────────────────────────────
    def _schedule_pipeline_refresh(self, *_):
        # Ignore debounce requests fired by _restore_params bulk var-sets.
        if self._restoring_params:
            return
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self._adv_refresh_job = self.after(DMD_REFRESH_DELAY_MS, self._auto_refresh_pipeline)

    def _schedule_dmd_only_refresh(self, *_):
        """Like _schedule_pipeline_refresh but only re-runs DMD conversion.
        
        Used for parameters that do NOT affect auto-action framing (text overlay,
        colorimetry-only changes, etc.) to avoid re-running the expensive
        OpenCV auto-action preprocessing unnecessarily.
        """
        if self._restoring_params:
            return
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
        self._adv_refresh_job = self.after(DMD_REFRESH_DELAY_MS, self._auto_refresh_dmd_only)

    def _auto_refresh_pipeline(self):
        self._adv_refresh_job = None
        if self._selected_iid and not self._busy and not self._auto_rendering and not self._dmd_rendering:
            src = self._file_data.get(self._selected_iid)
            if src:
                self._start_auto_generation(src)
                self._start_dmd_generation(src)

    def _auto_refresh_dmd_only(self):
        """Only refresh the DMD preview — skip auto-action preprocessing."""
        self._adv_refresh_job = None
        if self._selected_iid and not self._busy and not self._dmd_rendering:
            src = self._file_data.get(self._selected_iid)
            if src:
                self._start_dmd_generation(src)

    # ══════════════════════════════════════════════════════════════════════════
    #  TRIM
    # ══════════════════════════════════════════════════════════════════════════

    # ── Max-duration helpers ──────────────────────────────────────────────────
    def _on_max_dur_toggle(self):
        """Enable/disable the max-duration slider and refresh the trim end."""
        enabled = self.v_max_dur_enabled.get()
        self._max_dur_slider.configure(state="normal" if enabled else "disabled")
        if hasattr(self, "_sl_end"):
            self._sl_end.configure(state="disabled" if enabled else "normal")
        self._apply_max_duration()

    def _apply_max_duration(self):
        """If max_duration is active, snap trim_end to trim_start + max_duration."""
        if not self.v_max_dur_enabled.get():
            return
        if not hasattr(self, "_sl_end"):
            return
        start = self.v_trim_start.get()
        max_dur = self.v_max_duration.get()
        new_end = min(start + max_dur, self._source_duration)
        self.v_trim_end.set(new_end)
        if hasattr(self, "_lbl_end"):
            self._lbl_end.configure(text=f"{new_end:.1f} s")

    def _update_trim_sliders(self):
        dur = max(self._source_duration, 0.1)
        self._sl_start.configure(to=dur)
        self._sl_end.configure(to=dur)
        self.v_trim_start.set(0.0)
        # When max_duration is active, initialise end = min(max_dur, dur)
        if self.v_max_dur_enabled.get():
            init_end = min(self.v_max_duration.get(), dur)
        else:
            init_end = dur
        self.v_trim_end.set(init_end)
        self._lbl_start.configure(text="0.0 s")
        self._lbl_end.configure(text=f"{init_end:.1f} s")
        # Reflect max-dur state on end slider
        self._sl_end.configure(
            state="disabled" if self.v_max_dur_enabled.get() else "normal"
        )

    def _on_start_drag(self, val):
        v = float(val)
        end = self.v_trim_end.get()
        if self.v_max_dur_enabled.get():
            # End follows start automatically — clamp start to leave room
            max_dur = self.v_max_duration.get()
            v = min(v, max(0.0, self._source_duration - max_dur))
            self.v_trim_start.set(v)
            new_end = min(v + max_dur, self._source_duration)
            self.v_trim_end.set(new_end)
            self._lbl_end.configure(text=f"{new_end:.1f} s")
        else:
            if v >= end:
                self.v_trim_start.set(max(0.0, end - 0.05))
        self._lbl_start.configure(text=f"{self.v_trim_start.get():.1f} s")

    def _on_end_drag(self, val):
        v = float(val)
        start = self.v_trim_start.get()
        if v <= start:
            self.v_trim_end.set(min(self._source_duration, start + 0.05))
        self._lbl_end.configure(text=f"{self.v_trim_end.get():.1f} s")

    def _reset_trim(self):
        self.v_trim_start.set(0.0)
        self.v_trim_end.set(self._source_duration)
        self._lbl_start.configure(text="0.0 s")
        self._lbl_end.configure(text=f"{self._source_duration:.1f} s")

    def _get_trim(self):
        s = self.v_trim_start.get()
        e = self.v_trim_end.get()
        if s <= 0.0 and e >= self._source_duration - 0.05:
            return None, None
        return s, e

    # ══════════════════════════════════════════════════════════════════════════
    #  PER-GIF CONFIG
    # ══════════════════════════════════════════════════════════════════════════

