import tkinter as tk
import customtkinter as ctk
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

        def slider_row(label, var, from_, to, fmt="{:.1f}", suffix="", steps=None):
            f = ctk.CTkFrame(self, fg_color="transparent")
            f.pack(fill="x", padx=8, pady=2)
            f.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(f, text=label, width=135, anchor="w",
                         font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
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
                if not _editing[0]:
                    entry_sv.set(_lbl_txt())

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            return sl

        section("🎨  Content mode")
        mr = ctk.CTkFrame(self, fg_color="transparent")
        mr.pack(fill="x", padx=8, pady=2)
        mr.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mr, text="Mode", width=135, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._mode_menu = ctk.CTkOptionMenu(
            mr, variable=self.app_state.v_mode,
            values=["pixel_art", "anime", "cinema", "custom"],
            width=180
        )
        self._mode_menu.grid(row=0, column=1, padx=4, sticky="w")
        
        def _update_mode_menu_state(*_):
            self._mode_menu.configure(state="normal")
        
        self.app_state.v_auto_color_enabled.trace_add("write", _update_mode_menu_state)
        self.app_state.v_let_me_handle_it.trace_add("write", _update_mode_menu_state)
        _update_mode_menu_state()

        section("⚡  Parallelism")
        slider_row("Workers (CPU)", self.app_state.v_workers, 1, 16, "{:.0f}", " workers", steps=15)

        section("📜  Scroll")
        slider_row("Scroll speed",    self.app_state.v_scroll_speed,        4.0, 80.0, "{:.0f}", " px/s")
        slider_row("Top crop (%)",    self.app_state.v_top_crop,      0.0,  0.5, "{:.0%}")
        slider_row("Bottom crop (%)", self.app_state.v_bottom_crop,   0.0,  0.5, "{:.0%}")
        slider_row("Scroll cycles",   self.app_state.v_scroll_cycles, 0.0,  5.0, "{:.2f}", " cyc")

        section("🎬  Render FPS")
        slider_row("FPS minimum", self.app_state.v_fps_min, 5.0,  30.0, "{:.1f}", " fps")
        slider_row("FPS maximum", self.app_state.v_fps_max, 10.0, 60.0, "{:.1f}", " fps")
