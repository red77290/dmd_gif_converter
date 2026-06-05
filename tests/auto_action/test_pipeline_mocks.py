import unittest
from unittest.mock import patch, MagicMock
from src.auto_action.pipeline import preprocess_video_for_dmd
from src.auto_action.config import AutoActionConfig
import numpy as np
import cv2

class TestPipelineMocks(unittest.TestCase):

    @patch("cv2.VideoCapture")
    @patch("src.auto_action.pipeline._FrameDetector.detect")
    @patch("src.auto_action.pipeline.subprocess.Popen")
    @patch("src.auto_action.pipeline.subprocess.run")
    def test_preprocess_video_success(self, mock_run, mock_popen, mock_detect, mock_vc):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: 30.0 if prop == cv2.CAP_PROP_FPS else (100 if prop == cv2.CAP_PROP_FRAME_WIDTH else (50 if prop == cv2.CAP_PROP_FRAME_HEIGHT else 10))
        
        dummy_frame = np.zeros((50, 100, 3), dtype=np.uint8)
        returns = [(True, dummy_frame)] * 5 + [(False, None)]
        mock_cap.read.side_effect = returns
        mock_vc.return_value = mock_cap
        
        mock_detect.return_value = (10, 10, 20, 20)
        
        mock_proc = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.wait.return_value = 0
        mock_popen.return_value = mock_proc
        
        cfg = AutoActionConfig()
        cfg.intro_duration = 0.0
        cfg.detector = "person"
        
        ok, out_path, msg = preprocess_video_for_dmd("dummy.mp4", cfg)
        
        self.assertTrue(ok)
        self.assertIsNotNone(out_path)
        self.assertIn("Auto action OK", msg)
        self.assertTrue(mock_proc.stdin.write.called)

    @patch("cv2.VideoCapture")
    def test_preprocess_video_cv2_fail(self, mock_vc):
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_vc.return_value = mock_cap
        
        cfg = AutoActionConfig()
        ok, out_path, msg = preprocess_video_for_dmd("dummy.mp4", cfg)
        
        self.assertFalse(ok)
        self.assertIsNone(out_path)
        self.assertIn("Could not open source", msg)

if __name__ == "__main__":
    unittest.main()
