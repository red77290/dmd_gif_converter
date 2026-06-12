import customtkinter as ctk
from src.engine.conversion.core import DEFAULT_PARAMS

class ExportSettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="━━  🖼️  Multi-Dalle / Tiling",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        self._tiling_preset_row = ctk.CTkFrame(self, fg_color="transparent")
        tiling_preset_row = self._tiling_preset_row
        tiling_preset_row.pack(fill="x", padx=10, pady=2)
        tiling_preset_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tiling_preset_row, text="Dimensions Preset", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._target_preset_menu = ctk.CTkOptionMenu(
            tiling_preset_row,
            variable=self.app_state.v_target_preset,
            values=["128x32 (1x1)", "256x32 (2x1)", "128x64 (1x2)", "256x64 (2x2)", "Custom"],
            command=self._on_target_preset_change,
            width=200,
        )
        self._target_preset_menu.grid(row=0, column=1, sticky="w", padx=4)

        self._custom_tiling_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._custom_tiling_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self._custom_tiling_frame, text="Custom Width", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(4, 6))
        self._custom_width_entry = ctk.CTkEntry(
            self._custom_tiling_frame, textvariable=self.app_state.v_target_width, width=100
        )
        self._custom_width_entry.grid(row=0, column=1, sticky="w", padx=4)

        ctk.CTkLabel(self._custom_tiling_frame, text="Custom Height", width=145, anchor="w",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(4, 6))
        self._custom_height_entry = ctk.CTkEntry(
            self._custom_tiling_frame, textvariable=self.app_state.v_target_height, width=100
        )
        self._custom_height_entry.grid(row=1, column=1, sticky="w", padx=4)

        self._on_target_preset_change(self.app_state.v_target_preset.get()) 

    def _on_target_preset_change(self, preset):
        if preset == "Custom":
            self._custom_tiling_frame.pack(
                fill="x", padx=10, pady=2, after=self._tiling_preset_row
            )
        else:
            width, height = map(int, preset.split(" ")[0].split("x"))
            self.app_state.v_target_width.set(width)
            self.app_state.v_target_height.set(height)
            self._custom_tiling_frame.pack_forget()
