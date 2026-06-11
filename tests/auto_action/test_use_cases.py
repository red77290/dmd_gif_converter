import os
import glob
import cv2
import pytest
import unittest
from unittest.mock import patch

from src.engine.auto_action.pipeline import preprocess_video_for_dmd
from src.engine.config.auto_action_config import AutoActionConfig
import src.engine.auto_action.pipeline as pipeline_mod
import src.plugins.trackers.tracker as tracker_mod
import src.plugins.detectors.detector as detector_mod

USE_CASES_DIR = os.path.join(os.path.dirname(__file__), "..", "resources", "use_cases")

class TestUseCases(unittest.TestCase):
    """
    Semantic test suite for specific GIF use-cases.
    If a GIF is named 'visage.gif', the test verifies that the face is actually 
    kept within the camera crop bounds.
    """

    @classmethod
    def setUpClass(cls):
        os.makedirs(USE_CASES_DIR, exist_ok=True)

    def test_all_gifs_in_use_cases_folder(self):
        video_files = glob.glob(os.path.join(USE_CASES_DIR, "*.gif")) + \
                      glob.glob(os.path.join(USE_CASES_DIR, "*.mp4"))
        
        if not video_files:
            self.skipTest(f"No videos found in {USE_CASES_DIR}. Drop some GIFs/MP4s there to test them!")

        for video_path in video_files:
            with self.subTest(video=os.path.basename(video_path)):
                self._run_semantic_test(video_path)

    def _run_semantic_test(self, gif_path: str):
        filename = os.path.basename(gif_path).lower()
        
        # Use motion detector for platformers, person for faces
        detector_type = "motion" if "platformer" in filename else "person"
        
        cfg = AutoActionConfig(
            detector=detector_type,
            smart_auto_crop=True,
            target_width=128,
            target_height=32,
            intro_duration=0.0,
            smoothness=0.0,
            platformer_mode=("platformer" in filename)
        )
        
        # We will intercept the camera bounds and the detected ROIs
        recorded_rois = []
        recorded_pairs = []

        original_detect = detector_mod._FrameDetector.detect
        original_build_camera_rect = tracker_mod._build_camera_rect

        def mock_build_camera_rect(frame_w, frame_h, passed_roi, cfg, *args, **kwargs):
            cam = original_build_camera_rect(frame_w, frame_h, passed_roi, cfg, *args, **kwargs)
            if passed_roi is None:
                return cam
            # Find the most recently detected full-body ROI
            roi = recorded_rois[-1] if recorded_rois else None
            if roi is not None:
                recorded_pairs.append((roi, cam))
            return cam

        def mock_detect(self_obj, frame, mode="person", *args, **kwargs):
            roi = original_detect(self_obj, frame, mode, *args, **kwargs)
            recorded_rois.append(roi)
            return roi

        with patch("src.plugins.trackers.tracker._build_camera_rect", side_effect=mock_build_camera_rect), \
             patch("src.plugins.detectors.detector._FrameDetector.detect", side_effect=mock_detect, autospec=True):
            
            success, out_path, msg = preprocess_video_for_dmd(gif_path, cfg)
            
        self.assertTrue(success, f"Pipeline failed on {filename}: {msg}")
        
        # --- SEMANTIC ASSERTIONS ---
        if "visage" in filename or "face" in filename or "closeup" in filename:
            # After the fix (v6.1.0+): the camera should be centred on the EYE region.
            #
            # The close-up-to-body regression (old code applied face proportions to a
            # tall body bbox when rh > 40% of frame height, placing the camera at ~42%
            # of body height = waist) is covered by the unit tests in
            # test_tracker_closeup.py::test_full_body_shot_clips_to_head_eye_region.
            #
            # NOTE: For "full_body*" GIFs the full pipeline test is a smoke test only,
            # because face_priority_mode depends on YOLO being available in the analysis
            # phase (detect_person → ONNX). In environments where only motion detection
            # is available, face_priority_mode=False and the camera is at the body centre
            # — which is unavoidable at the pipeline level without YOLO.
            # The aspect-ratio fix in tracker.py protects the eye focus when YOLO IS
            # active; unit tests validate that path directly.
            valid_roi_found = False
            for roi, cam in recorded_pairs:
                valid_roi_found = True
                rx, ry, rw, rh = roi
                cx, cy, cw, ch = cam

                cam_top    = cy - ch / 2.0
                cam_bottom = cy + ch / 2.0

                # Eye zone in the original bbox: roughly 20 %–65 % from top.
                # For face close-ups: the bbox IS the face → eye zone is 20-65 %.
                # For full-body shots: the bbox is the body; with face_priority_mode
                # active the camera will be much higher (~8 %), but with only motion
                # detection available cy ≈ 50 % (body centre) which falls just inside
                # this generous zone thanks to the wide camera window.
                eye_top    = ry + rh * 0.20
                eye_bottom = ry + rh * 0.65

                debug_info = (
                    f"Frame dims: {cam} vs ROI {roi}. "
                    f"Camera [{cam_top:.1f}-{cam_bottom:.1f}] should overlap "
                    f"eye zone [{eye_top:.1f}-{eye_bottom:.1f}]"
                )

                # The camera window must overlap the eye zone.
                self.assertLess(cam_top, eye_bottom, debug_info)
                self.assertGreater(cam_bottom, eye_top, debug_info)

            self.assertTrue(valid_roi_found, f"No person was detected in {filename}.")
            
        if "platformer" in filename:
            rois_y = [roi[1] + roi[3] for roi, cam in recorded_pairs]
            cams_y = [cam[1] for roi, cam in recorded_pairs]
            
            import numpy as np
            if len(rois_y) > 10:
                roi_var = np.var(rois_y)
                cam_var = np.var(cams_y)
                
                if roi_var > 10.0:
                    
                    
                        
                    self.assertLess(cam_var, roi_var * 2.0, f"Camera Y variance ({cam_var:.1f}) is more than 2x ROI Y variance ({roi_var:.1f}). Floor estimator/head protection is too jittery.")

        # Cleanup
        if out_path and os.path.exists(out_path):
            try:
                os.remove(out_path)
                os.rmdir(os.path.dirname(out_path))
            except Exception:
                pass
