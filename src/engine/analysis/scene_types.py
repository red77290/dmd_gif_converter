from typing import Optional
"""Scene type classification for the auto-action framing engine.

Provides a vocabulary of scene types (similar to colorimetry ``mode``) and a
rule-based classifier that maps analysis signals to a ``SceneProfile``.

Usage
-----
Manual selection::

    cfg.scene_type = "platformer"
    profile = SCENE_PROFILES[cfg.scene_type]

Auto-detection (enabled by ``auto_scene_type`` or ``smart_auto_crop``)::

    signals = { "tall_ratio": ..., "fill_ratio": ..., ... }
    profile = classify_scene(signals)
"""

from dataclasses import dataclass
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Scene type constants ─────────────────────────────────────────────────────
# Each value is a valid choice for ``AutoActionConfig.scene_type``.

class SceneType:
    """String constants for supported scene types."""

    # Generic / action
    WIDE_SHOT         = "wide_shot"          # small subjects, lots of background
    ACTION_MOVING     = "action_moving"      # subject moves across frame (RPG, run)
    ACTION_HORIZONTAL = "action_horizontal"  # side-scroller, horizontal scrolling

    # Platformers
    PLATFORMER        = "platformer"         # stable floor, character jumps

    # Fighting
    FIGHTING_2D       = "fighting_2d"        # pixel sprites, versus screen

    # Dialogue / static
    TALKING_CLOSEUP   = "talking_closeup"    # face fills frame, mostly still
    TALKING_MEDIUM    = "talking_medium"     # upper body visible, relatively still

    # Full-body
    FULL_BODY_TALL    = "full_body_tall"     # full body visible, focus on face
    FULL_BODY_MEDIUM  = "full_body_medium"   # medium body fill, generic tracking

    # Isometric / Top-Down
    TOP_DOWN_ISOMETRIC = "top_down_isometric" # Zelda, Pokemon, no gravity

    # Other
    FIRST_PERSON      = "first_person"       # Doom, Minecraft, centered action
    THIRD_PERSON      = "third_person"       # Tomb Raider, Dark Souls, camera behind character
    MENU_STATIC       = "menu_static"        # Title screens, minimal action

    ALL = [
        WIDE_SHOT, ACTION_MOVING, ACTION_HORIZONTAL,
        PLATFORMER, FIGHTING_2D,
        TALKING_CLOSEUP, TALKING_MEDIUM,
        FULL_BODY_TALL, FULL_BODY_MEDIUM,
        TOP_DOWN_ISOMETRIC, FIRST_PERSON, THIRD_PERSON, MENU_STATIC
    ]


# ── Scene profile ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SceneProfile:
    """Complete parameter set implied by a scene type.

    Analogous to a colorimetry preset: each scene type maps to one profile
    that drives face clipping, tracking behaviour, and camera dynamics.
    """

    scene_type: str
    face_priority: bool          # enable face-aware camera positioning
    face_clip_mode: str          # "none" | "closeup" | "full_body_head"
    face_head_frac: float        # head height as fraction of body bbox
    face_eye_offset: Optional[float]  # eye center as fraction from top of head
    platformer_mode: bool        # lock camera to stable floor
    auto_vertical_bias: bool     # enable asymmetric floor EMA
    suggested_strength: float    # tracking tightness (0–1)
    suggested_smoothness: float  # camera smoothing (0–0.98)
    max_zoom_override: Optional[float] = None # override for cfg.zoom_max


# ── Profile presets (one per scene type) ─────────────────────────────────────
# Mirrors the ``_PRESETS`` dict in colorimetry.

