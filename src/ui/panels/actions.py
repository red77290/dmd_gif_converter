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

class ActionsPanelMixin:
    def _build_bottom_area(self, parent):
        bot = ctk.CTkFrame(parent, fg_color="transparent")
        bot.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)
        bot.grid_columnconfigure(0, weight=1)
        bot.grid_columnconfigure(1, weight=0)
        bot.grid_rowconfigure(0, weight=1)

        self._params_scroll = ctk.CTkScrollableFrame(bot, label_text="⚙️  Parameters")
        self._params_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._params_scroll.grid_columnconfigure(0, weight=1)
        self._build_params_panel(self._params_scroll)

        ar = ctk.CTkFrame(bot, width=310)
        ar.grid(row=0, column=1, sticky="nsew")
        ar.grid_propagate(False)
        ar.grid_columnconfigure(0, weight=1)
        ar.grid_rowconfigure(3, weight=1)
        self._build_actions_panel(ar)

    # ── Params panel ──────────────────────────────────────────────────────────
    def _build_actions_panel(self, parent):
        ctk.CTkLabel(
            parent, text="🚀  Actions",
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        af = ctk.CTkFrame(parent, fg_color="transparent")
        af.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        af.grid_columnconfigure(0, weight=1)

        self._btn_convert = ctk.CTkButton(
            af,
            text="▶  Convert selected file\n    (click a file in the list first)",
            command=self.convert_selected,
            height=52, fg_color="#1a4f7a", hover_color="#1a618d",
            font=ctk.CTkFont(size=13), state="disabled"
        )
        self._btn_convert.grid(row=0, column=0, padx=4, pady=4, sticky="ew")

        self._btn_all = ctk.CTkButton(
            af, text="⚡  Convert all listed files",
            command=self.convert_all,
            height=36, fg_color="#5b2fa0", hover_color="#4a2585",
            font=ctk.CTkFont(size=12)
        )
        self._btn_all.grid(row=1, column=0, padx=4, pady=4, sticky="ew")

        self._btn_batch = ctk.CTkButton(
            af, text="📂  Batch — choose a folder",
            command=self.batch_folder,
            height=36, fg_color="#1e6a3c", hover_color="#155230",
            font=ctk.CTkFont(size=12)
        )
        self._btn_batch.grid(row=2, column=0, padx=4, pady=4, sticky="ew")

        self._progress = ctk.CTkProgressBar(af, height=8)
        self._progress.set(0)
        self._progress.grid(row=3, column=0, padx=4, pady=(10, 2), sticky="ew")

        self._status_lbl = ctk.CTkLabel(
            af, text="Ready", text_color="#888899", font=ctk.CTkFont(size=11)
        )
        self._status_lbl.grid(row=4, column=0, padx=4, pady=2)

        ctk.CTkLabel(
            parent, text="📋  Conversion log",
            font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, padx=12, pady=(10, 2), sticky="w")

        self._log_box = ctk.CTkTextbox(
            parent, font=ctk.CTkFont(size=11, family="Courier"), wrap="word"
        )
        self._log_box.grid(row=3, column=0, padx=8, pady=(0, 8), sticky="nsew")
        self._log_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  FILE MANAGEMENT
    # ══════════════════════════════════════════════════════════════════════════

    def browse_output(self):
        folder = filedialog.askdirectory(title="Choose output folder")
        if folder:
            self.v_output_dir.set(folder)

    # ══════════════════════════════════════════════════════════════════════════
    #  SOURCE PREVIEW
    # ══════════════════════════════════════════════════════════════════════════

    def _out_path(self, src):
        stem    = Path(src).stem
        out_dir = self.v_output_dir.get().strip() or str(Path(src).parent)
        out = os.path.join(out_dir, stem + ".gif")
        # Prevent silently overwriting the source file
        if os.path.normpath(out) == os.path.normpath(src):
            out = os.path.join(out_dir, stem + "_dmd.gif")
        return out

    def convert_selected(self):
        if not self._selected_iid:
            messagebox.showinfo("Info", "Select a file from the list first.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        src = self._file_data.get(self._selected_iid)
        if not src:
            return
        out = self._out_path(src)
        start_s, end_s = self._get_trim()
        trim_info = f"  trim [{start_s:.1f}s → {end_s:.1f}s]" if start_s is not None else ""
        self._log(f"▶  Convert: {Path(src).name}{trim_info}")
        tasks = [(src, out, start_s, end_s, self._selected_iid)]
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def convert_all(self):
        if not self._file_data:
            messagebox.showinfo("Info", "The file list is empty.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        tasks = [
            (path, self._out_path(path), None, None, iid)
            for iid, path in self._file_data.items()
        ]
        self._log(f"⚡  Converting {len(tasks)} file(s)…")
        for _, _, _, _, iid in tasks:
            self._set_file_status(iid, "converting")
        threading.Thread(
            target=self._run_tasks, args=(tasks, self._collect_params()), daemon=True
        ).start()

    def batch_folder(self):
        folder_in = filedialog.askdirectory(title="Source folder — Batch")
        if not folder_in:
            return
        out_dir = self.v_output_dir.get().strip()
        if not out_dir:
            out_dir = str(Path(folder_in).parent / (Path(folder_in).name + "_DMD"))
        files = [
            f for f in os.listdir(folder_in)
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            messagebox.showinfo("Info", "No supported files found in this folder.")
            return
        if self._busy:
            messagebox.showwarning("Busy", "A conversion is already running.")
            return
        params = self._collect_params()
        self._log(f"📂  Batch: {len(files)} file(s)  →  {out_dir}")
        threading.Thread(
            target=self._run_batch_folder, args=(folder_in, out_dir, params), daemon=True
        ).start()

    def _run_tasks(self, tasks, params):
        self.after(0, lambda: self._set_busy(True))
        total = len(tasks)
        for i, (src, out, start_s, end_s, iid) in enumerate(tasks):
            self.after(0, lambda _iid=iid: self._set_file_status(_iid, "converting"))
            success, msg = process_file(
                src, out, params, start_s, end_s,
                callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv))
            )
            status = "done" if success else "error"
            self.after(0, lambda _iid=iid, s=status: self._set_file_status(_iid, s))
            self.after(0, lambda p=(i + 1) / total: self._progress.set(p))
        self.after(0, lambda: self._log(f"✅  {total} conversion(s) done."))
        self.after(0, lambda: self._set_busy(False))

    def _run_batch_folder(self, folder_in, folder_out, params):
        self.after(0, lambda: self._set_busy(True))
        self.after(0, lambda: self._progress.set(0))

        def on_progress(done, total):
            frac = done / max(1, total)
            self.after(0, lambda f=frac: self._progress.set(f))

        process_folder(
            folder_in, folder_out, params,
            callback=lambda m, lv="info": self.after(0, lambda _m=m, _lv=lv: self._log(_m, _lv)),
            progress_callback=on_progress,
        )
        self.after(0, lambda: self._log("✅  Batch folder done."))
        self.after(0, lambda: self._set_busy(False))

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self._btn_convert, self._btn_all, self._btn_batch):
            btn.configure(state=state)
        for btn in (self._btn_all_prev, self._btn_src, self._btn_auto, self._btn_dmd):
            btn.configure(state=state)
        self._status_lbl.configure(text="⏳  Converting…" if busy else "Ready")
        if not busy:
            self._progress.set(1.0)
            self.after(2500, lambda: self._progress.set(0))

    # ══════════════════════════════════════════════════════════════════════════
    #  LOG
    # ══════════════════════════════════════════════════════════════════════════

    def _log(self, message, level="info"):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", message + "\n")
        self._log_box.configure(state="disabled")
        self._log_box.see("end")

    # ══════════════════════════════════════════════════════════════════════════
    #  CLEANUP
    # ══════════════════════════════════════════════════════════════════════════

