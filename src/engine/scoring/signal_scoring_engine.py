"""
Signal Scoring Engine — Layer 1 of the Scoring V2 architecture.

PURPOSE
-------
Observe. Measure. Describe.

NEVER decide. NEVER filter. NEVER select. NEVER reject.

This module behaves like a pure sensor system.
It extracts numerical information from frames and returns it in a
structured FrameSignalScore object.

The engine has no knowledge of:
  - thresholds
  - rankings
  - selection rules
  - frame retention rules
  - business rules
  - DMD-specific constraints

All of those belong exclusively in FinalScoringEngine (Layer 2).

OUTPUT
------
FrameSignalScore — a fully typed dataclass with Optional fields
(None = "signal not computed" rather than 0.0, which would be misleading).

INTEGRATION
-----------
This module is purely additive. It does NOT modify any existing interface.
It does NOT wrap or replace IScorer, DMDVisibilityScore, or DMDReadabilityScore.
Those continue to function exactly as before.

The SignalScoringEngine MAY call IDetector for subject-based signals,
but it does so without tight coupling: the detector is injected, optional,
and its absence merely results in None values for subject/face fields.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    # Avoid circular imports at runtime — only used for type hints
    from src.engine.auto_action.interfaces import IDetector

logger = logging.getLogger(__name__)

BoundingBox = Tuple[int, int, int, int]  # (x, y, w, h)


# ---------------------------------------------------------------------------
# Output object — Layer 1
# ---------------------------------------------------------------------------

@dataclass
class FrameSignalScore:
    """
    Pure measurement result for a single frame.

    All fields are Optional[float] in range [0.0, 1.0] unless stated otherwise.
    None means "not computed" (e.g. detector unavailable, first frame).
    0.0 means the signal was computed and its value is zero.

    Do NOT add decision logic, thresholds, or weights to this class.
    """

    # ── Motion & Dynamics ────────────────────────────────────────────────────
    motion_score: Optional[float] = None
    """Normalized magnitude of pixel-level change between consecutive frames.
    High → lots of motion. Range [0, 1]. None on first frame (no previous)."""

    optical_flow_score: Optional[float] = None
    """Mean optical flow magnitude (Farneback). Heavier than motion_score but
    more accurate for directional motion. None if OpenCV unavailable. Range [0, 1]."""

    stability_score: Optional[float] = None
    """Temporal consistency: 1 - motion_score. High → stable/static frame.
    None on first frame. Range [0, 1]."""

    # ── Perceptual Quality ───────────────────────────────────────────────────
    entropy_score: Optional[float] = None
    """Shannon entropy of the grayscale histogram, normalized to [0, 1].
    High → rich information content, complex scene.
    Low → flat/uniform/dark/overexposed frame."""

    contrast_score: Optional[float] = None
    """Normalized RMS contrast (std dev of grayscale / 128). Range [0, 1].
    High → strong contrast, DMD-readable. Low → washed out or very dark."""

    saliency_score: Optional[float] = None
    """Estimated visual attention density: proportion of frame covered by
    high-saliency regions (spectral residual approximation). Range [0, 1]."""

    edge_density_score: Optional[float] = None
    """Fraction of pixels classified as edges (Canny). High → detail-rich.
    Low → flat/empty or extremely blurry. Range [0, 1]."""

    # ── Subject / Object Signals ─────────────────────────────────────────────
    subject_score: Optional[float] = None
    """Subject size relative to frame area. Larger detected ROI → higher score.
    Range [0, 1]. None if detector unavailable or no detection."""

    face_score: Optional[float] = None
    """Placeholder for face confidence. None until face detection is supported.
    When implemented: detection confidence × normalized size. Range [0, 1]."""

    object_score: Optional[float] = None
    """Object detection confidence (primary detection from IDetector).
    Range [0, 1]. None if detector unavailable."""

    subject_centering_score: Optional[float] = None
    """How centered is the detected subject (1 = perfectly centered, 0 = at edge).
    Range [0, 1]. None if no detection."""

    # ── DMD-Specific Signals ─────────────────────────────────────────────────
    readability_score: Optional[float] = None
    """Proxy for how readable the frame will be on a 128×32 DMD after resize.
    Combines contrast_score and edge_density_score with DMD-specific weights.
    Range [0, 1]. This is a SIGNAL, not a decision."""

    attention_score: Optional[float] = None
    """Estimated visual attention concentration: product of saliency and
    subject_centering. High → a salient, centered subject. Range [0, 1]."""

    # ── Metadata ─────────────────────────────────────────────────────────────
    frame_idx: int = -1
    """Source frame index in the video (0-based). -1 = unknown."""

    is_dark: bool = False
    """True if the frame is too dark for reliable analysis (mean luminance < threshold)."""

    has_detection: bool = False
    """True if the IDetector returned a bounding box for this frame."""

    roi: Optional[BoundingBox] = None
    """Raw bounding box (x, y, w, h) returned by the detector, if any."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class SignalScoringEngine:
    """
    Extracts FrameSignalScore from individual frames.

    This class is stateful only for temporal signals (motion, stability)
    that require a reference to the previous frame. All other signals are
    stateless and can be called on isolated frames.

    Parameters
    ----------
    detector : IDetector, optional
        Any IDetector implementation for subject/object signals.
        If None, subject_score, object_score, face_score, and
        subject_centering_score will always be None.
    dark_threshold : float
        Mean grayscale luminance below which a frame is flagged as dark.
        Default: 40.0 (out of 255).
    optical_flow : bool
        If True, compute optical flow (Farneback). More expensive but more
        accurate than simple frame difference. Default: False.
    """

    _DARK_THRESHOLD_DEFAULT: float = 40.0

    def __init__(
        self,
        detector: Optional["IDetector"] = None,
        dark_threshold: float = _DARK_THRESHOLD_DEFAULT,
        optical_flow: bool = False,
    ) -> None:
        self._detector = detector
        self._dark_threshold = dark_threshold
        self._optical_flow = optical_flow

        # Temporal state — only these two are stateful
        self._prev_gray: Optional[np.ndarray] = None
        self._frame_count: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset temporal state. Call between independent videos."""
        self._prev_gray = None
        self._frame_count = 0

    def score_frame(
        self,
        frame: np.ndarray,
        frame_idx: int = -1,
    ) -> FrameSignalScore:
        """
        Compute all available signals for a single BGR frame.

        Parameters
        ----------
        frame : np.ndarray
            BGR image array (as returned by cv2.VideoCapture.read()).
        frame_idx : int
            Source frame index, stored in the output for traceability.

        Returns
        -------
        FrameSignalScore
            All signals computed for this frame.
            None fields = signal was not computed (not zero!).
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available — returning empty FrameSignalScore.")
            return FrameSignalScore(frame_idx=frame_idx)

        result = FrameSignalScore(frame_idx=frame_idx)

        if frame is None or frame.size == 0:
            result.is_dark = True
            self._frame_count += 1
            return result

        # Convert to grayscale once — reused by all signals
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame.copy()

        # ── Dark frame detection ─────────────────────────────────────────
        mean_lum = float(gray.mean())
        result.is_dark = mean_lum < self._dark_threshold

        # ── Temporal signals (require previous frame) ────────────────────
        if self._prev_gray is not None and not result.is_dark:
            motion = self._compute_motion(gray, self._prev_gray, cv2)
            result.motion_score = motion
            result.stability_score = max(0.0, 1.0 - motion)

            if self._optical_flow:
                result.optical_flow_score = self._compute_optical_flow(
                    gray, self._prev_gray, cv2
                )

        # ── Entropy ─────────────────────────────────────────────────────
        if not result.is_dark:
            result.entropy_score = self._compute_entropy(gray)

        # ── Contrast ────────────────────────────────────────────────────
        result.contrast_score = self._compute_contrast(gray)

        # ── Edge density ─────────────────────────────────────────────────
        result.edge_density_score = self._compute_edge_density(gray, cv2)

        # ── Saliency (lightweight spectral residual) ─────────────────────
        if not result.is_dark:
            result.saliency_score = self._compute_saliency(gray, cv2)

        # ── Subject / object detection ───────────────────────────────────
        if self._detector is not None and not result.is_dark:
            self._apply_detector_signals(frame, gray, result)

        # ── Composite DMD-specific signals ───────────────────────────────
        result.readability_score = self._compute_readability_signal(result)
        result.attention_score = self._compute_attention_signal(result)

        # ── Update temporal state ────────────────────────────────────────
        if not result.is_dark:
            self._prev_gray = gray
        self._frame_count += 1

        return result

    def score_sequence(
        self,
        frames: list,
        start_frame_idx: int = 0,
    ) -> list:
        """
        Score a list of frames. Returns List[FrameSignalScore].

        Parameters
        ----------
        frames : list of np.ndarray
            Sequence of BGR frames in chronological order.
        start_frame_idx : int
            Index of the first frame in the original video (for traceability).
        """
        return [
            self.score_frame(f, frame_idx=start_frame_idx + i)
            for i, f in enumerate(frames)
        ]

    # ------------------------------------------------------------------
    # Private signal extractors
    # All return float in [0.0, 1.0] or raise on unexpected input.
    # All are PURE — no state mutation except _compute_optical_flow (None).
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_motion(
        gray: np.ndarray,
        prev_gray: np.ndarray,
        cv2,
    ) -> float:
        """
        Frame-difference motion: mean absolute pixel change, normalized to [0, 1].

        Value of 1.0 = average pixel changed by 255 (complete scene change).
        Value of 0.0 = frame identical to previous.
        """
        diff = cv2.absdiff(gray, prev_gray)
        return float(np.mean(diff)) / 255.0

    @staticmethod
    def _compute_optical_flow(
        gray: np.ndarray,
        prev_gray: np.ndarray,
        cv2,
    ) -> float:
        """
        Farneback dense optical flow — mean magnitude, normalized to [0, 1].
        More expensive than _compute_motion but direction-aware.
        """
        try:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )
            mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
            # Typical max magnitude for a fast pan is ~30–40 px/frame
            return float(min(1.0, np.mean(mag) / 30.0))
        except Exception:
            return 0.0

    @staticmethod
    def _compute_entropy(gray: np.ndarray) -> float:
        """
        Shannon entropy of the grayscale histogram, normalized to [0, 1].
        Max entropy for 8-bit = log2(256) ≈ 8.0 bits.
        """
        hist, _ = np.histogram(gray.ravel(), bins=256, range=(0, 256))
        hist = hist[hist > 0].astype(np.float64)
        hist /= hist.sum()
        entropy = float(-np.sum(hist * np.log2(hist)))
        return min(1.0, entropy / 8.0)

    @staticmethod
    def _compute_contrast(gray: np.ndarray) -> float:
        """
        RMS contrast: standard deviation of grayscale / 128.
        Normalized to [0, 1]. 1.0 = maximum possible std dev.
        """
        std = float(np.std(gray.astype(np.float32)))
        return min(1.0, std / 128.0)

    @staticmethod
    def _compute_edge_density(gray: np.ndarray, cv2) -> float:
        """
        Fraction of pixels classified as edges via Canny.
        High value → lots of detail / many distinct shapes.
        Low value → flat/blank/blurry content.
        """
        try:
            edges = cv2.Canny(gray, threshold1=50, threshold2=150)
            total = gray.shape[0] * gray.shape[1]
            if total == 0:
                return 0.0
            return float(np.count_nonzero(edges)) / total
        except Exception:
            return 0.0

    @staticmethod
    def _compute_saliency(gray: np.ndarray, cv2) -> float:
        """
        Lightweight spectral residual saliency approximation.

        1. Compute log-amplitude spectrum via FFT.
        2. Subtract smoothed version (spectral residual).
        3. IFFT → saliency map.
        4. Return fraction of frame covered by above-mean saliency.

        This is an O(n log n) approximation that avoids the full
        OpenCV Saliency API (which requires optional contrib modules).
        """
        try:
            # Resize for speed
            small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
            small_f = small.astype(np.float32) / 255.0

            # FFT
            fft = np.fft.fft2(small_f)
            log_amplitude = np.log(np.abs(fft) + 1e-8)
            phase = np.angle(fft)

            # Spectral residual
            kernel_size = 3
            smoothed = cv2.blur(log_amplitude, (kernel_size, kernel_size))
            residual = log_amplitude - smoothed

            # Reconstruct
            recon = np.fft.ifft2(np.exp(residual + 1j * phase))
            saliency_map = np.abs(recon) ** 2

            # Threshold at mean
            mean_sal = float(np.mean(saliency_map))
            fraction = float(np.mean(saliency_map > mean_sal))
            return float(min(1.0, fraction * 2.0))  # scale: 0.5 baseline → 1.0
        except Exception:
            return 0.0

    def _apply_detector_signals(
        self,
        frame: np.ndarray,
        gray: np.ndarray,
        result: FrameSignalScore,
    ) -> None:
        """
        Run the injected IDetector and populate subject/object fields.
        Modifies result in-place. Safe to skip entirely if detector is None.
        """
        try:
            roi = self._detector.detect_person(frame)
            if roi is not None:
                x, y, w, h = roi
                result.has_detection = True
                result.roi = roi

                frame_area = frame.shape[0] * frame.shape[1]
                roi_area = w * h
                result.subject_score = min(1.0, roi_area / max(1, frame_area))

                # Centering: 1 = center, 0 = at edge
                cx_roi = x + w / 2.0
                cy_roi = y + h / 2.0
                cx_frame = frame.shape[1] / 2.0
                cy_frame = frame.shape[0] / 2.0
                max_dist = (cx_frame ** 2 + cy_frame ** 2) ** 0.5
                dist = ((cx_roi - cx_frame) ** 2 + (cy_roi - cy_frame) ** 2) ** 0.5
                result.subject_centering_score = max(0.0, 1.0 - dist / max(1.0, max_dist))

                # Object confidence — use roi area as proxy when no confidence API
                result.object_score = result.subject_score
            else:
                result.has_detection = False
        except Exception as exc:
            logger.debug("Detector signal extraction failed: %s", exc)

    @staticmethod
    def _compute_readability_signal(result: FrameSignalScore) -> Optional[float]:
        """
        Composite DMD readability signal: combination of contrast and edges.

        This is a SIGNAL only — it measures raw perceptual properties.
        The FinalScoringEngine applies business weights and thresholds.
        """
        parts = []
        weights = []
        if result.contrast_score is not None:
            parts.append(result.contrast_score)
            weights.append(0.6)
        if result.edge_density_score is not None:
            parts.append(result.edge_density_score)
            weights.append(0.4)
        if not parts:
            return None
        total_w = sum(weights)
        return float(sum(p * w for p, w in zip(parts, weights)) / total_w)

    @staticmethod
    def _compute_attention_signal(result: FrameSignalScore) -> Optional[float]:
        """
        Attention: product of saliency and subject centering.

        High saliency + centered subject = maximum attention signal.
        None if neither component is available.
        """
        sal = result.saliency_score
        cen = result.subject_centering_score
        if sal is None and cen is None:
            return None
        sal = sal if sal is not None else 0.5  # neutral fallback
        cen = cen if cen is not None else 0.5  # neutral fallback
        return float(sal * cen)