SCENE_PROFILES: dict[str, SceneProfile] = {
    SceneType.TALKING_CLOSEUP: SceneProfile(
        scene_type=SceneType.TALKING_CLOSEUP,
        face_priority=True,
        face_clip_mode="closeup",
        face_head_frac=0.40,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.25,
        suggested_smoothness=0.96,
        max_zoom_override=1.05,
    ),
    SceneType.FULL_BODY_TALL: SceneProfile(
        scene_type=SceneType.FULL_BODY_TALL,
        face_priority=True,
        face_clip_mode="full_body_head",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.35,
        suggested_smoothness=0.92,
        max_zoom_override=1.05,
    ),
    SceneType.TALKING_MEDIUM: SceneProfile(
        scene_type=SceneType.TALKING_MEDIUM,
        face_priority=True,
        face_clip_mode="full_body_head",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.30,
        suggested_smoothness=0.94,
        max_zoom_override=1.5,
    ),
    SceneType.FULL_BODY_MEDIUM: SceneProfile(
        scene_type=SceneType.FULL_BODY_MEDIUM,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=True,
        suggested_strength=0.65,
        suggested_smoothness=0.85,
        max_zoom_override=1.5,
    ),
    SceneType.PLATFORMER: SceneProfile(
        scene_type=SceneType.PLATFORMER,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=True,
        auto_vertical_bias=True,
        suggested_strength=0.65,
        suggested_smoothness=0.70,
        max_zoom_override=1.05,
    ),
    SceneType.FIGHTING_2D: SceneProfile(
        scene_type=SceneType.FIGHTING_2D,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=True,        # FIX: Now anchors to floor like a platformer!
        auto_vertical_bias=True,
        suggested_strength=0.70,
        suggested_smoothness=0.80,
        max_zoom_override=1.05,
    ),

    SceneType.ACTION_HORIZONTAL: SceneProfile(
        scene_type=SceneType.ACTION_HORIZONTAL,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=True,
        suggested_strength=0.65,
        suggested_smoothness=0.85,
        max_zoom_override=1.1,
    ),
    SceneType.WIDE_SHOT: SceneProfile(
        scene_type=SceneType.WIDE_SHOT,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=True,
        suggested_strength=0.40,
        suggested_smoothness=0.90,
        max_zoom_override=2.0,
    ),
    SceneType.ACTION_MOVING: SceneProfile(
        scene_type=SceneType.ACTION_MOVING,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=True,
        suggested_strength=0.65,
        suggested_smoothness=0.85,
        max_zoom_override=1.6,
    ),
    SceneType.TOP_DOWN_ISOMETRIC: SceneProfile(
        scene_type=SceneType.TOP_DOWN_ISOMETRIC,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=True,
        suggested_strength=0.60,
        suggested_smoothness=0.80,
        max_zoom_override=1.3,
    ),
    SceneType.FIRST_PERSON: SceneProfile(
        scene_type=SceneType.FIRST_PERSON,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.0,      # Lock camera to center
        suggested_smoothness=0.98,   # High smoothing so it doesn't shake
        max_zoom_override=1.0,       # No zoom
    ),
    SceneType.THIRD_PERSON: SceneProfile(
        scene_type=SceneType.THIRD_PERSON,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.30,     # Slight tracking but mostly centered
        suggested_smoothness=0.90,   # Smooth tracking
        max_zoom_override=1.1,       # Very slight zoom allowed
    ),
    SceneType.MENU_STATIC: SceneProfile(
        scene_type=SceneType.MENU_STATIC,
        face_priority=False,
        face_clip_mode="none",
        face_head_frac=0.22,
        face_eye_offset=None,
        platformer_mode=False,
        auto_vertical_bias=False,
        suggested_strength=0.0,
        suggested_smoothness=0.98,
        max_zoom_override=1.0,
    ),
}

