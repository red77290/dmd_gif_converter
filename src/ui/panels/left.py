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

# ── GIF Search optional dependencies ─────────────────────────────────────────
# Package was renamed duckduckgo_search → ddgs ; try both for backward compat.
try:
    import requests as _requests
    try:
        from ddgs import DDGS as _DDGS          # new name (v9+)
    except ImportError:
        from duckduckgo_search import DDGS as _DDGS  # legacy name (<=8.x)
    _gif_search_available = True
except ImportError:
    _requests = None
    _DDGS = None
    _gif_search_available = False


class LeftPanelMixin:
    def _build_left_panel(self):
        lp = ctk.CTkFrame(self, width=295, corner_radius=0)
        lp.grid(row=0, column=0, sticky="nsew")
        lp.grid_propagate(False)
        lp.grid_rowconfigure(3, weight=1)   # row 3 = tree (was 2)
        lp.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(lp, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=10, pady=(12, 4), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="📁  Source files",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        self._count_lbl = ctk.CTkLabel(
            hdr, text="empty", text_color="#666688", font=ctk.CTkFont(size=11)
        )
        self._count_lbl.grid(row=0, column=1, sticky="e")

        br = ctk.CTkFrame(lp, fg_color="transparent")
        br.grid(row=1, column=0, padx=8, pady=(0, 4), sticky="ew")
        br.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkButton(br, text="➕ File(s)", command=self.add_files, height=30).grid(
            row=0, column=0, padx=2, sticky="ew")
        ctk.CTkButton(br, text="📂 Folder",  command=self.add_folder, height=30).grid(
            row=0, column=1, padx=2, sticky="ew")
        ctk.CTkButton(br, text="✕ Remove",   command=self._remove_selected,
                      height=30, fg_color="#3a3a4a", hover_color="#7b241c").grid(
            row=0, column=2, padx=2, sticky="ew")

        self._btn_refresh_folder = ctk.CTkButton(
            br, text="🔄 Refresh folder", command=self.refresh_folder,
            height=28, fg_color="#1a3a1a", hover_color="#2a5a2a",
            font=ctk.CTkFont(size=11), state="disabled"
        )
        self._btn_refresh_folder.grid(
            row=1, column=0, columnspan=3, padx=2, pady=(3, 0), sticky="ew"
        )

        # ── GIF Search section (row=2) ────────────────────────────────────────
        self._build_search_section(lp)

        self._style_treeview()
        tree_host = tk.Frame(lp, bg="#12121f")
        tree_host.grid(row=3, column=0, padx=6, pady=4, sticky="nsew")
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_host, style="File.Treeview",
            show="tree", selectmode="extended"
        )
        sb = ttk.Scrollbar(tree_host, orient="vertical",
                           command=self._tree.yview, style="File.Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")

        self._tree.tag_configure("idle",       foreground="#aaaacc")
        self._tree.tag_configure("converting", foreground="#f39c12")
        self._tree.tag_configure("done",       foreground="#2ecc71")
        self._tree.tag_configure("error",      foreground="#e74c3c")

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Delete>",           lambda _e: self._remove_selected())
        self._tree.bind("<BackSpace>",        lambda _e: self._remove_selected())

        ctk.CTkLabel(lp, text="👆 Click · Ctrl/⇧ multi-select · Del to remove",
                     text_color="#444466", font=ctk.CTkFont(size=10)
                     ).grid(row=4, column=0, padx=8, pady=(0, 2), sticky="w")

        bot = ctk.CTkFrame(lp, fg_color="transparent")
        bot.grid(row=5, column=0, padx=6, pady=6, sticky="ew")
        bot.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(bot, text="📤 Output folder", font=ctk.CTkFont(size=12)).grid(
            row=0, column=0, columnspan=2, padx=4, pady=(6, 1), sticky="w"
        )
        of = ctk.CTkFrame(bot, fg_color="transparent")
        of.grid(row=1, column=0, columnspan=2, sticky="ew")
        of.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            of, textvariable=self.v_output_dir,
            placeholder_text="(same folder as source)", height=28
        ).grid(row=0, column=0, padx=(4, 2), sticky="ew")
        ctk.CTkButton(
            of, text="…", width=28, height=28, command=self.browse_output
        ).grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(
            bot, text="🗑  Clear list", command=self.clear_files,
            fg_color="#3a3a4a", hover_color="#7b241c", height=28
        ).grid(row=2, column=0, columnspan=2, padx=4, pady=(8, 2), sticky="ew")

    def _build_search_section(self, parent):
        """Compact GIF-search panel inserted between the file buttons and the tree."""
        sf = ctk.CTkFrame(parent, fg_color="#0d1a2a", corner_radius=6)
        sf.grid(row=2, column=0, padx=8, pady=(0, 4), sticky="ew")
        sf.grid_columnconfigure(0, weight=1)

        # Header row
        head = ctk.CTkFrame(sf, fg_color="transparent")
        head.grid(row=0, column=0, padx=8, pady=(6, 2), sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head, text="🔍  GIF Search  (DuckDuckGo)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#5ba3d9"
        ).grid(row=0, column=0, sticky="w")

        # Search bar row: [keyword entry] [qty entry] [Download btn]
        sr = ctk.CTkFrame(sf, fg_color="transparent")
        sr.grid(row=1, column=0, padx=8, pady=2, sticky="ew")
        sr.grid_columnconfigure(0, weight=1)

        self._search_entry = ctk.CTkEntry(
            sr, textvariable=self.v_search_keyword,
            placeholder_text="keyword…", height=28
        )
        self._search_entry.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self._search_entry.bind("<Return>", lambda _e: self._search_and_download())

        # Quantity entry (small, 1-50)
        qty_frame = ctk.CTkFrame(sr, fg_color="transparent")
        qty_frame.grid(row=0, column=1, padx=(0, 4))
        ctk.CTkLabel(qty_frame, text="×", font=ctk.CTkFont(size=11),
                     text_color="#888899").pack(side="left")
        self._qty_entry = ctk.CTkEntry(
            qty_frame, textvariable=self.v_search_qty,
            width=52, height=28, justify="center"
        )
        self._qty_entry.pack(side="left")

        self._btn_search = ctk.CTkButton(
            sr, text="⬇ DL", width=50, height=28,
            fg_color="#1a4f6e", hover_color="#1a618d",
            command=self._search_and_download,
            state="normal" if _gif_search_available else "disabled"
        )
        self._btn_search.grid(row=0, column=2)

        # Cancel button (hidden by default)
        self._btn_cancel_dl = ctk.CTkButton(
            sf, text="✕ Cancel", height=24,
            fg_color="#4a1a1a", hover_color="#7b241c",
            font=ctk.CTkFont(size=11),
            command=self._cancel_download
        )
        # Not shown until a download starts

        # Status label
        self._search_status = ctk.CTkLabel(
            sf, text="" if _gif_search_available else "⚠ duckduckgo-search / requests not installed",
            text_color="#556677", font=ctk.CTkFont(size=10)
        )
        self._search_status.grid(row=3, column=0, padx=8, pady=(2, 6), sticky="w")

    def _search_and_download(self):
        """Validate inputs and launch the download thread."""
        if not _gif_search_available:
            messagebox.showerror(
                "Missing dependencies",
                "GIF Search requires extra packages.\n\n"
                "Install with:\n  pip install duckduckgo-search requests\n\n"
                "Or re-run ./launch_ui.sh — it installs automatically."
            )
            return

        keyword = self.v_search_keyword.get().strip()
        if not keyword:
            messagebox.showwarning("Search", "Please enter a keyword to search for GIFs.")
            self._search_entry.focus_set()
            return

        try:
            qty = int(self.v_search_qty.get())
            if qty < 1:
                qty = 1
            if qty > 300:
                qty = 300
            self.v_search_qty.set(qty)
        except (ValueError, tk.TclError):
            messagebox.showwarning("Search", "Quantity must be a number between 1 and 300.")
            self._qty_entry.focus_set()
            return

        if self._download_active:
            messagebox.showwarning("Busy", "A download is already in progress.")
            return

        # Create a dedicated temp dir for this search
        tmpdir = tempfile.mkdtemp(prefix="dmd_gifsearch_")
        self._gif_tmpdirs.append(tmpdir)

        self._download_active = True
        self._download_cancel = False

        # UI feedback
        self._btn_search.configure(state="disabled", text="⏳…")
        self._btn_cancel_dl.grid(row=2, column=0, padx=8, pady=(0, 2), sticky="ew")
        self._search_status.configure(
            text=f"🔍 Searching '{keyword}'…", text_color="#5ba3d9"
        )
        self._progress.set(0)
        self._status_lbl.configure(text=f"⬇  Downloading GIFs…")
        self._log(f"🔍  GIF Search: '{keyword}' × {qty}  →  {tmpdir}")

        threading.Thread(
            target=self._run_download,
            args=(keyword, qty, tmpdir),
            daemon=True
        ).start()

    def _run_download(self, keyword: str, qty: int, tmpdir: str):
        """Background thread: search + download GIFs one by one."""
        downloaded = 0
        errors     = 0

        def _ui(fn):
            self.after(0, fn)

        try:
            _ui(lambda: self._search_status.configure(
                text=f"🔍 Querying DuckDuckGo…", text_color="#5ba3d9"
            ))
            results = list(_DDGS().images(
                keyword + " gif",       # positional 'query' (ddgs v7+) — replaces keywords=
                safesearch="off",
                type_image="gif",
                max_results=qty,
            ))
        except Exception as exc:
            logger.warning("DuckDuckGo search failed: %s", exc)
            _err = f"Search failed: {exc}"   # capture before lambda — exc is cleared after except block
            _ui(lambda: self._on_download_done(
                keyword, 0, 0, qty, error=_err
            ))
            return

        if not results:
            _ui(lambda: self._on_download_done(
                keyword, 0, 0, qty, error=f"No GIFs found for '{keyword}'."
            ))
            return

        total = len(results)
        _ui(lambda: self._log(f"   Found {total} result(s) — downloading…"))

        for i, result in enumerate(results):
            if self._download_cancel:
                break

            image_url = result.get("image")
            if not image_url:
                continue

            # Build filename
            basename = os.path.basename(image_url).split("?")[0]
            if not basename or "." not in basename:
                basename = f"{keyword.replace(' ', '_')}_{i + 1}.gif"
            # Ensure .gif extension
            if not basename.lower().endswith(".gif"):
                basename = os.path.splitext(basename)[0] + ".gif"
            # Sanitise
            safe_name = "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in basename)
            file_path  = os.path.join(tmpdir, safe_name)

            # Avoid overwriting if same name
            if os.path.exists(file_path):
                stem, ext = os.path.splitext(safe_name)
                file_path = os.path.join(tmpdir, f"{stem}_{i}{ext}")

            try:
                resp = _requests.get(image_url, stream=True, timeout=12)
                resp.raise_for_status()

                # Validate Content-Type (best-effort)
                ct = resp.headers.get("Content-Type", "")
                if ct and "image" not in ct and "octet-stream" not in ct:
                    logger.debug("Skipping non-image URL: %s (CT=%s)", image_url, ct)
                    errors += 1
                    continue

                with open(file_path, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if self._download_cancel:
                            break
                        fh.write(chunk)

                if self._download_cancel:
                    # Remove incomplete file
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                    break

                downloaded += 1
                _fp = file_path
                _ui(lambda p=_fp: self._add_downloaded_gif(p))
                prog = downloaded / total
                _ui(lambda v=prog: self._progress.set(v))
                _ui(lambda d=downloaded, t=total: self._search_status.configure(
                    text=f"⬇ {d}/{t} downloaded…", text_color="#5ba3d9"
                ))

            except _requests.exceptions.Timeout:
                errors += 1
                logger.warning("Timeout downloading %s", image_url)
                _ui(lambda u=image_url: self._log(f"   ⚠ Timeout: {u[:60]}…", "error"))
            except _requests.exceptions.RequestException as exc:
                errors += 1
                logger.warning("Download error %s: %s", image_url, exc)
                _ui(lambda e=str(exc): self._log(f"   ⚠ Download error: {e[:80]}", "error"))
            except Exception as exc:
                errors += 1
                logger.warning("Unexpected error for %s: %s", image_url, exc)
                _ui(lambda e=str(exc): self._log(f"   ⚠ Unexpected: {e[:80]}", "error"))

        _ui(lambda: self._on_download_done(keyword, downloaded, errors, total))

    def _add_downloaded_gif(self, path: str):
        """Main thread: add a freshly downloaded GIF to the file list."""
        if not os.path.isfile(path):
            return
        self._add_file_raw(path)
        self._update_count()

    def _cancel_download(self):
        """Request cancellation of an active download."""
        if self._download_active:
            self._download_cancel = True
            self._search_status.configure(text="⏹ Cancelling…", text_color="#f39c12")

    def _on_download_done(self, keyword: str, downloaded: int, errors: int, total: int,
                          error: str = ""):
        """Main thread: reset download UI state."""
        self._download_active = False
        self._download_cancel = False

        self._btn_search.configure(state="normal" if _gif_search_available else "disabled",
                                   text="⬇ DL")
        self._btn_cancel_dl.grid_remove()

        if error:
            self._search_status.configure(text=f"❌ {error}", text_color="#e74c3c")
            self._log(f"❌  GIF Search failed: {error}", "error")
            self._progress.set(0)
            self._status_lbl.configure(text="Ready")
            return

        cancelled = downloaded < total and not error
        txt = f"✅ {downloaded}/{total} GIFs downloaded"
        if errors:
            txt += f"  ({errors} error{'s' if errors != 1 else ''})"
        if cancelled:
            txt += "  [cancelled]"
        self._search_status.configure(text=txt, text_color="#2ecc71" if downloaded else "#e74c3c")
        self._log(f"✅  GIF Search '{keyword}': {downloaded} downloaded, {errors} error(s).")
        self._progress.set(1.0)
        self._status_lbl.configure(text="Ready")
        self.after(2500, lambda: self._progress.set(0))

    def _style_treeview(self):
        s = ttk.Style()
        s.theme_use("default")
        s.configure("File.Treeview",
                    background="#12121f", foreground="#aaaacc",
                    fieldbackground="#12121f", borderwidth=0,
                    rowheight=26, font=("Helvetica", 12))
        s.map("File.Treeview",
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", "#ffffff")])
        s.layout("File.Treeview", [("File.Treeview.treearea", {"sticky": "nswe"})])
        s.configure("File.Vertical.TScrollbar",
                    background="#2a2a3e", troughcolor="#12121f",
                    arrowcolor="#555577", relief="flat")

    def _update_count(self):
        n = len(self._file_data)
        self._count_lbl.configure(
            text=f"{n} file{'s' if n != 1 else ''}" if n else "empty"
        )

    # ── Right panel ───────────────────────────────────────────────────────────
    def add_files(self):
        ext_list = " ".join(f"*{e}" for e in sorted(SUPPORTED_EXTENSIONS))
        paths = filedialog.askopenfilenames(
            title="Select video / GIF files",
            filetypes=[("Video / GIF", ext_list), ("All files", "*.*")]
        )
        if paths:
            self._batch_insert(list(paths), 0)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select source folder")
        if not folder:
            return
        self._last_source_folder = folder
        if hasattr(self, "_btn_refresh_folder"):
            self._btn_refresh_folder.configure(state="normal")
        threading.Thread(target=self._scan_folder, args=(folder,), daemon=True).start()

    def refresh_folder(self):
        """Re-scan the last selected folder and add any new files."""
        if not self._last_source_folder:
            return
        folder = self._last_source_folder
        self._log(f"🔄  Refreshing folder: {Path(folder).name}…")
        threading.Thread(target=self._scan_folder_refresh, args=(folder,), daemon=True).start()

    def _scan_folder_refresh(self, folder):
        """Like _scan_folder but only adds new files (silent if nothing new)."""
        paths = sorted([
            os.path.join(folder, f) for f in os.listdir(folder)
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ])
        if not paths:
            self.after(0, lambda: self._log("   No supported files found in folder."))
            return
        new_paths = [p for p in paths if p not in self._file_paths]
        if not new_paths:
            self.after(0, lambda: self._log("   ✅  No new files — folder is up to date."))
            return
        self.after(0, lambda: self._batch_insert(new_paths, 0, folder))

    def _scan_folder(self, folder):
        paths = sorted([
            os.path.join(folder, f) for f in os.listdir(folder)
            if Path(f).suffix.lower() in SUPPORTED_EXTENSIONS
        ])
        if not paths:
            self.after(0, lambda: messagebox.showinfo(
                "Info", "No supported files found in this folder."))
            return
        self.after(0, lambda: self._batch_insert(paths, 0, folder))

    def _batch_insert(self, paths, start, source_folder=None, batch_size=150):
        batch = paths[start:start + batch_size]
        for p in batch:
            self._add_file_raw(p)
        self._update_count()
        remaining = start + batch_size
        if remaining < len(paths):
            self.after(0, lambda: self._batch_insert(paths, remaining, source_folder, batch_size))
        else:
            folder_name = Path(source_folder).name if source_folder else ""
            if folder_name:
                self._log(f"📂  {len(paths)} file(s) added from '{folder_name}'")

    def _add_file_raw(self, path):
        if path in self._file_paths:
            return
        ext  = Path(path).suffix.lower()
        icon = "🎞" if ext == ".gif" else "🎬"
        name = Path(path).name
        disp = (name[:30] + "…") if len(name) > 32 else name
        iid  = self._tree.insert("", "end", text=f"  {icon}  {disp}", tags=("idle",))
        self._file_data[iid]  = path
        self._file_paths.add(path)

    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        # With extended selectmode, use the focused item (last clicked) for preview.
        iid = self._tree.focus() or sel[0]
        if iid not in sel:
            iid = sel[0]

        # ── Short-circuit: same item re-clicked ──────────────────────────────
        if iid == self._selected_iid:
            return

        # ── SAVE first — synchronous, instant, before ANY state change ───────
        # This must happen before _restore_params overwrites the UI vars.
        if self.v_per_gif_config.get() and self._selected_iid:
            old_path = self._file_data.get(self._selected_iid)
            if old_path:
                self._per_gif_configs[old_path] = self._snapshot_params()

        # ── Cancel any pending debounce refresh (stale render for old GIF) ───
        if self._adv_refresh_job:
            self.after_cancel(self._adv_refresh_job)
            self._adv_refresh_job = None

        self._selected_iid = iid
        if hasattr(self, "_btn_convert") and not self._busy:
            self._btn_convert.configure(state="normal")
        path = self._file_data.get(iid)
        if path:
            # Per-GIF config: load saved config (if any) when mode is enabled.
            # _restore_params fires ~40 var traces → each would re-schedule the
            # debounce.  We suppress them with a flag so the restore is atomic
            # and silent; we cancel once more afterwards for safety.
            if self.v_per_gif_config.get():
                if path in self._per_gif_configs:
                    self._restoring_params = True
                    try:
                        self._restore_params(self._per_gif_configs[path])
                    finally:
                        self._restoring_params = False
                    self._update_per_gif_status(path, saved=True)
                else:
                    self._update_per_gif_status(path, saved=False)

            # Cancel debounce once more: _restore_params may have fired traces
            # before the flag was set (or the flag was cleared), so make sure
            # no stale job is queued before we start fresh renders.
            if self._adv_refresh_job:
                self.after_cancel(self._adv_refresh_job)
                self._adv_refresh_job = None

            self._load_preview(path)
            # If Smart Color Boost is active, refresh computed values for this file
            if self.v_auto_color_enabled.get():
                self._refresh_auto_color_values(path)

    def _remove_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        # If the currently previewed file is among the items to remove, stop preview first.
        if self._selected_iid in sel:
            self._stop_src_preview()
            self._stop_auto_preview()
            self._stop_dmd_preview()
            self._selected_iid = ""
            self._trim_frame.grid_remove()
            self._draw_canvas_idle()
            self._draw_auto_canvas_idle()
            self._draw_dmd_canvas_idle()
        for iid in sel:
            path = self._file_data.pop(iid, None)
            if path:
                self._file_paths.discard(path)
                self._per_gif_configs.pop(path, None)  # remove per-gif config
            self._tree.delete(iid)
        self._update_count()

    def clear_files(self):
        self._stop_src_preview()
        self._stop_auto_preview()
        self._stop_dmd_preview()
        self._tree.delete(*self._tree.get_children())
        self._file_data.clear()
        self._file_paths.clear()
        self._per_gif_configs.clear()  # clear all per-gif configs
        self._selected_iid = ""
        self._trim_frame.grid_remove()
        self._draw_canvas_idle()
        self._draw_auto_canvas_idle()
        self._draw_dmd_canvas_idle()
        self._update_count()
        if hasattr(self, "_per_gif_status_lbl"):
            self._per_gif_status_lbl.configure(text="")

    def _set_file_status(self, iid, status):
        try:
            self._tree.item(iid, tags=(status,))
        except tk.TclError:
            pass

