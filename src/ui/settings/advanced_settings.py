import customtkinter as ctk

def adv_slider(par, label, var, from_, to, fmt="{:.2f}", suffix="",
               steps=None, is_int=False, tooltip_text=None):
    import tkinter as tk
    import re
    f = ctk.CTkFrame(par, fg_color="transparent")
    f.pack(fill="x", padx=10, pady=2)
    f.grid_columnconfigure(1, weight=1)
    lbl = ctk.CTkLabel(f, text=label, width=145, anchor="w",
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
        return (fmt.format(int(var.get())) if is_int else fmt.format(var.get())) + suffix

    entry_sv = tk.StringVar(value=_lbl_txt())
    entry = ctk.CTkEntry(f, textvariable=entry_sv, width=80, justify="right",
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
            if is_int:
                var.set(int(val))
            else:
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

class AdvancedSettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._adv_expanded = False
        self._build_ui()

    def _build_ui(self):
        self._adv_toggle_btn = ctk.CTkButton(
            self,
            text="🔧  Advanced Settings  ▼",
            command=self._toggle_advanced,
            fg_color="#1a1a2e", hover_color="#2a2a3e",
            anchor="w", height=34, border_width=1,
            border_color="#3a3a5a",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#aaaadd",
        )
        self._adv_toggle_btn.pack(fill="x", padx=8, pady=(14, 0))

        self._adv_frame = ctk.CTkFrame(self, fg_color="#0f0f20", corner_radius=6)
        self._build_advanced_content(self._adv_frame)

    def _toggle_advanced(self):
        self._adv_expanded = not self._adv_expanded
        if self._adv_expanded:
            self._adv_frame.pack(fill="x", padx=8, pady=(0, 8))
            self._adv_toggle_btn.configure(text="🔧  Advanced Settings  ▲")
        else:
            self._adv_frame.pack_forget()
            self._adv_toggle_btn.configure(text="🔧  Advanced Settings  ▼")

    def _build_advanced_content(self, parent):
        ctk.CTkLabel(
            parent,
            text="ℹ️  All settings here are hidden by default.\n"
                 "    Default values reproduce the standard v2.0 output unchanged.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=12, pady=(8, 4), anchor="w")

        # ── SECTION 3: POSITIONING ────────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  📍  Positioning",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        scroll_row = ctk.CTkFrame(parent, fg_color="transparent")
        scroll_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_scroll_enabled = ctk.CTkCheckBox(
            scroll_row,
            text="Auto vertical scroll  (default — matches standard behaviour)",
            variable=self.app_state.v_scroll_enabled,
            command=self._on_scroll_enabled_change,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_scroll_enabled.pack(side="left")

        # Manual positioning frame (hidden when scroll is on)
        self._manual_frame = ctk.CTkFrame(parent, fg_color="#16213e", corner_radius=6)

        ctk.CTkLabel(
            self._manual_frame,
            text="✋  Manual frame — auto-scroll is OFF\n"
                 "    Zoom first, then adjust X / Y to choose the visible 128×32 window.\n"
                 "    DMD preview auto-refreshes ~2 s after you stop moving sliders.",
            text_color="#7799aa", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=12, pady=(8, 6), anchor="w")

        adv_slider(self._manual_frame, "Zoom",     self.app_state.v_zoom,     0.5, 4.0,
                   "{:.2f}", "×", steps=70)
        adv_slider(self._manual_frame, "X offset", self.app_state.v_manual_x, 0,  512,
                   "{:.0f}", " px", steps=512, is_int=True)
        adv_slider(self._manual_frame, "Y offset", self.app_state.v_manual_y, 0,  512,
                   "{:.0f}", " px", steps=512, is_int=True)

        self._on_scroll_enabled_change()

        def _update_adv_scroll_state(*_):
            try:
                state = "disabled" if self.app_state.v_action_enabled.get() else "normal"
                if self._cb_scroll_enabled and self._cb_scroll_enabled.winfo_exists():
                    self._cb_scroll_enabled.configure(state=state)
            except Exception:
                pass

        self.app_state.v_action_enabled.trace_add("write", _update_adv_scroll_state)
        _update_adv_scroll_state()
        # ── SECTION 4: VISUAL EFFECTS ─────────────────────────────────────────
        ctk.CTkLabel(
            parent, text="━━  ✨  Visual Effects",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(14, 4), anchor="w")

        ctk.CTkLabel(
            parent,
            text="All effects are OFF by default (values = 0 / unchecked).\n"
                 "Non-zero values add extra ffmpeg filter passes.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 6), anchor="w")

        adv_slider(parent, "Hue shift",       self.app_state.v_hue_shift,       -180.0, 180.0,
                   "{:.0f}", "°", steps=360)
        adv_slider(parent, "Noise reduction", self.app_state.v_noise_reduction,   0.0,   8.0,
                   "{:.1f}", "")
        adv_slider(parent, "Film grain",      self.app_state.v_film_grain,        0,    50,
                   "{:.0f}", "", steps=50, is_int=True)

        vig_row = ctk.CTkFrame(parent, fg_color="transparent")
        vig_row.pack(fill="x", padx=14, pady=(4, 8))
        self._cb_vignette = ctk.CTkCheckBox(
            vig_row,
            text="Vignette  (darkens edges — default OFF)",
            variable=self.app_state.v_vignette, font=ctk.CTkFont(size=12),
        )
        self._cb_vignette.pack(side="left")

    def _on_scroll_enabled_change(self):
        if self.app_state.v_scroll_enabled.get():
            self._manual_frame.pack_forget()
        else:
            self._manual_frame.pack(fill="x", padx=10, pady=(4, 4))
