from dataclasses import dataclass
from typing import Optional

@dataclass
class AutoActionConfig:
    detector: str = "person"          # person | motion | hybrid | center
    strength: float = 0.65             # 0..1, larger = tighter framing
    smoothness: float = 0.65           # 0..0.98, larger = smoother / slower
    zoom_max: float = 2.0              # max dynamic zoom factor (hard limit)
    padding: float = 0.20              # extra padding around ROI
    intro_duration: float = 1.5        # seconds of full-frame overview before focusing
    bg_sub_enable: bool = False        # enable background subtraction (replaces background with black)
    bottom_crop_pct: float = 0.0       # fraction of image bottom to exclude from framing (0 = disabled)
    top_crop_pct: float = 0.0          # fraction of image top to exclude from framing (0 = disabled)
    auto_bottom_crop: bool = False     # auto-detect bottom crop boundary from ROI analysis
    auto_top_crop: bool = False        # auto-detect top crop boundary from ROI analysis
    vertical_bias: float = 0.0        # shift camera center: +1.0 = down (show floor), -1.0 = up (show sky)
    auto_vertical_bias: bool = False  # auto floor detection: places ROI bottom (floor) at ~85 % of crop height
    smart_auto_crop: bool = False      # let the engine choose the optimal crop/tracking combination
    auto_strength: bool = False        # auto-detect optimal strength based on content type
    auto_pillarbox_crop: bool = False  # auto-detect left/right black bars and constrain horizontal framing
    auto_smoothness: bool = False      # auto-detect optimal smoothness based on content type
    dmd_visibility_score_enabled: bool = False # Enable DMD Visibility Score
    # ── PRIORITY 2 — Temporal Scene Memory ───────────────────────────────────
    # Sliding window (seconds) of past ROI detections used to interpolate the
    # camera position when YOLO loses the subject for a few frames.  Set to 0
    # to disable (matches legacy behaviour).  2–5 s recommended.
    roi_history_window_s: float = 3.0   # seconds of ROI history kept (0 = disabled)
    # ── PRIORITY 3 — Scene Change Detection ──────────────────────────────────
    # When the HSV histogram difference between two consecutive frames exceeds
    # scene_change_threshold, the ROI history, camera smoothing, and zoom are
    # all reset so stale tracking data does not bleed across hard cuts.
    # Set to 0.0 to disable.
    scene_change_threshold: float = 0.45  # 0..1, higher = less sensitive
    # ── PRIORITY 4 — Micro-detection Rejection ────────────────────────────────
    # Any detected ROI whose area is smaller than this fraction of the source
    # frame area is silently discarded.  Prevents zooming onto tiny subjects
    # (< 2 % of frame) that would become invisible after resize to DMD res.
    min_roi_area_ratio: float = 0.02   # 0..1, 0 = disabled (accept all ROIs)
    # ── PRIORITY 5 — Directional Look-Ahead ──────────────────────────────────
    # When the ROI centre moves consistently in one direction, offset the camera
    # slightly in that direction so there is space "in front of" the subject.
    # lead_factor=0 = disabled (legacy).  0.15–0.35 recommended.
    look_ahead_enabled: bool = True
    look_ahead_factor: float = 0.25   # fraction of crop half-width to offset
    # ── PRIORITY 6 — Multi-ROI Fusion ───────────────────────────────────────
    # When True, all YOLO person detections above the confidence threshold are
    # gathered and fused into a single confidence-weighted centroid bounding box.
    # Prevents the camera from always snapping to the single highest-confidence
    # subject when multiple people are visible (e.g. a crowd or co-op play).
    multi_roi_fusion_enabled: bool = True
    # ── PRIORITY 7 — Minimum Useful Size After Resize ────────────────────────
    # Minimum dimension (pixels) a detected subject must occupy in the DMD
    # output frame.  Any proposed zoom that would render the ROI smaller than
    # this in BOTH width and height is cancelled and the camera stays at the
    # current position.  0 = disabled.
    min_subject_dmd_px: int = 4    # pixels in the DMD output (e.g. 128×32)
    # ── Scene Type Classification ────────────────────────────────────────────
    # Manual scene type selection.  Each scene type implies a full profile
    # (face clipping, strength, smoothness, floor tracking) — analogous to
    # how the colorimetry 'mode' implies contrast/saturation/brightness.
    # Empty string = no manual override (use defaults or auto-detection).
    # Valid values: see SceneType.ALL in src/engine/analysis/scene_types.py
    scene_type: str = ""

    # When True, the analysis phase auto-detects the scene type from content
    # (overrides manual scene_type).  Enabled by smart_auto_crop / LMH.
    auto_scene_type: bool = False

    # ── PRIORITY 8 — Smart Platformer Mode ───────────────────────────────────
    # Optimised for side-scrolling 2-D games: locks vertical tracking to keep
    # the floor visible at a fixed ratio of the strip height, and widens the
    # horizontal field of view to reveal more of the level ahead.
    platformer_mode: bool = False
    platformer_floor_ratio: float = 0.80  # fraction of strip height for floor line
    # ── PRIORITY 10 — ROI Confidence System ──────────────────────────────────
    # Minimum YOLO confidence score required to act on a detection.  Boxes
    # below this value are silently dropped (treated as no detection).  When
    # combined with P2 temporal memory the camera holds its last known position
    # rather than jumping to centre.  0.0 = accept everything (legacy).
    roi_confidence_min: float = 0.0   # [0..1], 0 = disabled

    # ── VNext Priority 1 & 8 — Dynamic ROI Confidence & Persistence ──────────
    dynamic_roi_confidence_enabled: bool = True
    roi_persistence_score_enabled: bool = True

    # ── VNext Priority 6 — Scroll Direction Memory ───────────────────────────
    scroll_direction_memory_enabled: bool = True

    # ── VNext Priority 9 — DMD Readability Predictor ─────────────────────────
    dmd_readability_score_enabled: bool = True

    # ── VNext Priority 10 — Auto Tuning Dataset Generator ────────────────────
    auto_tuning_dataset_dir: Optional[str] = None  # None = disabled

    # ── Search Engines API Keys ─────────────────────────────────────────────
    tenor_api_key: str = ""
    giphy_api_key: str = ""

    # API backward-compatibility only
    out_w: int = 0
    out_h: int = 0
    start_s: Optional[float] = None
    end_s: Optional[float] = None
    target_width: int = 128           # Target output width for DMD
    target_height: int = 32          # Target output height for DMD
