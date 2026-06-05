"""
Tests unitaires pour dmd_auto_action.py

Couvre :
  - available_detectors()
  - AutoActionConfig (dataclass — valeurs par défaut et personnalisées)
  - _clamp()
  - _build_camera_rect()
  - _smooth()
  - _crop_frame()
  - preprocess_video_for_dmd() — chemin d'erreur sans OpenCV
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.auto_action.main import (
    AutoActionConfig,
    _FloorEstimator,
    _build_camera_rect,
    _calculate_dmd_visibility_score,
    _clamp,
    _compute_auto_crop_margins,
    _crop_frame,
    _smart_auto_crop_decision,
    _smooth,
    available_detectors,
    preprocess_video_for_dmd,
)
from src.auto_action.main import _compute_scene_change_score
from src.auto_action.main import _apply_look_ahead
from src.auto_action.main import _fuse_rois

class TestPreprocessVideoForDmd(unittest.TestCase):

    def test_missing_file_returns_false(self):
        """Un chemin de fichier inexistant doit échouer proprement."""
        ok, out, msg = preprocess_video_for_dmd("__nonexistent__.mp4", AutoActionConfig())
        self.assertFalse(ok)
        self.assertIsNone(out)
        self.assertIsInstance(msg, str)
        self.assertGreater(len(msg), 0)

    def test_opencv_unavailable_returns_false(self):
        """Sans OpenCV, la fonction doit retourner False avec un message."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("cv2 not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            ok, out, msg = preprocess_video_for_dmd("any.mp4", AutoActionConfig())

        self.assertFalse(ok)
        self.assertIsNone(out)
        self.assertIn("OpenCV", msg)

    def test_available_detectors_are_valid(self):
        """Chaque mode de détecteur doit être dans la liste autorisée."""
        for mode in available_detectors():
            self.assertIn(mode, ["person", "motion", "hybrid", "center"])

if __name__ == "__main__":
    unittest.main()
