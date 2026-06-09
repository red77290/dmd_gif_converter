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
from src.plugins.scorers.dmd_scorers import DMDVisibilityScore, SceneChangeScore