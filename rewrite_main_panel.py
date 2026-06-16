import re

with open("src/ui/preview/preview_panel.py", "r") as f:
    code = f.read()

# Add imports for controllers
code = re.sub(
    r"from src.ui.constants import \(",
    "from src.ui.preview.controllers.source_controller import SourceController\n"
    "from src.ui.preview.controllers.auto_controller import AutoController\n"
    "from src.ui.preview.controllers.dmd_controller import DmdController\n\n"
    "from src.ui.constants import (",
    code
)

# Initialize controllers in __init__
init_hook = r"        self._last_dmd_h = SRC_CANVAS_H" + "\n"
controllers_init = """
        # Instantiate Controllers
        self.dmd_controller = DmdController(
            self._dmd_canvas, self._dmd_info_label, self._btn_dmd, 
            self._conv_progress, self.app_state)
            
        self.auto_controller = AutoController(
            self._auto_canvas, self._auto_info_label, self._btn_auto, 
            self.dmd_controller, self.app_state)
            
        self.source_controller = SourceController(
            self._src_canvas, self._src_info_label, self._btn_src)
"""
code = code.replace(init_hook, init_hook + controllers_init)

# Replace _load_preview
new_load_preview = """    def _load_preview(self, file_path, is_converted=False, converted_data=None):
        self._source_duration = 10.0
        from src.engine.conversion.utils import get_metadata
        _, __, ___, dur = get_metadata(file_path)
        self._source_duration = dur if dur and dur > 0 else 10.0
        self._update_trim_sliders()

        if is_converted:
            self._trim_frame.grid_remove()
            self._diagnosis_frame.grid()
            if converted_data:
                score = converted_data.get("score", 0)
                color = converted_data.get("color", "")
                rating = converted_data.get("rating", "")
                reasons = converted_data.get("reasons", [])
                self._lbl_score.configure(
                    text=f"{score}%\\n{rating}",
                    text_color=color if color and "#" in color else "#ffffff")
                
                reasons_text = " • " + "\\n • ".join(reasons) if reasons else "No specific reasons."
                self._lbl_reasons.configure(text=reasons_text)
            
            self.source_controller.draw_idle()
            self.auto_controller.draw_idle()
            self.dmd_controller.start_generation(file_path, is_already_converted=True)
        else:
            self._trim_frame.grid()
            self._diagnosis_frame.grid_remove()
            self.source_controller.load(file_path, self._source_duration)
            self.auto_controller.start_generation(file_path)"""

code = re.sub(r"    def _load_preview\(self, file_path, is_converted=False, converted_data=None\):.*?(?=    # ══════════════════════════════════════════════════════════════════════════\n    #  SOURCE)", new_load_preview + "\n\n", code, flags=re.DOTALL)

# Delete all old logic from SOURCE to end
idx = code.find("    # ══════════════════════════════════════════════════════════════════════════\n    #  SOURCE")
if idx != -1:
    code = code[:idx]

with open("src/ui/preview/main_panel.py", "w") as f:
    f.write(code)

