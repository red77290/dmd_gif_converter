import logging
from typing import Any, Dict
import tkinter as tk

from src.engine.config.conversion_config import ConversionConfig
from src.engine.config.auto_action_config import AutoActionConfig
from src.engine.config.export_config import ExportConfig
from src.engine.config.display_config import DisplayConfig
from src.ui.interfaces import IModel

logger = logging.getLogger(__name__)

APP_VERSION = "7.1.0"

class ApplicationState(IModel):
    def __init__(self):
        self.conversion_config = ConversionConfig()
        self.auto_action_config = AutoActionConfig()
        self.export_config = ExportConfig()
        self.display_config = DisplayConfig()

        # Tkinter vars for UI binding (we can sync these with config)
        # We define them here to allow UI widgets to bind easily.
        # This can be improved to automatically generate Tk vars from dataclass fields.
        self._var_map: Dict[str, tk.Variable] = {}
        
        # Pre-initialize target dimensions as StringVar to prevent Tkinter TclError on empty Entry
        self.v_smart_ratio_bypass = tk.BooleanVar(value=True)

        self.v_target_width = tk.StringVar(value="128")
        self.v_target_height = tk.StringVar(value="32")
        self._var_map["v_target_width"] = self.v_target_width
        self._var_map["v_target_height"] = self.v_target_height
        
        self._create_tk_vars_for_config(self.conversion_config, "v_")
        self._create_tk_vars_for_config(self.auto_action_config, "v_action_")
        self._create_tk_vars_for_config(self.export_config, "v_")
        self._create_tk_vars_for_config(self.display_config, "v_")
        
        # Add aliases or special vars
        self.v_search_keyword = tk.StringVar(value="")
        self.v_search_qty     = tk.StringVar(value="10")
        self.v_search_engine  = tk.StringVar(value="DuckDuckGo")
        self.v_search_min_w   = tk.StringVar(value="")
        self.v_search_min_h   = tk.StringVar(value="")
        self.v_search_ratio   = tk.StringVar(value="All")
        self.v_action_enabled = tk.BooleanVar(value=False)
        self.v_per_gif_config = tk.BooleanVar(value=False)
        self.v_auto_workers = tk.BooleanVar(value=True)

        # UI state helpers
        self.per_gif_global_snapshot: Dict[str, Any] = {}
        self.lmh_widgets: list = []

        # Apply "Let me handle it" overrides immediately if enabled by default
        self._apply_lmh_if_needed()
        # Keep applying whenever the flag is toggled (even if SettingsPanel is closed)
        self.v_let_me_handle_it.trace_add("write", lambda *_: self._apply_lmh_if_needed())


    def _create_tk_vars_for_config(self, config_obj, prefix: str):
        for field_name in config_obj.__dataclass_fields__:
            val = getattr(config_obj, field_name)
            var_name = f"{prefix}{field_name}"
            
            # Avoid overwriting if already exists
            if hasattr(self, var_name):
                continue
                
            if isinstance(val, bool):
                var = tk.BooleanVar(value=val)
            elif isinstance(val, int):
                var = tk.IntVar(value=val)
            elif isinstance(val, float):
                var = tk.DoubleVar(value=val)
            else:
                var = tk.StringVar(value=str(val) if val is not None else "")
                
            setattr(self, var_name, var)
            self._var_map[var_name] = var

    def get(self, key: str, default: Any = None) -> Any:
        var = self._var_map.get(key)
        if var is not None:
            try:
                return var.get()
            except Exception:
                return default
        return getattr(self, key, default)

    def set(self, key: str, value: Any) -> None:
        var = self._var_map.get(key)
        if var is not None:
            try:
                var.set(value)
            except Exception:
                pass
        else:
            setattr(self, key, value)

    def snapshot(self) -> Dict[str, Any]:
        return {k: v.get() for k, v in self._var_map.items()}

    def restore(self, state: Dict[str, Any]) -> None:
        for k, val in state.items():
            var = self._var_map.get(k)
            if var is not None:
                try:
                    var.set(val)
                except Exception:
                    pass

    def _apply_lmh_if_needed(self):
        """Apply 'Let me handle it' var overrides at startup if the flag is True.

        The SettingsPanel is only built on demand, so lmh_widgets is empty at
        startup.  We still need the *values* (v_auto_color_enabled, etc.) to
        reflect the forced state so that _collect_params() returns consistent
        results even before the settings window is ever opened.
        """
        if not getattr(self, "v_let_me_handle_it", None):
            return
        if not self.v_let_me_handle_it.get():
            return
        forced_true = [
            "v_auto_color_enabled",
            "v_action_enabled",
            "v_action_smart_auto_crop",
            "v_action_auto_scene_type",
            "v_action_dmd_visibility_score_enabled",
            "v_action_dmd_readability_score_enabled",
            "v_action_auto_strength",
            "v_action_auto_smoothness",
            "v_action_auto_pillarbox_crop",
            "v_action_dynamic_scene_detection",
            "v_action_auto_detector_fallback",
        ]
        for var_name in forced_true:
            var = getattr(self, var_name, None)
            if var is not None:
                try:
                    var.set(True)
                except Exception:
                    pass

    def build_params(self) -> Dict[str, Any]:
        """Build a converter-compatible params dict from current state."""
        # Simple implementation returning all tracked vars
        return {k.replace("v_", "").replace("action_", ""): v.get() for k, v in self._var_map.items()}
