import unittest
from unittest.mock import patch, MagicMock
from src.engine.conversion.ffmpeg_utils import (
    _check_drawtext, _apply_text_overlay_pillow, snap_to_clean_fps, get_metadata
)

class TestFfmpegUtils(unittest.TestCase):
    def test_snap_to_clean_fps(self):
        self.assertEqual(snap_to_clean_fps(11.0), 10.0)
        self.assertEqual(snap_to_clean_fps(24.0), 25.0)
        self.assertEqual(snap_to_clean_fps(19.0), 20.0)
        self.assertEqual(snap_to_clean_fps(5.0), 10.0)  # min bound
        self.assertEqual(snap_to_clean_fps(30.0), 25.0) # max bound
        self.assertEqual(snap_to_clean_fps(12.5), 12.5)

    @patch("src.engine.conversion.ffmpeg_utils.subprocess.run")
    def test_check_drawtext_available(self, mock_run):
        mock_run.return_value = MagicMock(stdout="drawtext filter", stderr="")
        import src.engine.conversion.ffmpeg_utils as m
        m._drawtext_available = None
        self.assertTrue(_check_drawtext())

    @patch("src.engine.conversion.ffmpeg_utils.subprocess.run")
    def test_check_drawtext_unavailable(self, mock_run):
        mock_run.return_value = MagicMock(stdout="nothing", stderr="")
        import src.engine.conversion.ffmpeg_utils as m
        m._drawtext_available = None
        self.assertFalse(_check_drawtext())

    @patch("src.engine.conversion.ffmpeg_utils.subprocess.run")
    def test_get_metadata_success(self, mock_run):
        mock_stdout = '{"streams": [{"width": 100, "height": 200, "avg_frame_rate": "30/1"}], "format": {"duration": "10.5"}}'
        mock_run.return_value = MagicMock(stdout=mock_stdout)
        w, h, fps, dur = get_metadata("fake.mp4")
        self.assertEqual(w, 100)
        self.assertEqual(h, 200)
        self.assertEqual(fps, 30.0)
        self.assertEqual(dur, 10.5)

    @patch("src.engine.conversion.ffmpeg_utils.subprocess.run", side_effect=Exception("error"))
    def test_get_metadata_failure(self, mock_run):
        w, h, fps, dur = get_metadata("fake.mp4")
        self.assertIsNone(w)
        self.assertIsNone(h)
        self.assertEqual(fps, 25.0)
        self.assertEqual(dur, 0.0)

if __name__ == "__main__":
    unittest.main()
