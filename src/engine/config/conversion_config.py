from dataclasses import dataclass

@dataclass
class ConversionConfig:
    mode: str = "pixel_art"
    workers: int = 2
    auto_workers: bool = True
    scroll_speed: float = 24.0
    bottom_crop: float = 0.15
    top_crop: float = 0.0
    scroll_cycles: float = 1.5
    fps_min: float = 10.0
    fps_max: float = 25.0
    contrast: float = 1.6
    saturation: float = 2.2
    brightness: float = -0.03
    gamma: float = 0.85
    sharpen_lum: float = 1.8
    sharpen_chr: float = 0.5
    dither: str = "none"
    trim_start: float = 0.0
    trim_end: float = 0.0
    scroll_enabled: bool = True
    zoom: float = 1.0
    manual_x: int = 0
    manual_y: int = 0
    hue_shift: float = 0.0
    noise_reduction: float = 0.0
    film_grain: int = 0
    vignette: bool = False
    auto_color_enabled: bool = False
    let_me_handle_it: bool = True
    per_gif_config: bool = False
    led_sim: bool = True
