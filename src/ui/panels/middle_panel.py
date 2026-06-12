import os
import logging
import tkinter as tk
import tkinter.ttk as ttk
import customtkinter as ctk
from pathlib import Path
from tkinter import messagebox

from src.ui.events.event_bus import EventBus, EventType

logger = logging.getLogger(__name__)

class MiddlePanel(ctk.CTkFrame):
    def __init__(self, parent, app_state, **kwargs):
        super().__init__(parent, width=320, corner_radius=0, **kwargs)
        self.app_state = app_state
        self._converted_files = []
        self._converted_data: dict = {}
        self._converted_paths: set = set()
        self._selected_converted_iid: str = ""
        self._build_ui()


    def browse_output(self):
        d = tk.filedialog.askdirectory(title="Select output folder", initialdir=self.app_state.v_output_dir.get())
        if d:
            self.app_state.v_output_dir.set(d)

    def _build_ui(self):
        mp = self
        mp.grid_propagate(False)
        mp.grid_rowconfigure(5, weight=1)  # treeview row expands
        mp.grid_columnconfigure(0, weight=1)

        # ── Quick Settings (row 0) ────────────────────────────────────────────
        qs = ctk.CTkFrame(mp, fg_color="#1a1200", corner_radius=8, border_width=1, border_color="#ffaa22")
        qs.grid(row=0, column=0, padx=10, pady=(10, 4), sticky="ew")
        qs.grid_columnconfigure(0, weight=1)
        
        self._lmh_cb = ctk.CTkCheckBox(
            qs,
            text="🤖 Let me handle it (Auto)",
            variable=self.app_state.v_let_me_handle_it,
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#ffaa22",
            fg_color="#cc7700", hover_color="#ff9900"
        )
        self._lmh_cb.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        
        ctk.CTkButton(
            qs, text="⚙️ Advanced", width=90, height=24,
            command=self._open_advanced_settings,
            fg_color="#3a3a4a", hover_color="#5a5a6a"
        ).grid(row=0, column=1, padx=10, pady=8, sticky="e")

        # ── Target Resolution ────────────────────────────────────────────────
        res_frame = ctk.CTkFrame(mp, fg_color="transparent")
        res_frame.grid(row=1, column=0, padx=10, pady=(2, 8), sticky="ew")
        res_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(res_frame, text="Resolution:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._target_preset_menu = ctk.CTkOptionMenu(
            res_frame,
            variable=self.app_state.v_target_preset,
            values=["128x32 (1x1)", "256x32 (2x1)", "128x64 (1x2)", "256x64 (2x2)", "Custom"],
            command=self._on_target_preset_change,
            height=24
        )
        self._target_preset_menu.grid(row=0, column=1, sticky="ew")

        # Custom inputs
        self._custom_res_frame = ctk.CTkFrame(res_frame, fg_color="transparent")
        self._custom_res_frame.grid_columnconfigure(1, weight=1)
        self._custom_res_frame.grid_columnconfigure(3, weight=1)
        
        ctk.CTkLabel(self._custom_res_frame, text="W:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=2)
        ctk.CTkEntry(self._custom_res_frame, textvariable=self.app_state.v_target_width, width=45, height=24).grid(row=0, column=1, padx=2)
        ctk.CTkLabel(self._custom_res_frame, text="H:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=2)
        ctk.CTkEntry(self._custom_res_frame, textvariable=self.app_state.v_target_height, width=45, height=24).grid(row=0, column=3, padx=2)

        self._on_target_preset_change(self.app_state.v_target_preset.get())

        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(mp, fg_color="transparent")
        hdr.grid(row=2, column=0, padx=10, pady=(8, 4), sticky="ew")
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="✅  Converted Files",
            font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        
        self._converted_count_lbl = ctk.CTkLabel(
            hdr, text="empty", text_color="#666688", font=ctk.CTkFont(size=11)
        )
        self._converted_count_lbl.grid(row=0, column=1, sticky="e", padx=(0, 8))

        ctk.CTkButton(
            hdr, text="Clear", width=40, height=20, font=ctk.CTkFont(size=10),
            command=self._clear_converted, fg_color="#3a3a4a", hover_color="#c0392b"
        ).grid(row=0, column=2, sticky="e")

        # ── Global Statistics ───────────────────────────────────────────────
        stat_frame = ctk.CTkFrame(mp, fg_color="#12121f", corner_radius=6)
        stat_frame.grid(row=3, column=0, padx=8, pady=(4, 6), sticky="ew")
        stat_frame.grid_columnconfigure((0,1,2,3,4,5), weight=1)
        
        def _stat_lbl(text, color, col, row=0):
            lbl = ctk.CTkLabel(stat_frame, text=text, text_color=color, font=ctk.CTkFont(size=11, weight="bold"))
            lbl.grid(row=row, column=col, padx=2, pady=2)
            return lbl

        self._stat_vars = {
            "total": _stat_lbl("Tot: 0", "#ffffff", 0),
            "Premium": _stat_lbl("🌟 0", "#2ecc71", 1),
            "Good": _stat_lbl("🟢 0", "#88dd88", 2),
            "Acceptable": _stat_lbl("🟡 0", "#f1c40f", 3),
            "Poor": _stat_lbl("🟠 0", "#e67e22", 4),
            "Bad": _stat_lbl("🔴 0", "#e74c3c", 5),
        }

        # ── Filter & Search ──────────────────────────────────────────────────
        filter_frame = ctk.CTkFrame(mp, fg_color="transparent")
        filter_frame.grid(row=4, column=0, padx=8, pady=2, sticky="ew")
        filter_frame.grid_columnconfigure(1, weight=1)

        self.app_state.v_filter_preset = tk.StringVar(value="Show All")
        preset_menu = ctk.CTkOptionMenu(
            filter_frame, variable=self.app_state.v_filter_preset,
            values=["Show All", "Excellent Only", "Good And Above", "Acceptable And Above", "Poor And Above"],
            command=self._on_filter_changed,
            width=140, height=26
        )
        preset_menu.grid(row=0, column=0, sticky="w", padx=(0, 4))
        
        self.app_state.v_search_converted = tk.StringVar(value="")
        search_entry = ctk.CTkEntry(
            filter_frame, textvariable=self.app_state.v_search_converted,
            placeholder_text="Search...", height=26
        )
        search_entry.grid(row=0, column=1, sticky="ew")
        search_entry.bind("<KeyRelease>", self._on_filter_changed)

        # ── Treeview ─────────────────────────────────────────────────────────
        tree_host = tk.Frame(mp, bg="#12121f")
        tree_host.grid(row=5, column=0, padx=6, pady=4, sticky="nsew")
        tree_host.grid_rowconfigure(0, weight=1)
        tree_host.grid_columnconfigure(0, weight=1)

        self._tree_converted = ttk.Treeview(
            tree_host, style="Converted.Treeview",
            columns=("Score", "Category"),
            show="tree headings", selectmode="extended"
        )
        
        self._tree_converted.heading("#0", text="File", anchor="w")
        self._tree_converted.heading("Score", text="Score", anchor="w")
        self._tree_converted.heading("Category", text="Category", anchor="w")
        
        self._tree_converted.column("#0", width=140, stretch=True)
        self._tree_converted.column("Score", width=60, stretch=False)
        self._tree_converted.column("Category", width=80, stretch=False)

        sb_conv = ttk.Scrollbar(tree_host, orient="vertical",
                           command=self._tree_converted.yview, style="File.Vertical.TScrollbar")
        self._tree_converted.configure(yscrollcommand=sb_conv.set)
        
        self._tree_converted.grid(row=0, column=0, sticky="nsew")
        sb_conv.grid(row=0, column=1, sticky="ns")

        self._style_converted_treeview()
        
        self._tree_converted.bind("<<TreeviewSelect>>", self._on_converted_tree_select)
        self._tree_converted.bind("<Delete>", lambda _e: self._remove_selected_converted())
        self._tree_converted.bind("<BackSpace>", lambda _e: self._remove_selected_converted())
        
        self._tree_converted.heading("#0", command=lambda: self._sort_converted("name"))
        self._tree_converted.heading("Score", command=lambda: self._sort_converted("score"))
        self._tree_converted.heading("Category", command=lambda: self._sort_converted("Category"))

        # ── Cleanup Assistant ────────────────────────────────────────────────
        cleanup_frame = ctk.CTkFrame(mp, fg_color="#1a1a2e", corner_radius=6)
        cleanup_frame.grid(row=6, column=0, padx=8, pady=(4, 8), sticky="ew")
        cleanup_frame.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(cleanup_frame, text="🧹 Cleanup Assistant", font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3").grid(row=0, column=0, columnspan=2, padx=8, pady=(4, 0), sticky="w")
        
        ctk.CTkButton(cleanup_frame, text="Trash Red (<=30%)", fg_color="#e74c3c", hover_color="#c0392b", height=24, font=ctk.CTkFont(size=11), command=lambda: self._cleanup_by_score(30)).grid(row=1, column=0, padx=(8, 2), pady=(4, 6), sticky="ew")
        ctk.CTkButton(cleanup_frame, text="Trash <=50%", fg_color="#e67e22", hover_color="#d35400", height=24, font=ctk.CTkFont(size=11), command=lambda: self._cleanup_by_score(50)).grid(row=1, column=1, padx=(2, 8), pady=(4, 6), sticky="ew")

        # Custom cleanup
        custom_frame = ctk.CTkFrame(cleanup_frame, fg_color="transparent")
        custom_frame.grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 6), sticky="ew")
        custom_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(custom_frame, text="Trash <=", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0,4))
        
        self.app_state.v_cleanup_custom = tk.StringVar(value="70")
        custom_entry = ctk.CTkEntry(custom_frame, textvariable=self.app_state.v_cleanup_custom, width=40, height=24)
        custom_entry.grid(row=0, column=1, sticky="w")
        
        ctk.CTkLabel(custom_frame, text="%", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(2,4))
        ctk.CTkButton(custom_frame, text="Trash Custom", fg_color="#8e44ad", hover_color="#732d91", height=24, width=80, font=ctk.CTkFont(size=11), command=self._cleanup_custom).grid(row=0, column=3, padx=(4,0))

        # ── Destination Folder ──────────────────────────────────────────────
        dest_frame = ctk.CTkFrame(mp, fg_color="transparent")
        dest_frame.grid(row=7, column=0, padx=8, pady=(0, 8), sticky="ew")
        dest_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(dest_frame, text="📤 Output / Destination folder", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=4, pady=(2, 2), sticky="w"
        )
        
        of = ctk.CTkFrame(dest_frame, fg_color="transparent")
        of.grid(row=1, column=0, columnspan=2, sticky="ew")
        of.grid_columnconfigure(0, weight=1)
        
        ctk.CTkEntry(
            of, textvariable=self.app_state.v_output_dir,
            placeholder_text="(same folder as source)", height=28
        ).grid(row=0, column=0, padx=(4, 2), sticky="ew")
        
        ctk.CTkButton(
            of, text="…", width=28, height=28, command=self.browse_output
        ).grid(row=0, column=1, padx=(0, 4))

        ctk.CTkButton(
            dest_frame, text="🚚 Move Converted & Clear List",
            height=28, command=self._move_and_clear_converted,
            fg_color="#1a4f7a", hover_color="#1a618d", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=2, column=0, columnspan=2, padx=4, pady=(6, 4), sticky="ew")

    def _style_converted_treeview(self):
        s = ttk.Style()
        s.configure("Converted.Treeview",
                    background="#12121f", foreground="#aaaacc",
                    fieldbackground="#12121f", borderwidth=0,
                    rowheight=26, font=("Helvetica", 11))
        s.map("Converted.Treeview",
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", "#ffffff")])
        s.configure("Converted.Treeview.Heading", background="#1a1a2e", foreground="#ffffff", font=("Helvetica", 11, "bold"))
        
        # Tags for colors
        self._tree_converted.tag_configure("Bad", foreground="#e74c3c")
        self._tree_converted.tag_configure("Poor", foreground="#e67e22")
        self._tree_converted.tag_configure("Acceptable", foreground="#f1c40f")
        self._tree_converted.tag_configure("Good", foreground="#2ecc71")
        self._tree_converted.tag_configure("Excellent", foreground="#88ff88")
        s.configure("Converted.Treeview.Heading", background="#1a1a2e", foreground="#ffffff", font=("Helvetica", 11, "bold"))
        
        # Tags for colors
        self._tree_converted.tag_configure("Excellent", foreground="#2ecc71")
        self._tree_converted.tag_configure("Good", foreground="#88dd88")
        self._tree_converted.tag_configure("Acceptable", foreground="#f1c40f")
        self._tree_converted.tag_configure("Poor", foreground="#e67e22")
        self._tree_converted.tag_configure("Bad", foreground="#e74c3c")
        self._tree_converted.tag_configure("Unknown", foreground="#aaaaaa")
        s.map("Converted.Treeview",
              background=[("selected", "#1e3a5f")],
              foreground=[("selected", "#ffffff")])

    def _open_advanced_settings(self):
        # We will dispatch an event or just open the toplevel directly
        # Since we have reference to app_state, maybe SettingsPanel is self-contained.
        from src.ui.settings.settings_panel import SettingsWindow
        SettingsWindow(self, self.app_state)

    def _on_target_preset_change(self, preset):
        if preset != "Custom":
            width, height = map(int, preset.split(" ")[0].split("x"))
            self.app_state.v_target_width.set(width)
            self.app_state.v_target_height.set(height)
            self._custom_res_frame.grid_forget()
        else:
            self._custom_res_frame.grid(row=2, column=0, columnspan=2, pady=4, sticky="ew")

    def _update_converted_count(self):
        n = len(self._converted_data)
        self._converted_count_lbl.configure(text=f"{n} file{'s' if n != 1 else ''}" if n else "empty")

    def _add_converted_file(self, path, score_result):
        if path in self._converted_paths:
            return
            
        name = Path(path).name
        disp = (name[:20] + "…") if len(name) > 22 else name
        
        score_val = score_result.get("score", 0)
        rating = score_result.get("rating", "Unknown")
        color = score_result.get("color", "")
        
        score_str = f"{color} {score_val}%"
        
        iid = self._tree_converted.insert("", "end", text=f" {disp}", values=(score_str, rating), tags=(rating,))
        
        # Store metadata
        self._converted_data[iid] = {
            "path": path,
            "score": score_val,
            "rating": rating,
            "color": color,
            "reasons": score_result.get("reasons", [])
        }
        self._converted_paths.add(path)
        self._update_converted_count()
        self._update_statistics()

    def _on_converted_tree_select(self, event=None):
        sel = self._tree_converted.selection()
        if not sel:
            return
        iid = self._tree_converted.focus() or sel[0]
        if iid not in sel:
            iid = sel[0]
            
        if iid == self._selected_converted_iid:
            return
            
        self._selected_converted_iid = iid
        
        # Deselect pending files if any
        if hasattr(self, "_tree") and self._tree.selection():
            self._tree.selection_remove(self._tree.selection())
            self._selected_iid = ""
        
        data = self._converted_data.get(iid)
        if data:
            path = data["path"]
            # Trigger preview via EventBus → PreviewPanel._on_source_changed
            EventBus.publish(EventType.PREVIEW_SOURCE_CHANGED, {
                "path": path,
                "is_converted": True,
                "converted_data": data,
            })

    def _remove_selected_converted(self):
        sel = self._tree_converted.selection()
        if not sel:
            return
        for iid in sel:
            data = self._converted_data.pop(iid, None)
            if data:
                self._converted_paths.discard(data["path"])
            self._tree_converted.delete(iid)
        self._update_converted_count()
        self._update_statistics()
        self._selected_converted_iid = ""
        self._clear_preview_via_bus()

    def _clear_converted(self):
        if not self._converted_data:
            return
        if not messagebox.askyesno("Clear List", "Clear all items from the converted list AND delete them from disk?"):
            return
            
        try:
            import send2trash
            safe_delete = send2trash.send2trash
        except ImportError:
            self._log("send2trash module missing. Deleting permanently instead.", "warning")
            safe_delete = os.remove
            
        for data in self._converted_data.values():
            path = data["path"]
            if os.path.exists(path):
                try: safe_delete(path)
                except: pass
            sidecar = path + ".scores.json"
            if os.path.exists(sidecar):
                try: safe_delete(sidecar)
                except: pass

        children = self._tree_converted.get_children()
        if children:
            self._tree_converted.delete(*children)
        self._converted_data.clear()
        self._converted_paths.clear()
        self._update_converted_count()
        self._update_statistics()
        self._selected_converted_iid = ""
        
        # Clear the preview panel
        self._clear_preview_via_bus()


    def _move_and_clear_converted(self):
        out_dir = self.app_state.v_output_dir.get().strip()
        if not out_dir:
            messagebox.showerror("Error", "Please select an output folder first.")
            return
        
        if not os.path.exists(out_dir):
            messagebox.showerror("Error", f"Output folder does not exist:\n{out_dir}")
            return
            
        if not self._converted_data:
            messagebox.showinfo("Move", "The converted list is empty.")
            return
            
        import shutil
        moved = 0
        errors = 0
        for iid, data in self._converted_data.items():
            src_path = data["path"]
            if os.path.exists(src_path):
                # Also move sidecar if it exists
                sidecar_path = src_path + ".scores.json"
                try:
                    shutil.move(src_path, os.path.join(out_dir, os.path.basename(src_path)))
                    if os.path.exists(sidecar_path):
                        shutil.move(sidecar_path, os.path.join(out_dir, os.path.basename(sidecar_path)))
                    moved += 1
                except Exception as e:
                    self._log(f"Failed to move {src_path}: {e}", "error")
                    errors += 1
                    
        if errors > 0:
            messagebox.showwarning("Move Completed", f"Moved {moved} files.\n{errors} errors occurred. See log.")
        else:
            self._log(f"🚚 Successfully moved {moved} files to {out_dir}")
            
        # Clear the list automatically
        children = self._tree_converted.get_children()
        if children:
            self._tree_converted.delete(*children)
        self._converted_data.clear()
        self._converted_paths.clear()
        self._update_converted_count()
        self._update_statistics()
        self._selected_converted_iid = ""

    def _on_filter_changed(self, *_):
        # Basic filtering logic
        search_query = self.app_state.v_search_converted.get().lower().strip()
        preset = self.app_state.v_filter_preset.get()
        
        min_score = 0
        if preset == "Excellent Only": min_score = 86
        elif preset == "Good And Above": min_score = 71
        elif preset == "Acceptable And Above": min_score = 51
        elif preset == "Poor And Above": min_score = 31

        # Re-populate tree based on filter
        children = self._tree_converted.get_children()
        if children:
            self._tree_converted.delete(*children)
        
        for iid, data in self._converted_data.items():
            path = data["path"]
            score = data["score"]
            rating = data["rating"]
            color = data["color"]
            
            name = Path(path).name
            if search_query and search_query not in name.lower():
                continue
                
            if score < min_score:
                continue
                
            disp = (name[:20] + "…") if len(name) > 22 else name
            score_str = f"{color} {score}%"
            self._tree_converted.insert("", "end", iid=iid, text=f" {disp}", values=(score_str, rating), tags=(rating,))

    def _sort_converted(self, col):
        if not hasattr(self, "_sort_dirs"):
            self._sort_dirs = {}
            
        # Toggle direction
        self._sort_dirs[col] = not self._sort_dirs.get(col, False)
        reverse = self._sort_dirs[col]
        
        items = [(self._tree_converted.set(k, col) if col != "name" else self._tree_converted.item(k)["text"], k) for k in self._tree_converted.get_children("")]
        
        if col == "score":
            def _get_score(val):
                try:
                    return int(val.split(" ")[1].replace("%", ""))
                except:
                    return 0
            items.sort(key=lambda x: _get_score(x[0]), reverse=reverse)
        elif col == "Category":
            # Sort by predefined category levels
            rating_order = {"Excellent": 5, "Good": 4, "Acceptable": 3, "Poor": 2, "Bad": 1, "Unknown": 0}
            items.sort(key=lambda x: rating_order.get(x[0], 0), reverse=reverse)
        else:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)
            
        for index, (val, k) in enumerate(items):
            self._tree_converted.move(k, "", index)

    def _update_statistics(self):
        counts = {"Excellent": 0, "Good": 0, "Acceptable": 0, "Poor": 0, "Bad": 0}
        total = len(self._converted_data)
        
        for data in self._converted_data.values():
            r = data.get("rating")
            if r in counts:
                counts[r] += 1
                
        self._stat_vars["total"].configure(text=f"Tot: {total}")
        self._stat_vars["Premium"].configure(text=f"🌟 {counts['Excellent']}")
        self._stat_vars["Good"].configure(text=f"🟢 {counts['Good']}")
        self._stat_vars["Acceptable"].configure(text=f"🟡 {counts['Acceptable']}")
        self._stat_vars["Poor"].configure(text=f"🟠 {counts['Poor']}")
        self._stat_vars["Bad"].configure(text=f"🔴 {counts['Bad']}")

    def _cleanup_custom(self):
        try:
            max_score = int(self.app_state.v_cleanup_custom.get())
            self._cleanup_by_score(max_score)
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid percentage number.")

    def _cleanup_by_score(self, max_score):
        to_remove = []
        for iid, data in self._converted_data.items():
            if data["score"] <= max_score:
                to_remove.append((iid, data["path"]))
                
        if not to_remove:
            messagebox.showinfo("Cleanup", f"No files found with score <= {max_score}%")
            return
            
        if messagebox.askyesno("Confirm Cleanup", f"Move {len(to_remove)} files to trash?"):
            try:
                import send2trash
                safe_delete = send2trash.send2trash
            except ImportError:
                self._log("send2trash module missing. Deleting permanently instead.", "warning")
                safe_delete = os.remove
                
            deleted = 0
            for iid, path in to_remove:
                try:
                    if os.path.exists(path):
                        safe_delete(path)
                except Exception as e:
                    self._log(f"Failed to trash {path}: {e}", "warning")
                    
                # Also trash the sidecar if it exists
                sidecar_path = path + ".scores.json"
                if os.path.exists(sidecar_path):
                    try:
                        safe_delete(sidecar_path)
                    except Exception:
                        pass
                        
                self._converted_paths.discard(path)
                if iid in self._converted_data:
                    del self._converted_data[iid]
                # remove from tree
                if self._tree_converted.exists(iid):
                    self._tree_converted.delete(iid)
                    
                deleted += 1
                    
            self._update_converted_count()
            self._update_statistics()
            self._log(f"🧹 Trashed {deleted} files.")
            
            # Clear preview if the selected item was trashed
            if self._selected_converted_iid in [iid for iid, _ in to_remove]:
                self._selected_converted_iid = ""
                self._clear_preview_via_bus()

    # ══════════════════════════════════════════════════════════════════════════
    #  LOGGING helper
    # ══════════════════════════════════════════════════════════════════════════

    def _clear_preview_via_bus(self):
        """Stop and reset all PreviewPanel animations via EventBus."""
        for action in ("stop_src", "stop_auto", "stop_dmd",
                       "idle_src", "idle_auto", "idle_dmd"):
            EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED, {"action": action})

    def _log(self, message: str, level: str = "info"):
        """Log to Python logger (and optionally forward to EventBus)."""
        lvl = {"debug": logging.DEBUG, "info": logging.INFO,
               "warning": logging.WARNING, "error": logging.ERROR}.get(level.lower(), logging.INFO)
        logger.log(lvl, message)
        try:
            from src.ui.events.event_bus import EventBus, EventType
            EventBus.publish(EventType.CONVERSION_PROGRESS, {"log": message, "level": level})
        except Exception:
            pass


