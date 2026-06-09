import customtkinter as ctk
import tkinter as tk
import re

def adv_slider(par, label, var, from_, to, fmt="{:.2f}", suffix="",
               steps=None, is_int=False, lmh=True, auto_var=None):
    f = ctk.CTkFrame(par, fg_color="transparent")
    f.pack(fill="x", padx=10, pady=2)
    f.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(f, text=label, width=145, anchor="w",
                 font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
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
        par.focus()

    def _on_return(_e):
        _commit()

    def _on_focus_out(_e):
        _commit()

    entry.bind("<Return>", _on_return)
    entry.bind("<FocusIn>", _on_focus_in)
    entry.bind("<FocusOut>", _on_focus_out)

    def _var_changed(*_):
        if not _editing[0]:
            entry_sv.set(_lbl_txt())
            
    var.trace_add("write", _var_changed)
    
    if auto_var is not None:
        def _toggle_slider(*_):
            state = "disabled" if auto_var.get() else "normal"
            sl.configure(state=state)
        auto_var.trace_add("write", _toggle_slider)
        
    return sl

class TextOverlayPopup(ctk.CTkToplevel):
    def __init__(self, master, app_state):
        super().__init__(master)
        self.title("Text Overlay Settings")
        self.geometry("450x380")
        self.resizable(False, False)
        
        # Keep on top but NOT modal (grab_set blocks after() callbacks during background renders)
        self.attributes("-topmost", True)

        self._app_state = app_state
        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkFrame(self, fg_color="#16213e", corner_radius=6)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        text_content_row = ctk.CTkFrame(container, fg_color="transparent")
        text_content_row.pack(fill="x", padx=10, pady=6)
        text_content_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_content_row, text="Text Content", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_content_entry = ctk.CTkEntry(
            text_content_row, textvariable=self._app_state.v_text_content, width=200
        )
        self._text_content_entry.grid(row=0, column=1, sticky="ew", padx=4)

        adv_slider(container, "Font Size", self._app_state.v_text_font_size, 4, 32,
                   "{:.0f}", " px", steps=28, is_int=True, lmh=False)

        text_color_row = ctk.CTkFrame(container, fg_color="transparent")
        text_color_row.pack(fill="x", padx=10, pady=6)
        text_color_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_color_row, text="Text Color", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_color_menu = ctk.CTkOptionMenu(
            text_color_row,
            variable=self._app_state.v_text_color,
            values=["white", "yellow", "red", "green", "blue"],
            width=200,
        )
        self._text_color_menu.grid(row=0, column=1, sticky="w", padx=4)

        text_position_row = ctk.CTkFrame(container, fg_color="transparent")
        text_position_row.pack(fill="x", padx=10, pady=6)
        text_position_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_position_row, text="Text Position", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_position_menu = ctk.CTkOptionMenu(
            text_position_row,
            variable=self._app_state.v_text_position,
            values=["top_left", "top_center", "top_right", "middle_left", "middle_center", "middle_right", "bottom_left", "bottom_center", "bottom_right"],
            width=200,
        )
        self._text_position_menu.grid(row=0, column=1, sticky="w", padx=4)

        text_font_row = ctk.CTkFrame(container, fg_color="transparent")
        text_font_row.pack(fill="x", padx=10, pady=6)
        text_font_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_font_row, text="Font", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        _available_fonts = [
            "HelvetiPixel.ttf", "PixelMordred.ttf", "BitCasual.ttf",
            "CursivePixel.ttf", "justabit.ttf", "KarenBook.ttf",
            "OldWizard.ttf", "OrdinaryBasis.ttf", "Quintet.ttf", "TimesNewPixel.ttf",
        ]
        self._text_font_menu = ctk.CTkOptionMenu(
            text_font_row,
            variable=self._app_state.v_text_font_file,
            values=_available_fonts,
            width=200,
        )
        self._text_font_menu.grid(row=0, column=1, sticky="w", padx=4)

        # ── Text Style ────────────────────────────────────────────────────────
        text_style_row = ctk.CTkFrame(container, fg_color="transparent")
        text_style_row.pack(fill="x", padx=10, pady=6)
        text_style_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_style_row, text="Text Style", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_style_menu = ctk.CTkOptionMenu(
            text_style_row,
            variable=self._app_state.v_text_style,
            values=["outline", "bold", "shadow", "none"],
            width=200,
        )
        self._text_style_menu.grid(row=0, column=1, sticky="w", padx=4)

        # ── Text Animation (Text Magic!) ──────────────────────────────────────
        text_anim_row = ctk.CTkFrame(container, fg_color="transparent")
        text_anim_row.pack(fill="x", padx=10, pady=6)
        text_anim_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(text_anim_row, text="Animation (Magic!)", width=145, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color="#ffff99").grid(row=0, column=0, padx=(4, 6))
            
        self._text_anim_menu = ctk.CTkOptionMenu(
            text_anim_row,
            variable=self._app_state.v_text_animation,
            values=["none", "blink", "scroll_left", "scroll_up"],
            width=200,
        )
        self._text_anim_menu.grid(row=0, column=1, sticky="w", padx=4)

        # ── Background box ────────────────────────────────────────────────────
        bg_row = ctk.CTkFrame(container, fg_color="transparent")
        bg_row.pack(fill="x", padx=10, pady=(10, 2))
        self._text_bg_cb = ctk.CTkCheckBox(
            bg_row,
            text="Background box (dark box behind text)",
            variable=self._app_state.v_text_bg,
            command=self._on_text_bg_toggle,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._text_bg_cb.pack(side="left")

        # Opacity slider
        self._text_bg_opacity_frame = ctk.CTkFrame(container, fg_color="transparent")
        self._text_bg_opacity_frame.pack(fill="x", padx=10, pady=2)
        self._text_bg_opacity_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._text_bg_opacity_frame, text="Box opacity", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._text_bg_opacity_slider = ctk.CTkSlider(
            self._text_bg_opacity_frame,
            from_=10, to=100, number_of_steps=90,
            variable=self._app_state.v_text_bg_opacity,
        )
        self._text_bg_opacity_slider.grid(row=0, column=1, sticky="ew", padx=4)
        self._text_bg_opacity_lbl = ctk.CTkLabel(
            self._text_bg_opacity_frame,
            text="%d %%" % self._app_state.v_text_bg_opacity.get(),
            width=60, anchor="e", font=ctk.CTkFont(size=11),
        )
        self._text_bg_opacity_lbl.grid(row=0, column=2, padx=(4, 4))
        self._app_state.v_text_bg_opacity.trace_add(
            "write",
            lambda *_: self._text_bg_opacity_lbl.configure(
                text="%d %%" % self._app_state.v_text_bg_opacity.get()
            ),
        )
        self._on_text_bg_toggle()

        close_btn = ctk.CTkButton(self, text="Close", command=self.destroy, width=100)
        close_btn.pack(pady=10)

    def _on_text_bg_toggle(self):
        if self._app_state.v_text_bg.get():
            self._text_bg_opacity_frame.pack(fill="x", padx=10, pady=2)
        else:
            self._text_bg_opacity_frame.pack_forget()

class AutoActionPopup(ctk.CTkToplevel):
    def __init__(self, master, app_state):
        super().__init__(master)
        self.title("Auto-Action & Video Cutter Settings")
        self.geometry("500x550")
        self.resizable(False, False)
        
        # Make it a modal tool window
        self.attributes("-topmost", True)
        self.grab_set()

        self._app_state = app_state
        self._build_ui()

    def _build_ui(self):
        container = ctk.CTkFrame(self, fg_color="#16213e", corner_radius=6)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Auto-Cutter (Highlights Extractor) ────────────────────────────────
        cutter_lbl = ctk.CTkLabel(
            container, text="🎬 Auto-Cutter (Extract Highlights)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#ffff99"
        )
        cutter_lbl.pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        cutter_row = ctk.CTkFrame(container, fg_color="transparent")
        cutter_row.pack(fill="x", padx=14, pady=2)
        self._cb_auto_cutter_enabled = ctk.CTkCheckBox(
            cutter_row,
            text="Enable Auto-Cutter for long videos",
            variable=self._app_state.v_auto_cutter_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_auto_cutter_enabled.pack(side="left")

        adv_slider(container, "Top N Highlights", self._app_state.v_auto_cutter_top_n, 1, 10,
                   "{:.0f}", "", steps=9, is_int=True, lmh=False)

        ctk.CTkLabel(
            container,
            text="    Automatically scans the video and extracts the best moments.\n    Creates multiple GIFs if Top N > 1.",
            text_color="#667788", font=ctk.CTkFont(size=10), justify="left",
        ).pack(padx=14, pady=(0, 10), anchor="w")

        # ── Auto-Action Formatting ────────────────────────────────────────────
        action_lbl = ctk.CTkLabel(
            container, text="🎯 Auto-Action Framing",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        )
        action_lbl.pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        action_row = ctk.CTkFrame(container, fg_color="transparent")
        action_row.pack(fill="x", padx=14, pady=2)
        self._cb_auto_action_enabled = ctk.CTkCheckBox(
            action_row,
            text="Enable cinematic auto-framing",
            variable=self._app_state.v_auto_action_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_auto_action_enabled.pack(side="left")

        mode_row = ctk.CTkFrame(container, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=6)
        mode_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mode_row, text="Detection mode", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._action_detector_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self._app_state.v_action_detector,
            values=["person", "motion", "hybrid", "center"],
            width=200,
        )
        self._action_detector_menu.grid(row=0, column=1, sticky="w", padx=4)

        adv_slider(container, "Action Tracking", self._app_state.v_action_strength, 0.0, 1.0,
                   "{:.2f}", "", auto_var=self._app_state.v_action_auto_strength)
                   
        adv_slider(container, "Camera Smoothness", self._app_state.v_action_smoothness, 0.50, 0.99,
                   "{:.2f}", "", auto_var=self._app_state.v_action_auto_smoothness)

        # ── Smart Features ────────────────────────────────────────────────────
        smart_lbl = ctk.CTkLabel(
            container, text="🧠 Smart Features",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        )
        smart_lbl.pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        self._cb_smart_crop = ctk.CTkCheckBox(
            container,
            text="Smart Crop (Dynamically adjust vertical framing)",
            variable=self._app_state.v_action_smart_auto_crop,
            font=ctk.CTkFont(size=12), text_color="#dddddd"
        )
        self._cb_smart_crop.pack(padx=14, pady=4, anchor="w")

        self._cb_bg_sub = ctk.CTkCheckBox(
            container,
            text="Background Subtraction (Isolate subjects)",
            variable=self._app_state.v_bg_sub_enable,
            font=ctk.CTkFont(size=12), text_color="#dddddd"
        )
        self._cb_bg_sub.pack(padx=14, pady=4, anchor="w")

        self._cb_visibility_score = ctk.CTkCheckBox(
            container,
            text="Calculate Visibility Score (DMD Quality)",
            variable=self._app_state.v_dmd_visibility_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#dddddd"
        )
        self._cb_visibility_score.pack(padx=14, pady=4, anchor="w")
        
        self._cb_readability_score = ctk.CTkCheckBox(
            container,
            text="Calculate Text Readability Score",
            variable=self._app_state.v_dmd_readability_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#dddddd"
        )
        self._cb_readability_score.pack(padx=14, pady=4, anchor="w")

        close_btn = ctk.CTkButton(self, text="Close", command=self.destroy, width=100)
        close_btn.pack(pady=10)
