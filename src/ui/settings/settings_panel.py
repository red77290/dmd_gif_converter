import customtkinter as ctk

from src.ui.settings.conversion_settings import ConversionSettingsPanel
from src.ui.settings.auto_action_settings import AutoActionSettingsPanel
from src.ui.settings.display_settings import DisplaySettingsPanel
from src.ui.settings.advanced_settings import AdvancedSettingsPanel

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent, app_state):
        super().__init__(parent)
        self.title("⚙️ Advanced Settings")
        self.geometry("420x750")
        self.transient(parent.winfo_toplevel())
        
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        self.panel = SettingsPanel(self, app_state)
        self.panel.grid(row=0, column=0, sticky="nsew")

class SettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Create a scrollable frame for all settings
        self.scroll_frame = ctk.CTkScrollableFrame(self)
        self.scroll_frame.grid(row=0, column=0, sticky="nsew")

        # Top toggles that were in _build_params_panel (Smart Color Boost)
        self._build_top_toggles(self.scroll_frame)

        # 1. Conversion Settings
        self.conversion_settings = ConversionSettingsPanel(self.scroll_frame, self.app_state)
        self.conversion_settings.pack(fill="x", padx=5, pady=5)

        # Colorimetry could be in ConversionSettings but keeping it simple here
        self._build_colorimetry(self.scroll_frame)

        # 2. Auto Action Settings
        self.auto_action_settings = AutoActionSettingsPanel(self.scroll_frame, self.app_state)
        self.auto_action_settings.pack(fill="x", padx=5, pady=5)

        # 3. Display Settings (Text Overlay)
        self.display_settings = DisplaySettingsPanel(self.scroll_frame, self.app_state)
        self.display_settings.pack(fill="x", padx=5, pady=5)

        # 4. Advanced Settings
        self.advanced_settings = AdvancedSettingsPanel(self.scroll_frame, self.app_state)
        self.advanced_settings.pack(fill="x", padx=5, pady=5)

        # Connect "Let Me Handle It" behavior across sub-panels
        self._lmh_widgets = []
        # We need to find all widgets inside those panels that need to be disabled.
        # For a true refactor, the components should observe the app_state.v_let_me_handle_it var.
        self.app_state.v_let_me_handle_it.trace_add("write", self._on_let_me_handle_toggle)
        self.app_state.v_per_gif_config.trace_add("write", self._on_per_gif_toggle)
        
        # Initial call
        self._on_let_me_handle_toggle()

    def _build_top_toggles(self, parent):
        pg_frame = ctk.CTkFrame(parent, fg_color='#0f1a10', corner_radius=6)
        pg_frame.pack(fill='x', padx=13, pady=(8, 4))
        pg_frame.grid_columnconfigure(1, weight=1)
        self._per_gif_cb = ctk.CTkCheckBox(pg_frame, text='🎞️  Per-GIF Config  —  each file has its own settings', variable=self.app_state.v_per_gif_config, command=self._on_per_gif_toggle, font=ctk.CTkFont(size=12, weight='bold'), text_color='#88ddaa')
        self._per_gif_cb.pack(side='left', padx=12, pady=8)
        from src.ui.widgets import _InfoBadge
        _badge_pg = _InfoBadge(pg_frame)
        _badge_pg.configure(text=(
            'When enabled, each GIF can have its own custom settings.\n'
            'Clicking a GIF in the conversion list loads its specific configuration.'
        ))
        _badge_pg.pack(side='left', padx=(0, 8))
        self._per_gif_status_lbl = ctk.CTkLabel(pg_frame, text='', text_color='#557755', font=ctk.CTkFont(size=10))
        self._per_gif_status_lbl.pack(side='left', padx=(0, 8))
        ac_row = ctk.CTkFrame(parent, fg_color='#0f1a0f', corner_radius=6)
        ac_row.pack(fill='x', padx=13, pady=(10, 6))
        self._auto_color_cb = ctk.CTkCheckBox(ac_row, text='🎨  Smart Color Boost  —  IA auto-colorimetry', variable=self.app_state.v_auto_color_enabled, font=ctk.CTkFont(size=12, weight='bold'), text_color='#88dd88')
        self._auto_color_cb.pack(side='left', padx=12, pady=8)
        self.app_state.lmh_widgets.append(self._auto_color_cb)
        _badge_ac = _InfoBadge(ac_row)
        _badge_ac.configure(text=(
            'Automatically adjusts contrast, saturation, and brightness based on the image content.\n'
            '(Locked and forced ON when Let me handle it is active)'
        ))
        _badge_ac.pack(side='left', padx=(0, 8))

    def _build_colorimetry(self, parent):
        self._custom_header = ctk.CTkLabel(
            parent, text="🎛️  Colorimetry  (custom mode only)",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        )
        self._custom_header.pack(fill="x", padx=13, pady=(12, 2), anchor="w")
        self._custom_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._custom_frame.pack(fill="x")
        
        # Adding sliders via the shared adv_slider (imported from advanced_settings or a new util)
        from src.ui.settings.advanced_settings import adv_slider
        adv_slider(self._custom_frame, "Contrast",    self.app_state.v_contrast,    0.5,  2.5)
        adv_slider(self._custom_frame, "Saturation",  self.app_state.v_saturation,  0.0,  4.0)
        adv_slider(self._custom_frame, "Brightness",  self.app_state.v_brightness, -0.5,  0.5, "{:.3f}")
        adv_slider(self._custom_frame, "Gamma",       self.app_state.v_gamma,       0.1,  2.5)
        adv_slider(self._custom_frame, "Sharpen Lum", self.app_state.v_sharpen_lum, 0.0,  3.0)
        adv_slider(self._custom_frame, "Sharpen Chr", self.app_state.v_sharpen_chr, 0.0,  2.0)

        self.app_state.v_mode.trace_add("write", self._update_custom_visibility)
        self._update_custom_visibility()

    def _update_custom_visibility(self, *_):
        is_custom = self.app_state.v_mode.get() == "custom"
        if is_custom:
            self._custom_header.pack(fill="x", padx=13, pady=(12, 2), anchor="w")
            self._custom_frame.pack(fill="x")
        else:
            self._custom_header.pack_forget()
            self._custom_frame.pack_forget()

    def _on_per_gif_toggle(self, *_):
        is_on = self.app_state.v_per_gif_config.get()
        if is_on:
            self.app_state.per_gif_global_snapshot = self.app_state.snapshot()
            if hasattr(self, '_per_gif_status_lbl'):
                self._per_gif_status_lbl.configure(text='ON — select a file to load/save its config')
        else:
            if self.app_state.per_gif_global_snapshot:
                self.app_state.restore(self.app_state.per_gif_global_snapshot)
            if hasattr(self, '_per_gif_status_lbl'):
                self._per_gif_status_lbl.configure(text='')

    def _on_let_me_handle_toggle(self, *_):
        enabled = self.app_state.v_let_me_handle_it.get()
        if enabled:
            self.app_state.v_auto_color_enabled.set(True)
            self.app_state.v_action_enabled.set(True)
            self.app_state.v_action_smart_auto_crop.set(True)
            self.app_state.v_action_auto_scene_type.set(True)
            self.app_state.v_action_dmd_visibility_score_enabled.set(True)
            self.app_state.v_action_dmd_readability_score_enabled.set(True)
            self.app_state.v_action_auto_strength.set(True)
            self.app_state.v_action_auto_smoothness.set(True)
            self.app_state.v_action_auto_pillarbox_crop.set(True)
            self.app_state.v_action_zoom_max.set(2.0)
        state = 'disabled' if enabled else 'normal'
        for widget in self.app_state.lmh_widgets:
            try:
                widget.configure(state=state)
            except Exception:
                pass
