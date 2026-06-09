from dataclasses import dataclass

@dataclass
class ExportConfig:
    output_dir: str = ""
    target_width: int = 128
    target_height: int = 32
    target_preset: str = "128x32 (1x1)"
    max_dur_enabled: bool = True
    max_duration: float = 120.0
