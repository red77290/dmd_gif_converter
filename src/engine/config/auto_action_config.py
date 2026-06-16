from dataclasses import dataclass, fields, replace as _dc_replace
from typing import Optional

@dataclass
class AutoActionConfig:
    detector: str = "person"          # person | motion | hybrid | center
    strength: float = 0.65             # 0..1, larger = tighter framing
    smoothness: float = 0.65           # 0..0.98, larger = smoother / slower
    zoom_max: float = 2.0              # max dynamic zoom factor (hard limit)
    padding: float = 0.20              # extra padding around ROI
    subsample_frames: int = 3          # run YOLO every N frames (1 = every frame)
    intro_duration: float = 0.0        # seconds of full-frame overview before focusing
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
    auto_detector_fallback: bool = False # dynamically switch to hybrid if person fails
    dmd_visibility_score_enabled: bool = False # Enable DMD Visibility Score
    # ── PRIORITY 2 — Temporal Scene Memory ───────────────────────────────────
    roi_history_window_s: float = 3.0   # seconds of ROI history kept (0 = disabled)
    # ── PRIORITY 3 — Scene Change Detection ──────────────────────────────────
    scene_change_threshold: float = 0.45  # 0..1, higher = less sensitive
    # ── PRIORITY 4 — Micro-detection Rejection ────────────────────────────────
    min_roi_area_ratio: float = 0.02   # 0..1, 0 = disabled (accept all ROIs)
    # ── PRIORITY 5 — Directional Look-Ahead ──────────────────────────────────
    look_ahead_enabled: bool = True
    look_ahead_factor: float = 0.25   # fraction of crop half-width to offset
    # ── PRIORITY 6 — Multi-ROI Fusion ───────────────────────────────────────
    multi_roi_fusion_enabled: bool = True
    # ── PRIORITY 7 — Minimum Useful Size After Resize ────────────────────────
    min_subject_dmd_px: int = 4    # pixels in the DMD output (e.g. 128×32)
    # ── Scene Type Classification ────────────────────────────────────────────
    scene_type: str = ""
    auto_scene_type: bool = False
    # When enabled, classifies the scene dynamically on every camera cut
    dynamic_scene_detection: bool = False
    # ── PRIORITY 8 — Smart Platformer Mode ───────────────────────────────────
    platformer_mode: bool = False
    platformer_floor_ratio: float = 0.80  # fraction of strip height for floor line
    # ── PRIORITY 10 — ROI Confidence System ──────────────────────────────────
    roi_confidence_min: float = 0.0   # [0..1], 0 = disabled
    # ── VNext Priority 1 & 8 — Dynamic ROI Confidence & Persistence ──────────
    dynamic_roi_confidence_enabled: bool = True
    roi_persistence_score_enabled: bool = True
    # ── VNext Priority 6 — Scroll Direction Memory ───────────────────────────
    scroll_direction_memory_enabled: bool = True
    # ── VNext Priority 9 — DMD Readability Predictor ─────────────────────────
    dmd_readability_score_enabled: bool = True
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
    is_batch: bool = False           # Context flag: True if running within an 8-worker batch

    # ══════════════════════════════════════════════════════════════════════════
    #  Factory & serialisation — SINGLE SOURCE OF TRUTH
    # ══════════════════════════════════════════════════════════════════════════
    # Mapping: params-dict key  →  dataclass field name
    # Keys with mismatched names are listed explicitly below.
    # All other fields use a standard "action_{field_name}" convention.
    _PARAMS_KEY_ALIASES: dict = None   # populated in __init_subclass__; see below

    @staticmethod
    def _build_alias_map():
        """Return {params_dict_key: field_name} with legacy aliases."""
        # Legacy aliases where the dict key doesn't match the field name
        aliases = {
            "action_intro":          "intro_duration",
            "action_bottom_crop":    "bottom_crop_pct",
            "action_top_crop":       "top_crop_pct",
            "action_auto_pillarbox": "auto_pillarbox_crop",
        }
        no_prefix = {
            "bg_sub_enable", "dynamic_scene_detection",
            "dmd_visibility_score_enabled", "dmd_readability_score_enabled",
            "target_width", "target_height",
        }
        field_names = {f.name for f in fields(AutoActionConfig)
                       if not f.name.startswith("_")}
        mapped_fields = set(aliases.values())
        result = dict(aliases)
        for name in field_names:
            if name in mapped_fields:
                continue  # already handled by an alias
            if name in no_prefix:
                result[name] = name
            else:
                result[f"action_{name}"] = name
        return result

    @classmethod
    def _alias_map(cls):
        if cls._PARAMS_KEY_ALIASES is None:
            cls._PARAMS_KEY_ALIASES = cls._build_alias_map()
        return cls._PARAMS_KEY_ALIASES

    # ── from_params : dict → AutoActionConfig ────────────────────────────────
    @classmethod
    def from_params(cls, p: dict, **overrides) -> "AutoActionConfig":
        """Build an AutoActionConfig from a conversion params dict.

        This is the ONLY place that maps dict keys (action_*) to dataclass
        fields.  Used by core.py process_file / process_folder and by
        ffmpeg_converter.py.
        """
        _cast = {str: str, int: int, float: float, bool: bool}
        field_map = {f.name: f for f in fields(cls) if not f.name.startswith("_")}
        kwargs = {}
        for pkey, fname in cls._alias_map().items():
            if fname not in field_map:
                continue
            raw = p.get(pkey)
            if raw is None:
                continue
            ft = field_map[fname].type
            cast_fn = _cast.get(ft)
            if cast_fn is not None:
                kwargs[fname] = cast_fn(raw)
            else:
                kwargs[fname] = raw
        kwargs.update(overrides)
        return cls(**kwargs)

    # ── from_app_state : UI tk-vars → AutoActionConfig ───────────────────────
    @classmethod
    def from_app_state(cls, s, **overrides) -> "AutoActionConfig":
        """Build an AutoActionConfig by reading tk vars from ApplicationState.

        Tries v_action_{field} first, then v_{field}.  Fields without a
        matching tk var keep their dataclass defaults.
        """
        _cast = {str: str, int: int, float: float, bool: bool}
        kwargs = {}
        for f in fields(cls):
            if f.name.startswith("_"):
                continue
            
            prefixes = ("v_",) if f.name in ("target_width", "target_height") else ("v_action_", "v_")
            for prefix in prefixes:
                var = getattr(s, f"{prefix}{f.name}", None)
                if var is not None and hasattr(var, "get"):
                    raw = var.get()
                    cast_fn = _cast.get(f.type)
                    if cast_fn is not None:
                        kwargs[f.name] = cast_fn(raw)
                    else:
                        kwargs[f.name] = raw
                    break
        kwargs.update(overrides)
        return cls(**kwargs)

    # ── to_params_dict : AutoActionConfig → dict ─────────────────────────────
    def to_params_dict(self) -> dict:
        """Export to a params dict with the correct key names.

        Inverse of from_params().  Used by _collect_params() so that
        new fields are automatically propagated to the conversion engine.
        """
        result = {}
        for pkey, fname in self._alias_map().items():
            result[pkey] = getattr(self, fname, None)
        return result

    # ── copy : shallow clone (thread-safe per-file configs) ──────────────────
    def copy(self, **overrides) -> "AutoActionConfig":
        """Create a shallow copy, optionally overriding fields."""
        return _dc_replace(self, **overrides)

