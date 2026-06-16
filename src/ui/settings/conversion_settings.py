import customtkinter as ctk
import tkinter as tk
import re

class ConversionSettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        def section(text):
            ctk.CTkLabel(
                self, text=text, font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#7ec8e3"
            ).pack(fill="x", padx=8, pady=(12, 2), anchor="w")

        def slider_row(label, var, from_, to, fmt="{:.1f}", suffix="", steps=None, tooltip_text=None):
            f = ctk.CTkFrame(self, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=2)
            f.grid_columnconfigure(1, weight=1)
            lbl = ctk.CTkLabel(f, text=label, width=135, anchor="w",
                         font=ctk.CTkFont(size=12))
            lbl.grid(row=0, column=0, padx=(4, 6))
            if tooltip_text:
                from src.ui.widgets import ToolTip
                ToolTip(lbl, tooltip_text)
            kw = dict(from_=from_, to=to, variable=var)
            if steps is not None:
                kw["number_of_steps"] = steps
            sl = ctk.CTkSlider(f, **kw)
            sl.grid(row=0, column=1, sticky="ew", padx=4)

            def _lbl_txt():
                return fmt.format(var.get()) + suffix

            entry_sv = tk.StringVar(value=_lbl_txt())
            entry = ctk.CTkEntry(f, textvariable=entry_sv, width=72, justify="right",
                                 font=ctk.CTkFont(size=11))
            entry.grid(row=0, column=2, padx=(4, 4))

            _editing = [False]

            def _on_focus_in(_e):
                _editing[0] = True

            def _commit(*_):
                _editing[0] = False
                raw = entry_sv.get().strip()
                try:
                    m = re.match(r'^([+-]?\d*\.?\d+)', raw)
                    val = float(m.group(1)) if m else float(raw)
                    val = max(from_, min(to, val))
                    var.set(val)
                except (ValueError, AttributeError):
                    pass
                entry_sv.set(_lbl_txt())

            def _var_changed(*_):
                try:
                    if entry.winfo_exists() and not _editing[0]:
                        entry_sv.set(_lbl_txt())
                except Exception:
                    pass

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            sl.entry_widget = entry
            return sl

        section("🎨  Content mode")
        mr = ctk.CTkFrame(self, fg_color="transparent")
        mr.pack(fill="x", padx=8, pady=2)
        mr.grid_columnconfigure(1, weight=1)
        lbl_mode = ctk.CTkLabel(mr, text="Mode", width=135, anchor="w",
                     font=ctk.CTkFont(size=12))
        lbl_mode.grid(row=0, column=0, padx=(4, 6))
        from src.ui.widgets import ToolTip
        ToolTip(lbl_mode, "Selects the visual processing mode.\n'cinema' = deep blacks, smooth colors\n'pixel_art' = sharp and vibrant\n'anime' = saturated and bright\n'custom' = unlocks Advanced Settings")
        self._mode_menu = ctk.CTkOptionMenu(
            mr, variable=self.app_state.v_mode,
            values=["pixel_art", "anime", "cinema", "custom"],
            width=180
        )
        self._mode_menu.grid(row=0, column=1, padx=4, sticky="w")
        
        def _update_mode_menu_state(*_):
            try:
                if self.winfo_exists() and self._mode_menu.winfo_exists():
                    self._mode_menu.configure(state="normal")
            except Exception:
                pass
        
        self.app_state.v_auto_color_enabled.trace_add("write", _update_mode_menu_state)
        self.app_state.v_let_me_handle_it.trace_add("write", _update_mode_menu_state)
        _update_mode_menu_state()

        section("⚡  Parallelism")
        workers_frame = ctk.CTkFrame(self, fg_color="transparent")
        workers_frame.pack(fill="x", padx=8, pady=2)
        
        cb_auto_workers = ctk.CTkCheckBox(
            workers_frame,
            text="Auto",
            variable=self.app_state.v_auto_workers,
            font=ctk.CTkFont(size=12), text_color="#aaddaa", width=60
        )
        cb_auto_workers.pack(side="left", padx=(0, 10))
        ToolTip(cb_auto_workers, "Automatically determines the optimal number of CPU workers based on your system.")

        
        # Manually create the slider for workers so we can disable it
        wf_inner = ctk.CTkFrame(workers_frame, fg_color="transparent")
        wf_inner.pack(side="left", fill="x", expand=True)
        wf_inner.grid_columnconfigure(1, weight=1)
        lbl_workers = ctk.CTkLabel(wf_inner, text="Workers (CPU)", width=100, anchor="w",
                     font=ctk.CTkFont(size=12))
        lbl_workers.grid(row=0, column=0, padx=(4, 6))
        ToolTip(lbl_workers, "Number of concurrent CPU threads to use during conversion.\nHigher is faster but uses more system resources.")
                     
        sl_workers = ctk.CTkSlider(wf_inner, from_=1, to=16, number_of_steps=15, variable=self.app_state.v_workers)
        sl_workers.grid(row=0, column=1, sticky="ew", padx=4)
        
        workers_lbl_sv = tk.StringVar(value="{:.0f} workers".format(self.app_state.v_workers.get()))
        workers_entry = ctk.CTkEntry(wf_inner, textvariable=workers_lbl_sv, width=72, justify="right",
                             font=ctk.CTkFont(size=11))
        workers_entry.grid(row=0, column=2, padx=(4, 4))
        
        def _update_workers_lbl(*_):
            if not getattr(workers_entry, "_is_focused", False):
                workers_lbl_sv.set("{:.0f} workers".format(self.app_state.v_workers.get()))
        self.app_state.v_workers.trace_add("write", _update_workers_lbl)
        
        def _commit_workers(*_):
            workers_entry._is_focused = False
            raw = workers_lbl_sv.get().strip()
            import re
            try:
                m = re.match(r'^([+-]?\d*\.?\d+)', raw)
                val = float(m.group(1)) if m else float(raw)
                val = max(1, min(16, val))
                self.app_state.v_workers.set(val)
            except Exception:
                pass
            _update_workers_lbl()
            
        workers_entry.bind("<FocusIn>", lambda e: setattr(workers_entry, "_is_focused", True))
        workers_entry.bind("<FocusOut>", _commit_workers)
        workers_entry.bind("<Return>", _commit_workers)
        
        def _update_workers_state(*_):
            try:
                state = "disabled" if self.app_state.v_auto_workers.get() else "normal"
                sl_workers.configure(state=state)
                workers_entry.configure(state=state)
            except Exception:
                pass
                
        self.app_state.v_auto_workers.trace_add("write", _update_workers_state)
        _update_workers_state()

        section("📐  Dimensions")
        dim_row = ctk.CTkFrame(self, fg_color="transparent")
        dim_row.pack(fill="x", padx=8, pady=2)
        cb_ratio_bypass = ctk.CTkCheckBox(
            dim_row,
            text="Bypass framing for equivalent ratio",
            variable=self.app_state.v_smart_ratio_bypass,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        cb_ratio_bypass.pack(side="left")

        from src.ui.widgets import _InfoBadge
        badge = _InfoBadge(dim_row)
        badge.configure(text="Bypass framing/cropping and apply only Render FPS and Color Boost when the source video ratio matches the target ratio. By definition, selecting 'Original' resolution will always trigger this bypass.")
        badge.pack(side="left", padx=5)

        section("📜  Scroll")
        self._scroll_sliders = []
        self._scroll_sliders.append(slider_row("Scroll speed",    self.app_state.v_scroll_speed,        4.0, 80.0, "{:.0f}", " px/s", tooltip_text="Speed of the automatic vertical panning (pixels per second)."))
        self._scroll_sliders.append(slider_row("Top crop (%)",    self.app_state.v_top_crop,      0.0,  0.5, "{:.0%}", tooltip_text="Percentage of the top of the video to ignore (e.g. 10% = ignore top 10%)."))
        self._scroll_sliders.append(slider_row("Bottom crop (%)", self.app_state.v_bottom_crop,   0.0,  0.5, "{:.0%}", tooltip_text="Percentage of the bottom to ignore (useful for hiding HUDs or subtitles)."))
        self._scroll_sliders.append(slider_row("Scroll cycles",   self.app_state.v_scroll_cycles, 0.0,  5.0, "{:.2f}", " cyc", tooltip_text="Number of times to bounce the vertical pan up and down during the video's duration.\nA value of 1.0 means it pans down once."))

        def _update_scroll_state(*_):
            try:
                state = "disabled" if self.app_state.v_action_enabled.get() else "normal"
                for sl in self._scroll_sliders:
                    if sl and sl.winfo_exists():
                        sl.configure(state=state)
                        if hasattr(sl, "entry_widget") and sl.entry_widget.winfo_exists():
                            sl.entry_widget.configure(state=state)
            except Exception:
                pass
                
        self.app_state.v_action_enabled.trace_add("write", _update_scroll_state)
        _update_scroll_state()

        section("🎬  Render FPS")
        slider_row("FPS minimum", self.app_state.v_fps_min, 5.0,  30.0, "{:.1f}", " fps", tooltip_text="The lowest frame rate allowed for the output video/GIF.\nThe tool will drop frames down to this limit if possible to save file size.")
        slider_row("FPS maximum", self.app_state.v_fps_max, 10.0, 60.0, "{:.1f}", " fps", tooltip_text="The highest frame rate allowed.\nHigh FPS creates smoother animations but results in larger files.")
