from dataclasses import dataclass

@dataclass
class DisplayConfig:
    text_overlay_enabled: bool = False
    text_content: str = ""
    text_font_size: int = 8
    text_color: str = "white"
    text_position: str = "bottom_center"
    text_font_file: str = "HelvetiPixel.ttf"
    text_style: str = "outline"
    text_animation: str = "none"
    text_bg: bool = False
    text_bg_opacity: int = 60