# Default profile when no classification is active.
DEFAULT_SCENE_PROFILE = SCENE_PROFILES[SceneType.ACTION_MOVING]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def classify_scene(signals: dict) -> tuple[SceneProfile, list[str]]:
    """Auto-detect scene type from analysis signals using a scoring matrix.

    Parameters
    ----------
    signals : dict
        Expected keys (all optional, with sensible defaults):
        - tall_ratio      : float  — median_height / dmd_crop_h
        - fill_ratio      : float  — median_height / frame_h
        - body_aspect     : float  — median_height / median_width
        - floor_in_lower  : bool   — floor in lower 50% of frame
        - floor_var_score : float  — std of floor positions / frame_h
        - x_variance      : float  — variance of x centers (normalised)

    Returns
    -------
    SceneProfile
        The best-matching profile for the detected scene type.
    """
    scores = {st: 0.0 for st in SceneType.ALL}

    tall_ratio      = signals.get("tall_ratio", 0.0)
    fill_ratio      = signals.get("fill_ratio", 0.0)
    body_aspect     = signals.get("body_aspect", 1.0)
    floor_in_lower  = signals.get("floor_in_lower", False)
    floor_var_score = signals.get("floor_var_score", 1.0)
    x_variance      = signals.get("x_variance", 0.0)
    y_variance      = signals.get("y_variance", 0.0)

    # 1. Floor stability -> Platformer / Horizontal
    if floor_in_lower:
        if floor_var_score <= 0.25:
            # The more stable the floor, the higher the platformer score
            scores[SceneType.PLATFORMER] += 3.0 * (1.0 - floor_var_score/0.25)
            scores[SceneType.ACTION_HORIZONTAL] += 1.0
        else:
            scores[SceneType.ACTION_HORIZONTAL] += 1.5
            scores[SceneType.FIGHTING_2D] += 1.0
            scores[SceneType.PLATFORMER] -= 2.0

    # 2. Fill Ratio -> Closeups / Wide shots
    is_massive_subject = fill_ratio >= 0.40
    # Dialogue/talking scenes have no floor; if the subject is massive, any detected
    # "floor" at the bottom of the bounding box is actually just the body boundary.
    has_dialogue_floor = floor_in_lower and not is_massive_subject

    # Top-Down Isometric scenes never contain large subjects filling the frame
    if fill_ratio >= 0.30:
        scores[SceneType.TOP_DOWN_ISOMETRIC] -= 5.0

    if fill_ratio >= 0.50:
        # If the subject is extremely close (fill_ratio >= 0.70), relax body aspect checks
        if (body_aspect <= 1.4 and body_aspect >= 0.85) or fill_ratio >= 0.70:
            scores[SceneType.TALKING_CLOSEUP] += 5.0
        # Only give TALKING_MEDIUM points if there is NO floor (i.e. it's truly a conversation scene)
        if not has_dialogue_floor:
            scores[SceneType.TALKING_MEDIUM] += 2.0
        scores[SceneType.PLATFORMER] -= 5.0  # Big subjects are not platformers
        scores[SceneType.ACTION_HORIZONTAL] -= 5.0
        scores[SceneType.ACTION_MOVING] -= 5.0
        scores[SceneType.FIGHTING_2D] -= 3.0
    elif fill_ratio >= 0.25:
        # Only give talking points if there is no floor signal at all
        if not has_dialogue_floor:
            scores[SceneType.TALKING_MEDIUM] += 2.0
            scores[SceneType.FULL_BODY_MEDIUM] += 1.0
        else:
            # Subject fills medium portion of screen + floor detected = fighting_2d or platformer
            scores[SceneType.FIGHTING_2D] += 1.5
        if fill_ratio >= 0.35:
            scores[SceneType.PLATFORMER] -= 2.0
            scores[SceneType.ACTION_HORIZONTAL] -= 2.0
    elif fill_ratio < 0.15:
        if floor_in_lower and floor_var_score <= 0.25:
            # Small character but stable floor -> zoomed out platformer
            scores[SceneType.PLATFORMER] += 1.5
            scores[SceneType.WIDE_SHOT] += 1.0
        else:
            # If the camera perfectly tracks a tiny subject, it's a game, not a cinematic wide shot.
            if x_variance < 0.005 and y_variance < 0.005:
                scores[SceneType.PLATFORMER] += 1.5
                scores[SceneType.ACTION_HORIZONTAL] += 1.5
                scores[SceneType.WIDE_SHOT] += 0.5
            else:
                scores[SceneType.WIDE_SHOT] += 3.0

    # 3. Tall Ratio + Aspect -> Full body / Fighting
    if tall_ratio >= 0.60 and body_aspect > 1.4:
        scores[SceneType.FULL_BODY_TALL] += 3.0
        scores[SceneType.FIGHTING_2D] += 0.5
        scores[SceneType.PLATFORMER] -= 3.0
        scores[SceneType.MENU_STATIC] -= 2.0
        
    if body_aspect > 1.6:
        # Very tall bodies are humans/anime characters, not platformer sprites
        scores[SceneType.PLATFORMER] -= 3.0
    elif tall_ratio >= 0.35 and body_aspect > 1.2:
        scores[SceneType.FIGHTING_2D] += 1.0
        
    # 3b. Wide Aspect -> Fighting / Action (not a single face)
    if body_aspect < 0.85:
        scores[SceneType.TALKING_CLOSEUP] -= 3.0
        scores[SceneType.ACTION_HORIZONTAL] += 1.0
        if x_variance >= 0.02:
            scores[SceneType.FIGHTING_2D] += 2.0

    # 4. X-Variance -> Movement
    if x_variance >= 0.05:
        # Huge subjects moving fast laterally are fighting games. Small are platformers.
        if fill_ratio >= 0.35:
            scores[SceneType.FIGHTING_2D] += 2.0
        else:
            scores[SceneType.PLATFORMER] += 2.0
        
        scores[SceneType.ACTION_HORIZONTAL] += 1.5
        scores[SceneType.ACTION_MOVING] += 1.0
        
        # If it's a massive subject (like a face filling the screen), 
        # panning/moving doesn't mean it's suddenly a fighting game!
        if not is_massive_subject:
            scores[SceneType.TALKING_CLOSEUP] -= 3.0
            scores[SceneType.TALKING_MEDIUM] -= 2.0
    else:
        # Static subject: only award talking points if there is NO floor
        # A perfectly-centered game follow-camera has x_variance ~0 but is NOT a conversation scene.
        if not has_dialogue_floor:
            scores[SceneType.TALKING_CLOSEUP] += 1.0
            scores[SceneType.TALKING_MEDIUM] += 1.0
        # Penalize talking-style classifications if a floor was found
        else:
            scores[SceneType.TALKING_MEDIUM] -= 2.0
            scores[SceneType.TALKING_CLOSEUP] -= 2.0

    # 5. Isometric Top-Down: High movement in both X and Y, no stable floor
    if x_variance >= 0.02 and y_variance >= 0.02 and floor_var_score > 0.4:
        # Both X and Y are active, and the floor is very unstable or nonexistent.
        # Guard: a large or square subject (face, close-up) can NOT be isometric even if it wiggles.
        # Anime expressions / hair animations cause bounding box jitter that triggers this falsely.
        if fill_ratio < 0.30 and body_aspect < 1.2:
            scores[SceneType.TOP_DOWN_ISOMETRIC] += 3.0
            scores[SceneType.PLATFORMER] -= 2.0
        else:
            # It's a face or large close-up that moves -> classify as talking/full body
            scores[SceneType.TALKING_CLOSEUP] += 2.0
            scores[SceneType.FULL_BODY_TALL] += 1.0
            scores[SceneType.TOP_DOWN_ISOMETRIC] -= 3.0

    # 6. Static Menu / Still Scene: Very low movement
    if x_variance < 0.005 and y_variance < 0.005:
        # A perfectly centered follow-camera has ~0 variance! 
        # If there is a floor, it's a game, not a static menu.
        if not has_dialogue_floor:
            scores[SceneType.PLATFORMER] -= 3.0
            if fill_ratio >= 0.4:
                # Huge static subject -> portrait or closeup, NOT a menu
                scores[SceneType.TALKING_CLOSEUP] += 2.0
                scores[SceneType.TALKING_MEDIUM] += 2.0
                scores[SceneType.MENU_STATIC] -= 2.0
            elif fill_ratio >= 0.2:
                scores[SceneType.TALKING_MEDIUM] += 2.0
                scores[SceneType.MENU_STATIC] += 0.5
            else:
                scores[SceneType.MENU_STATIC] += 3.0
        else:
            # Floor detected + zero variance = perfectly locked camera (game with follow-cam)
            # Do NOT give talking/menu points; reinforce platform/fighting instead.
            scores[SceneType.TALKING_MEDIUM] -= 3.0
            scores[SceneType.MENU_STATIC] -= 3.0
            scores[SceneType.PLATFORMER] += 1.0

    # Add small default bias to moving action as the safest fallback
    scores[SceneType.ACTION_MOVING] += 0.5

    # Tie-breaking priority order (index 0 is highest priority on tie)
    priority_order = [
        SceneType.MENU_STATIC,
        SceneType.TALKING_CLOSEUP,
        SceneType.TOP_DOWN_ISOMETRIC,
        SceneType.FIRST_PERSON,
        SceneType.THIRD_PERSON,
        SceneType.PLATFORMER,
        SceneType.FIGHTING_2D,
        SceneType.FULL_BODY_TALL,
        SceneType.ACTION_HORIZONTAL,
        SceneType.TALKING_MEDIUM,
        SceneType.FULL_BODY_MEDIUM,
        SceneType.WIDE_SHOT,
        SceneType.ACTION_MOVING,  # Fallback
    ]

    # Select the scene type with the max score, using priority_order as tie-breaker
    best_type = max(scores.keys(), key=lambda st: (scores[st], -priority_order.index(st)))

    scoreboard_lines = ["\n=== Scene Classification Scoreboard ==="]
    for st in sorted(scores.keys(), key=lambda k: (-scores[k], priority_order.index(k))):
        marker = ">> " if st == best_type else "   "
        scoreboard_lines.append(f"{marker}{st:<20} : {scores[st]:>5.1f}")
    scoreboard_lines.append("=======================================")

    return SCENE_PROFILES[best_type], scoreboard_lines, scores
