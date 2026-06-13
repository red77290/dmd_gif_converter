"""
DMD Readability Engine — Pre-conversion quality prediction.

PURPOSE
-------
Estimate how understandable a source frame will remain after it goes
through the full DMD conversion pipeline:

  Source frame
    → Resize to target dimensions (e.g. 128×32)
    → Crop
    → Color quantization (simulated)
    → GIF encoding artifacts (simulated as blur + posterize)
    → Final 128×32 DMD output

This is fundamentally different from the existing DMDReadabilityScore
(in src/plugins/scorers/dmd_scorers.py) which evaluates the *output*
GIF frame *after* conversion. This engine evaluates the *source* frame
*before* conversion, enabling pre-conversion quality prediction and
A/B testing of scoring strategies.

OUTPUT
------
ReadabilityScore — a typed dataclass in range [0.0, 100.0].

INTEGRATION
-----------
Purely additive. Does NOT modify or replace DMDReadabilityScore.
The existing scorer continues to work unchanged on output frames.
This engine is used for input frame selection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output object
# ---------------------------------------------------------------------------

@dataclass
class ReadabilityScore:
    """
    Pre-conversion DMD readability prediction.

    Overall score is in range [0.0, 100.0].
    Higher = the frame is predicted to remain readable on the DMD.

    Individual sub-scores (all in [0.0, 1.0]) are available for
    inspection and debugging. None = not computed.
    """

    overall: float = 0.0
    """Main score [0.0, 100.0]. Higher = more readable on DMD."""

    contrast_preservation: Optional[float] = None
    """How much contrast survives the resize to 128×32. Range [0, 1]."""

    shape_count_score: Optional[float] = None
    """Score based on number of distinct shapes in the simulated output.
    Too few (blank) or too many (clutter) both score low. Range [0, 1]."""

    edge_retention: Optional[float] = None
    """Fraction of edges that survive the downscaling. Range [0, 1]."""

    low_res_interpretability: Optional[float] = None
    """Entropy of the simulated 128×32 output — information content after
    all lossy steps. Range [0, 1]."""

    visual_clutter: Optional[float] = None
    """Inverse of shape count score: 1 = cluttered, 0 = clean. Range [0, 1]."""

    reasons: List[str] = field(default_factory=list)
    """Human-readable observations (no decisions, only descriptions)."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class DmdReadabilityEngine:
    """
    Estimates how readable a source frame will be on a 128×32 DMD.

    The engine simulates the conversion pipeline on the source frame
    and analyzes the result — without actually running FFmpeg.

    Parameters
    ----------
    target_w : int
        Target DMD width (default: 128).
    target_h : int
        Target DMD height (default: 32).
    simulate_dither : bool
        If True, apply a simple posterization step to simulate GIF color
        quantization artifacts. Default: True.
    """

    def __init__(
        self,
        target_w: int = 128,
        target_h: int = 32,
        simulate_dither: bool = True,
    ) -> None:
        self._target_w = target_w
        self._target_h = target_h
        self._simulate_dither = simulate_dither

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]] = None,
    ) -> ReadabilityScore:
        """
        Simulate the DMD pipeline on a source frame and return readability metrics.

        Parameters
        ----------
        frame : np.ndarray
            BGR source frame (full resolution, as from the video).
        roi : tuple (x, y, w, h), optional
            If provided, the frame is cropped to the ROI region before
            simulation (mirrors the auto-action crop behavior).

        Returns
        -------
        ReadabilityScore
            All sub-scores and an overall readability prediction.
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — returning empty ReadabilityScore.")
            return ReadabilityScore(reasons=["OpenCV not available"])

        result = ReadabilityScore()

        if frame is None or frame.size == 0:
            result.reasons.append("Empty frame")
            return result

        # ── Step 1: Crop to ROI if provided ──────────────────────────────
        working = self._apply_roi(frame, roi)

        # ── Step 2: Simulate DMD resize ───────────────────────────────────
        simulated = self._simulate_conversion(working, cv2)
        gray_src = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY) if len(working.shape) == 3 else working
        gray_sim = simulated

        # ── Step 3: Compute sub-scores ────────────────────────────────────
        result.contrast_preservation = self._contrast_preservation(gray_src, gray_sim)
        result.shape_count_score, result.visual_clutter = self._shape_analysis(gray_sim, cv2)
        result.edge_retention = self._edge_retention(gray_src, gray_sim, cv2)
        result.low_res_interpretability = self._low_res_interpretability(gray_sim)

        # ── Step 4: Compose overall score ────────────────────────────────
        result.overall = self._compose_overall(result)

        # ── Step 5: Observations (pure description, no decisions) ─────────
        result.reasons = self._generate_observations(result)

        return result

    def evaluate_sequence(
        self,
        frames: List[np.ndarray],
        rois: Optional[List[Optional[Tuple[int, int, int, int]]]] = None,
    ) -> List[ReadabilityScore]:
        """
        Evaluate readability for a sequence of frames.

        Parameters
        ----------
        frames : List[np.ndarray]
            Sequence of BGR frames.
        rois : List[Optional[Tuple]], optional
            Per-frame ROIs. If None, no ROI crop is applied.
        """
        if rois is None:
            rois = [None] * len(frames)
        return [
            self.evaluate(f, roi=rois[i])
            for i, f in enumerate(frames)
        ]

    # ------------------------------------------------------------------
    # Private simulation helpers
    # ------------------------------------------------------------------

    def _apply_roi(
        self,
        frame: np.ndarray,
        roi: Optional[Tuple[int, int, int, int]],
    ) -> np.ndarray:
        """Crop frame to ROI rectangle if provided and valid."""
        if roi is None:
            return frame
        x, y, w, h = roi
        fh, fw = frame.shape[:2]
        x_int = max(0, int(round(x)))
        y_int = max(0, int(round(y)))
        x2_int = min(fw, int(round(x + w)))
        y2_int = min(fh, int(round(y + h)))
        if x2_int <= x_int or y2_int <= y_int:
            return frame
        return frame[y_int:y2_int, x_int:x2_int]

    def _simulate_conversion(
        self,
        frame: np.ndarray,
        cv2,
    ) -> np.ndarray:
        """
        Simulate the DMD pipeline on the source frame and return a
        grayscale representation of what the DMD will actually display.

        Pipeline:
          1. Resize to target dimensions (128×32)
          2. Convert to grayscale (DMD has no color information for legibility)
          3. If simulate_dither: posterize to 4 levels (simulates GIF quantization)
        """
        try:
            # 1. Resize
            resized = cv2.resize(frame, (self._target_w, self._target_h),
                                 interpolation=cv2.INTER_AREA)

            # 2. Grayscale
            if len(resized.shape) == 3:
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            else:
                gray = resized.copy()

            # 3. Posterize (simulate GIF color reduction)
            if self._simulate_dither:
                levels = 4
                gray = (gray // (256 // levels)) * (256 // levels)
                gray = gray.astype(np.uint8)

            return gray

        except Exception as exc:
            logger.debug("Simulation failed: %s", exc)
            return np.zeros((self._target_h, self._target_w), dtype=np.uint8)

    @staticmethod
    def _contrast_preservation(
        gray_src: np.ndarray,
        gray_sim: np.ndarray,
    ) -> float:
        """
        How much of the source contrast survives the resize.

        Ratio of simulated std dev to source std dev.
        1.0 = perfect preservation. < 1.0 = contrast lost.
        """
        src_std = float(np.std(gray_src))
        sim_std = float(np.std(gray_sim))
        if src_std < 1.0:
            # Source has no contrast — preservation is meaningless
            return 0.0
        return min(1.0, sim_std / src_std)

    @staticmethod
    def _shape_analysis(
        gray_sim: np.ndarray,
        cv2,
    ) -> Tuple[float, float]:
        """
        Count distinct shapes in the simulated output.

        Returns (shape_count_score, visual_clutter).

        Scoring rationale:
          - 0 shapes: nothing visible → shape_score = 0
          - 1–5 shapes: clean, clear → shape_score = 1.0
          - 5–15 shapes: acceptable → shape_score = 0.6
          - > 15 shapes: cluttered → shape_score = 0.2
        """
        try:
            _, thresh = cv2.threshold(
                gray_sim, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
                thresh, connectivity=8
            )
            # Exclude background label 0
            valid_shapes = sum(
                1 for i in range(1, num_labels)
                if stats[i, cv2.CC_STAT_AREA] > 2  # at least 3 pixels
            )
            if valid_shapes == 0:
                shape_score = 0.0
            elif valid_shapes <= 5:
                shape_score = 1.0
            elif valid_shapes <= 15:
                shape_score = 0.6
            else:
                shape_score = 0.2
            clutter = 1.0 - shape_score
            return shape_score, clutter
        except Exception:
            return 0.0, 1.0

    @staticmethod
    def _edge_retention(
        gray_src: np.ndarray,
        gray_sim: np.ndarray,
        cv2,
    ) -> float:
        """
        Fraction of source edge density retained in simulated output.

        Comparison is done on normalized edge density (edges/pixel),
        not absolute counts (sizes differ).
        """
        try:
            edges_src = cv2.Canny(gray_src, 50, 150)
            edges_sim = cv2.Canny(gray_sim, 30, 100)  # lower thresholds for 128×32

            density_src = np.count_nonzero(edges_src) / max(1, edges_src.size)
            density_sim = np.count_nonzero(edges_sim) / max(1, edges_sim.size)

            if density_src < 1e-4:
                # Source has no edges — nothing to preserve
                return 0.0

            return min(1.0, density_sim / density_src)
        except Exception:
            return 0.0

    @staticmethod
    def _low_res_interpretability(gray_sim: np.ndarray) -> float:
        """
        Shannon entropy of the simulated 128×32 output.

        High entropy → rich information survives → more interpretable.
        Low entropy → flat, uniform output → hard to read.
        Normalized to [0, 1] (max = log2(256) ≈ 8.0 bits).
        """
        hist, _ = np.histogram(gray_sim.ravel(), bins=256, range=(0, 256))
        hist = hist[hist > 0].astype(np.float64)
        hist /= hist.sum()
        entropy = float(-np.sum(hist * np.log2(hist)))
        return min(1.0, entropy / 8.0)

    @staticmethod
    def _compose_overall(result: ReadabilityScore) -> float:
        """
        Weighted combination of sub-scores → overall score [0, 100].

        Weights reflect DMD-specific importance:
        - Contrast preservation: most important (60%)
        - Shape count (clarity): important (50%)
        - Edge retention: medium (40%)
        - Low-res interpretability: supplementary (30%)
        """
        pairs = [
            (result.contrast_preservation, 0.60),
            (result.shape_count_score, 0.50),
            (result.edge_retention, 0.40),
            (result.low_res_interpretability, 0.30),
        ]
        total_weight = 0.0
        total_score = 0.0
        for value, weight in pairs:
            if value is not None:
                total_score += value * weight
                total_weight += weight
        if total_weight == 0.0:
            return 0.0
        return min(100.0, (total_score / total_weight) * 100.0)

    @staticmethod
    def _generate_observations(result: ReadabilityScore) -> List[str]:
        """
        Describe the readability score in human-readable terms.

        These are OBSERVATIONS, not decisions.
        """
        obs = []
        if result.contrast_preservation is not None:
            if result.contrast_preservation < 0.3:
                obs.append("Low contrast preservation after resize")
            elif result.contrast_preservation > 0.7:
                obs.append("Strong contrast preserved at 128×32")

        if result.shape_count_score is not None:
            if result.shape_count_score == 0.0:
                obs.append("No visible shapes after conversion")
            elif result.shape_count_score == 1.0:
                obs.append("Clean shape separation (1–5 shapes)")
            elif result.shape_count_score < 0.4:
                obs.append("High visual clutter (>15 shapes)")

        if result.edge_retention is not None:
            if result.edge_retention < 0.2:
                obs.append("Most edges lost during downscaling")
            elif result.edge_retention > 0.6:
                obs.append("Good edge retention after resize")

        if result.low_res_interpretability is not None:
            if result.low_res_interpretability < 0.2:
                obs.append("Very low information content at 128×32")

        if result.overall < 20.0:
            obs.append("Frame unlikely to be readable on DMD")
        elif result.overall > 70.0:
            obs.append("Frame expected to be clearly readable on DMD")

        return obs
