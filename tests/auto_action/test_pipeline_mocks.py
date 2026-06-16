import unittest
from unittest.mock import patch, MagicMock
from src.engine.auto_action.pipeline import preprocess_video_for_dmd
from src.engine.config.auto_action_config import AutoActionConfig
import numpy as np

class TestPipelineMocks(unittest.TestCase):

    @patch("src.plugins.detectors.detector._FrameDetector.detect")
    @patch("src.engine.auto_action.writer.subprocess.Popen")
    @patch("src.engine.auto_action.pipeline.VideoReader")
    @patch("src.engine.auto_action.pipeline.VideoAnalyzer.analyze")
    @patch("os.path.isfile")
    @patch("src.engine.conversion.ffmpeg_utils.get_metadata")
    def test_preprocess_video_success(self, mock_get_metadata, mock_isfile, mock_analyze, mock_VideoReader, mock_writer_popen, mock_detect):
        mock_get_metadata.return_value = (100, 50, 30.0, 10.0)
        mock_isfile.return_value = True
        
        mock_reader = MagicMock()
        mock_reader.open.return_value = (True, "")
        dummy_frame = np.zeros((50, 100, 3), dtype=np.uint8)
        mock_reader.read.side_effect = [(True, dummy_frame)] * 5 + [(False, None)]
        mock_reader.fps = 30.0
        mock_reader.frame_w = 100
        mock_reader.frame_h = 50
        mock_reader.total_frames = 10
        mock_VideoReader.return_value = mock_reader
        
        mock_detect.return_value = (10, 10, 20, 20)
        
        mock_writer_proc = MagicMock()
        mock_writer_proc.stdin.write = MagicMock()
        mock_writer_proc.wait.return_value = 0
        mock_writer_popen.return_value = mock_writer_proc
        
        cfg = AutoActionConfig()
        cfg.intro_duration = 0.0
        cfg.detector = "person"
        
        ok, out_path, msg = preprocess_video_for_dmd("dummy.mp4", cfg)
        
        self.assertTrue(ok)
        self.assertIsNotNone(out_path)
        self.assertIn("Auto action OK", msg)

    @patch("src.engine.auto_action.pipeline.VideoReader")
    @patch("src.engine.auto_action.pipeline.VideoAnalyzer.analyze")
    @patch("src.engine.conversion.ffmpeg_utils.get_metadata")
    def test_preprocess_video_cv2_fail(self, mock_get_metadata, mock_analyze, mock_VideoReader):
        mock_get_metadata.return_value = (100, 50, 30.0, 10.0)
        
        mock_reader = MagicMock()
        mock_reader.open.return_value = (False, "Could not open source")
        mock_VideoReader.return_value = mock_reader
        
        cfg = AutoActionConfig()
        ok, out_path, msg = preprocess_video_for_dmd("dummy.mp4", cfg)
        
        self.assertFalse(ok)
        self.assertIsNone(out_path)
        self.assertIn("Could not open source", msg)

if __name__ == "__main__":
    unittest.main()
