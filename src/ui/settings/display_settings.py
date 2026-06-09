import customtkinter as ctk

class DisplaySettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, app_state):
        super().__init__(parent, fg_color="transparent")
        self.app_state = app_state
        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(
            self, text="━━  💬  Text Overlay",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#7ec8e3"
        ).pack(fill="x", padx=10, pady=(10, 4), anchor="w")

        text_overlay_row = ctk.CTkFrame(self, fg_color="transparent")
        text_overlay_row.pack(fill="x", padx=14, pady=(0, 4))
        
        self._text_overlay_checkbox = ctk.CTkCheckBox(
            text_overlay_row,
            text="Enable Text Overlay",
            variable=self.app_state.v_text_overlay_enabled,
            font=ctk.CTkFont(size=12), text_color="#aaddaa",
            command=self._on_text_overlay_toggle
        )
        self._text_overlay_checkbox.pack(side="left")
        
        self._text_overlay_btn = ctk.CTkButton(
            text_overlay_row,
            text="⚙️ Settings",
            width=80,
            height=24,
            command=self._open_text_overlay_popup,
            font=ctk.CTkFont(size=11),
            fg_color="#3a4b6b", hover_color="#4a5b7b"
        )

        self._on_text_overlay_toggle()

    def _open_text_overlay_popup(self):
        from src.ui.popups import TextOverlayPopup
        # Master will be self.master (the scroll_frame or SettingsPanel)
        popup = TextOverlayPopup(self.master, self.app_state)
        
    def _on_text_overlay_toggle(self):
        if self.app_state.v_text_overlay_enabled.get():
            self._text_overlay_btn.pack(side="left", padx=10)
        else:
            self._text_overlay_btn.pack_forget()
