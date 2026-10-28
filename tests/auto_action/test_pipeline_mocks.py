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
        mock_writer_proc.stderr.read.side_effect = [b""]
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

    @patch("src.plugins.detectors.detector._FrameDetector.detect")
    @patch("src.engine.auto_action.writer.subprocess.Popen")
    @patch("src.engine.auto_action.pipeline.VideoReader")
    @patch("src.engine.auto_action.pipeline.VideoAnalyzer.analyze")
    @patch("os.path.isfile")
    @patch("src.engine.conversion.ffmpeg_utils.get_metadata")
    def test_preprocess_platformer_zero_intro_downward_drop_does_not_truncate(
        self,
        mock_get_metadata,
        mock_isfile,
        mock_analyze,
        mock_VideoReader,
        mock_writer_popen,
        mock_detect,
    ):
        """Regression test for v8.0.9: zero-intro platformer downward camera slew must never raise UnboundLocalError on CamRect."""
        mock_get_metadata.return_value = (304, 224, 25.0, 4.0)
        mock_isfile.return_value = True

        total_action_frames = 25
        dummy_frame = np.full((224, 304, 3), 48, dtype=np.uint8)
        mock_reader = MagicMock()
        mock_reader.open.return_value = (True, "")
        # 1st read is first_frame_for_intro, followed by 25 action frames + EOF
        mock_reader.read.side_effect = (
            [(True, dummy_frame)]
            + [(True, dummy_frame) for _ in range(total_action_frames)]
            + [(False, None)]
        )
        mock_reader.fps = 25.0
        mock_reader.frame_w = 304
        mock_reader.frame_h = 224
        mock_reader.total_frames = total_action_frames
        mock_VideoReader.return_value = mock_reader

        # Upper platform for first 8 detections, then steep drop to lower platform (> 4% crop_h)
        detections = [(120, 40, 24, 36)] * 8 + [(132, 165, 24, 36)] * 25
        det_idx = {"i": 0}

        def _detect_seq(*args, **kwargs):
            idx = min(det_idx["i"], len(detections) - 1)
            det_idx["i"] += 1
            return detections[idx]

        mock_detect.side_effect = _detect_seq

        mock_writer_proc = MagicMock()
        mock_writer_proc.stdin.write = MagicMock()
        mock_writer_proc.wait.return_value = 0
        mock_writer_proc.stderr.read.side_effect = [b""]
        mock_writer_popen.return_value = mock_writer_proc

        cfg = AutoActionConfig()
        cfg.intro_duration = 0.0
        cfg.platformer_mode = True
        cfg.subsample_frames = 1
        cfg.auto_fast_tracking = False
        cfg.smoothness = 0.82
        cfg.detector = "person"

        ok, out_path, msg = preprocess_video_for_dmd("platformer_drop.mp4", cfg)

        self.assertTrue(ok)
        self.assertIsNotNone(out_path)
        self.assertIn("Auto action OK", msg)
        # Every single action frame (+ >=1 tail frame) must be written, never truncated to ~2 frames
        self.assertGreaterEqual(mock_writer_proc.stdin.write.call_count, total_action_frames)

if __name__ == "__main__":
    unittest.main()
