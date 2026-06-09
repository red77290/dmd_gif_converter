import unittest
from unittest.mock import patch, MagicMock
import numpy as np

from src.auto_action.ai_moments import AiMomentsEngine, AiMoment

class TestAiMomentsEngine(unittest.TestCase):
    @patch('cv2.VideoCapture')
    def test_run_analysis_basic(self, mock_cv2_cap):
        # Mock video capture
        mock_cap_instance = MagicMock()
        mock_cap_instance.isOpened.return_value = True
        
        # Return 25 FPS, 250 frames (10 seconds)
        def mock_get(prop_id):
            if prop_id == 5: # cv2.CAP_PROP_FPS
                return 25.0
            if prop_id == 7: # cv2.CAP_PROP_FRAME_COUNT
                return 250.0
            return 0.0
            
        mock_cap_instance.get.side_effect = mock_get
        
        # Mock reading 250 frames
        mock_frames = [(True, np.random.randint(0, 255, (180, 320, 3), dtype=np.uint8)) for _ in range(250)] + [(False, None)]
        mock_cap_instance.read.side_effect = mock_frames
        
        mock_cv2_cap.return_value = mock_cap_instance

        options = {
            "moments_count": 3,
            "crit_action": True,
            "crit_epic": True,
            "crit_loopable": True,
            "crit_dmd": True,
            "strategy": "Balanced",
            "dur_mode": "Auto"
        }
        
        progress_updates = []
        def progress_cb(task, prog):
            progress_updates.append((task, prog))
            
        engine = AiMomentsEngine("dummy.mp4", options, progress_cb)
        
        results = engine.run()
        
        # We requested 3 moments, so we should get up to 3 moments
        self.assertLessEqual(len(results), 3)
        self.assertGreater(len(results), 0)
        
        moment = results[0]
        self.assertIsInstance(moment, AiMoment)
        
        # Validate scores
        self.assertTrue(0 <= moment.scores["Action"] <= 100)
        self.assertTrue(0 <= moment.scores["Epic"] <= 100)
        self.assertTrue(0 <= moment.scores["Loopable"] <= 100)
        self.assertTrue(0 <= moment.scores["DMD Visibility"] <= 100)
        self.assertTrue(0 <= moment.overall_score <= 100)
        
        # Check non-overlap
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                # If they overlap, the gap between end of one and start of another should not be small
                r1 = results[i]
                r2 = results[j]
                overlap = not (r1.end_time < r2.start_time + 1.0 or r1.start_time > r2.end_time - 1.0)
                self.assertFalse(overlap, "Moments overlap too much")

    @patch('cv2.VideoCapture')
    def test_cancel_analysis(self, mock_cv2_cap):
        mock_cap_instance = MagicMock()
        mock_cap_instance.isOpened.return_value = True
        mock_cap_instance.get.return_value = 25.0
        
        def slow_read():
            return (True, np.zeros((100, 100, 3), dtype=np.uint8))
            
        mock_cap_instance.read.side_effect = slow_read
        mock_cv2_cap.return_value = mock_cap_instance
        
        engine = AiMomentsEngine("dummy.mp4", {}, lambda t, p: None)
        
        import threading
        def cancel_later():
            import time
            time.sleep(0.05)
            engine.cancel()
            
        threading.Thread(target=cancel_later).start()
        
        results = engine.run()
        self.assertEqual(len(results), 0)

if __name__ == '__main__':
    unittest.main()
