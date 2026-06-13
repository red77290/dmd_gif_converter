import customtkinter as ctk
# ── Constants ─────────────────────────────────────────────────────────────────
# Three preview canvases
SRC_CANVAS_W  = 300
SRC_CANVAS_H  = 170
AUTO_CANVAS_W = 300
AUTO_CANVAS_H = 170

# DMD output is still displayed at 128×32 scaled ×2.34
DMD_DISPLAY_SCALE_FACTOR = 2.34375 # 300/128 = 75/32

# LED pixel-simulation — constants and filter imported from dmd_led_sim
# (zero UI dependencies, independently testable)
from src.ui.dmd_led_sim import LED_SIM_SCALE, LED_SIM_GAP, LED_SIM_MAX_W, apply_led_grid as _apply_led_grid

BG_CANVAS     = "#0d0d1a"
APP_VERSION   = "7.0.0"

# Auto-refresh debounce: ms to wait after last param change before rebuilding DMD
DMD_REFRESH_DELAY_MS = 1800

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

STATUS_COLOR = {
    "idle":       "#666688",
    "converting": "#f39c12",
    "done":       "#2ecc71",
    "error":      "#e74c3c",
}
MODE_DESC = {
    "pixel_art": "Retro sprites, arcade, consoles — default ★",
    "anime":     "Anime / cartoon (softer rendering)",
    "cinema":    "Live-action films, real footage",
    "custom":    "Manual control of every parameter",
}




