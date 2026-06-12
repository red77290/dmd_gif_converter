import tkinter as tk
import customtkinter as ctk
import re
from src.ui.widgets import _InfoBadge

class AutoActionSettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._build_ui()

    @staticmethod
    def _safe_cfg(widget, **kw):
        """Configure a widget, silently ignoring TclError if it was already destroyed."""
        try:
            widget.configure(**kw)
            if hasattr(widget, "entry_widget"):
                widget.entry_widget.configure(**kw)
        except Exception:
            pass

    def _build_ui(self):
        parent = self
        
        def adv_slider(par, label, var, from_, to, fmt="{:.2f}", suffix="",
                       steps=None, is_int=False):
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

            def _var_changed(*_):
                if not _editing[0]:
                    entry_sv.set(_lbl_txt())

            var.trace_add("write", _var_changed)
            entry.bind("<FocusIn>",  _on_focus_in)
            entry.bind("<FocusOut>", _commit)
            entry.bind("<Return>",   _commit)
            
            # Removed lmh_widgets.extend from adv_slider itself
            sl.entry_widget = entry
            return sl

        ctk.CTkLabel(
            parent, text="━━  🎯  Auto Action Framing (pre-ffmpeg)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        auto_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_auto_action_enabled = ctk.CTkCheckBox(
            auto_row,
            text="Enable cinematic auto-framing before ffmpeg (default OFF)",
            variable=self.app_state.v_action_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_auto_action_enabled.pack(side="left")
        self.app_state.lmh_widgets.append(self._cb_auto_action_enabled)
        _b1 = _InfoBadge(auto_row)
        _b1.configure(text="Applies automatic cinematic camera panning and zooming to focus on the action.\n(Forced ON when Let me handle it is active)")
        _b1.pack(side="left", padx=(0, 8))

        # We will track all widgets in this panel that depend on v_action_enabled
        self._action_dependent_widgets = []
        
        def _add_dep(*widgets):
            self._action_dependent_widgets.extend(widgets)
            self.app_state.lmh_widgets.extend(widgets)

        mode_row = ctk.CTkFrame(parent, fg_color="transparent")
        mode_row.pack(fill="x", padx=10, pady=2)
        mode_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(mode_row, text="Detection mode", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._action_detector_menu = ctk.CTkOptionMenu(
            mode_row,
            variable=self.app_state.v_action_detector,
            values=["person", "motion", "hybrid", "center"],
            width=200,
        )
        self._action_detector_menu.grid(row=0, column=1, sticky="w", padx=4)
        _add_dep(self._action_detector_menu)

        row_frame = ctk.CTkFrame(parent, fg_color="transparent")
        row_frame.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_dmd_visibility_score_enabled = ctk.CTkCheckBox(
            row_frame,
            text="DMD Visibility",
            variable=self.app_state.v_action_dmd_visibility_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_dmd_visibility_score_enabled.pack(side="left")
        _add_dep(self._cb_dmd_visibility_score_enabled)

        self._cb_dmd_readability_score_enabled = ctk.CTkCheckBox(
            row_frame,
            text="DMD Readability",
            variable=self.app_state.v_action_dmd_readability_score_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_dmd_readability_score_enabled.pack(side="left", padx=(10, 0))
        _add_dep(self._cb_dmd_readability_score_enabled)
        _b2 = _InfoBadge(row_frame)
        _b2.configure(text="Limits automatic zooms based on the resulting image's visibility and readability on a DMD display.\n(Forced ON when Let me handle it is active)")
        _b2.pack(side="left", padx=(0, 8))

        self._slider_action_strength = adv_slider(parent, "Action strength", self.app_state.v_action_strength, 0.0, 1.0,
                   "{:.2f}", "", steps=100)
        _add_dep(self._slider_action_strength)
                   
        strength_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        strength_auto_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_auto_strength = ctk.CTkCheckBox(
            strength_auto_row,
            text="Auto strength  (overrides slider · detects game/anime type)",
            variable=self.app_state.v_action_auto_strength,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_strength.pack(side="left")
        _add_dep(self._cb_auto_strength)
        
        def _toggle_auto_strength(*_):
            state = "disabled" if self.app_state.v_action_auto_strength.get() else "normal"
            self._safe_cfg(self._slider_action_strength, state=state)
        self.app_state.v_action_auto_strength.trace_add("write", _toggle_auto_strength)

        self._slider_action_smoothness = adv_slider(parent, "Camera smooth", self.app_state.v_action_smoothness, 0.0, 0.98,
                   "{:.2f}", "", steps=98)
        _add_dep(self._slider_action_smoothness)
                   
        smoothness_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        smoothness_auto_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_auto_smoothness = ctk.CTkCheckBox(
            smoothness_auto_row,
            text="Auto smooth  (overrides slider · detects game/anime type)",
            variable=self.app_state.v_action_auto_smoothness,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_smoothness.pack(side="left")
        _add_dep(self._cb_auto_smoothness)

        def _toggle_auto_smoothness(*_):
            state = "disabled" if self.app_state.v_action_auto_smoothness.get() else "normal"
            self._safe_cfg(self._slider_action_smoothness, state=state)
        self.app_state.v_action_auto_smoothness.trace_add("write", _toggle_auto_smoothness)

        _add_dep(adv_slider(parent, "Zoom max", self.app_state.v_action_zoom_max, 1.0, 3.0,
                   "{:.2f}", "×", steps=100))
        _add_dep(adv_slider(parent, "ROI padding", self.app_state.v_action_padding, 0.0, 0.6,
                   "{:.2f}", "", steps=60))
        _add_dep(adv_slider(parent, "Intro panoramic", self.app_state.v_action_intro_duration, 0.0, 5.0,
                   "{:.1f}", " s", steps=50))

        ctk.CTkLabel(
            parent, text="━━  📐  Crop & Vertical Bias",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 2), anchor="w")

        smart_row = ctk.CTkFrame(parent, fg_color="transparent")
        smart_row.pack(fill="x", padx=14, pady=(2, 0))
        self._cb_smart_auto_crop = ctk.CTkCheckBox(
            smart_row,
            text="🧠 Smart Auto Crop  —  engine analyses context & activates the optimal combination",
            variable=self.app_state.v_action_smart_auto_crop,
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#88ddff",
        )
        self._cb_smart_auto_crop.pack(side="left")
        _add_dep(self._cb_smart_auto_crop)
        _b3 = _InfoBadge(smart_row)
        _b3.configure(text="Automatically analyzes the scene to optimize bottom crop, top crop, and floor tracking.\n(Forced ON when Let me handle it is active)")
        _b3.pack(side="left", padx=(0, 8))

        scene_type_row = ctk.CTkFrame(parent, fg_color="transparent")
        scene_type_row.pack(fill="x", padx=14, pady=(6, 2))
        ctk.CTkLabel(scene_type_row, text="Scene Type:").pack(side="left", padx=(0, 10))
        self._scene_type_menu = ctk.CTkOptionMenu(
            scene_type_row,
            variable=self.app_state.v_action_scene_type,
            values=["", "platformer", "talking_closeup", "full_body_tall",
                    "fighting_2d", "action_horizontal", "talking_medium",
                    "full_body_medium", "wide_shot", "action_moving"],
            width=200,
        )
        self._scene_type_menu.pack(side="left")
        _add_dep(self._scene_type_menu)

        scene_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        scene_auto_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_scene_type = ctk.CTkCheckBox(
            scene_auto_row,
            text="Auto Scene Type  (overrides dropdown · detects scene from content)",
            variable=self.app_state.v_action_auto_scene_type,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_scene_type.pack(side="left")
        _add_dep(self._cb_auto_scene_type)

        def _toggle_auto_scene_type(*_):
            if self.app_state.v_action_smart_auto_crop.get(): return
            state = "disabled" if self.app_state.v_action_auto_scene_type.get() else "normal"
            self._safe_cfg(self._scene_type_menu, state=state)
        self.app_state.v_action_auto_scene_type.trace_add("write", _toggle_auto_scene_type)

        pillarbox_row = ctk.CTkFrame(parent, fg_color="transparent")
        pillarbox_row.pack(fill="x", padx=14, pady=(6, 0))
        self._cb_auto_pillarbox = ctk.CTkCheckBox(
            pillarbox_row,
            text="🎞  Auto Pillarbox Crop (Black bars)",
            variable=self.app_state.v_action_auto_pillarbox_crop,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_pillarbox.pack(side="left")
        _add_dep(self._cb_auto_pillarbox)

        self._slider_bottom_crop = adv_slider(parent, "Bottom crop (%)", self.app_state.v_action_bottom_crop_pct, 0.0, 0.5,
                   "{:.0%}", "", steps=50)
        _add_dep(self._slider_bottom_crop)
        bottom_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        bottom_auto_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_bottom_crop = ctk.CTkCheckBox(
            bottom_auto_row,
            text="Auto bottom crop  (overrides slider · detects floor / feet / face priority)",
            variable=self.app_state.v_action_auto_bottom_crop,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_bottom_crop.pack(side="left")
        _add_dep(self._cb_auto_bottom_crop)

        def _toggle_auto_bottom_crop(*_):
            if self.app_state.v_action_smart_auto_crop.get(): return
            state = "disabled" if self.app_state.v_action_auto_bottom_crop.get() else "normal"
            self._safe_cfg(self._slider_bottom_crop, state=state)
        self.app_state.v_action_auto_bottom_crop.trace_add("write", _toggle_auto_bottom_crop)

        self._slider_top_crop = adv_slider(parent, "Top crop (%)", self.app_state.v_action_top_crop_pct, 0.0, 0.5,
                   "{:.0%}", "", steps=50)
        _add_dep(self._slider_top_crop)
        top_auto_row = ctk.CTkFrame(parent, fg_color="transparent")
        top_auto_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_top_crop = ctk.CTkCheckBox(
            top_auto_row,
            text="Auto top crop  (overrides slider · detects head / sky / ceiling)",
            variable=self.app_state.v_action_auto_top_crop,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_top_crop.pack(side="left")
        _add_dep(self._cb_auto_top_crop)

        def _toggle_auto_top_crop(*_):
            if self.app_state.v_action_smart_auto_crop.get(): return
            state = "disabled" if self.app_state.v_action_auto_top_crop.get() else "normal"
            self._safe_cfg(self._slider_top_crop, state=state)
        self.app_state.v_action_auto_top_crop.trace_add("write", _toggle_auto_top_crop)

        self._slider_vertical_bias = adv_slider(parent, "Vertical bias", self.app_state.v_action_vertical_bias, -1.0, 1.0,
                   "{:.2f}", "", steps=100)
        _add_dep(self._slider_vertical_bias)

        auto_floor_row = ctk.CTkFrame(parent, fg_color="transparent")
        auto_floor_row.pack(fill="x", padx=14, pady=(0, 2))
        self._cb_auto_floor = ctk.CTkCheckBox(
            auto_floor_row,
            text="Auto floor detect (asymmetric EMA · overrides Vertical bias)",
            variable=self.app_state.v_action_auto_vertical_bias,
            font=ctk.CTkFont(size=12), text_color="#ffe08a",
        )
        self._cb_auto_floor.pack(side="left")
        _add_dep(self._cb_auto_floor)

        def _toggle_auto_floor(*_):
            if self.app_state.v_action_smart_auto_crop.get(): return
            state = "disabled" if self.app_state.v_action_auto_vertical_bias.get() else "normal"
            self._safe_cfg(self._slider_vertical_bias, state=state)
        self.app_state.v_action_auto_vertical_bias.trace_add("write", _toggle_auto_floor)

        def _toggle_smart_auto(*_):
            smart_on  = self.app_state.v_action_smart_auto_crop.get()
            cb_state  = "disabled" if smart_on else "normal"
            
            if smart_on:
                self.app_state.v_action_auto_scene_type.set(True)
                self.app_state.v_action_auto_bottom_crop.set(True)
                self.app_state.v_action_auto_top_crop.set(True)
                self.app_state.v_action_auto_vertical_bias.set(True)
                
            self._safe_cfg(self._cb_auto_scene_type, state=cb_state)
            self._safe_cfg(self._cb_auto_bottom_crop, state=cb_state)
            self._safe_cfg(self._cb_auto_top_crop, state=cb_state)
            self._safe_cfg(self._cb_auto_floor, state=cb_state)
            if not smart_on:
                _toggle_auto_scene_type()
                _toggle_auto_bottom_crop()
                _toggle_auto_top_crop()
                _toggle_auto_floor()
            else:
                self._safe_cfg(self._scene_type_menu, state="disabled")
                self._safe_cfg(self._slider_bottom_crop, state="disabled")
                self._safe_cfg(self._slider_top_crop, state="disabled")
                self._safe_cfg(self._slider_vertical_bias, state="disabled")
        self.app_state.v_action_smart_auto_crop.trace_add("write", _toggle_smart_auto)

        def _toggle_action_enabled(*_):
            if self.app_state.v_let_me_handle_it.get(): return
            enabled = self.app_state.v_action_enabled.get()
            if not enabled:
                for w in self._action_dependent_widgets:
                    self._safe_cfg(w, state="disabled")
            else:
                for w in self._action_dependent_widgets:
                    self._safe_cfg(w, state="normal")
                self.refresh_states()
        self.app_state.v_action_enabled.trace_add("write", _toggle_action_enabled)

        bg_sub_row = ctk.CTkFrame(parent, fg_color="transparent")
        bg_sub_row.pack(fill="x", padx=14, pady=(0, 4))
        self._cb_bg_sub = ctk.CTkCheckBox(
            bg_sub_row,
            text="Enable Background Subtraction (replaces background with black)",
            variable=self.app_state.v_action_bg_sub_enable,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
        )
        self._cb_bg_sub.pack(side="left")
        self.app_state.lmh_widgets.append(self._cb_bg_sub)
        _b4 = _InfoBadge(bg_sub_row)
        _b4.configure(text="Replaces the detected background with black to maximize contrast and reduce LED power consumption.\n(Locked when Let me handle it is ON)")
        _b4.pack(side="left", padx=(0, 8))

    def refresh_states(self):
        # Only refresh if the panel is globally enabled or managed by LMH
        if not self.app_state.v_action_enabled.get() and not self.app_state.v_let_me_handle_it.get():
            return
        
        self.app_state.v_action_smart_auto_crop.set(self.app_state.v_action_smart_auto_crop.get())
        self.app_state.v_action_auto_bottom_crop.set(self.app_state.v_action_auto_bottom_crop.get())
        self.app_state.v_action_auto_top_crop.set(self.app_state.v_action_auto_top_crop.get())
        self.app_state.v_action_auto_vertical_bias.set(self.app_state.v_action_auto_vertical_bias.get())
        self.app_state.v_action_auto_strength.set(self.app_state.v_action_auto_strength.get())
        self.app_state.v_action_auto_smoothness.set(self.app_state.v_action_auto_smoothness.get())
        self.app_state.v_action_auto_scene_type.set(self.app_state.v_action_auto_scene_type.get())
