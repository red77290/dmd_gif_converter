import os
import glob
import cv2
import pytest
import unittest
from unittest.mock import patch

from src.auto_action.pipeline import preprocess_video_for_dmd
from src.auto_action.config import AutoActionConfig
import src.auto_action.pipeline as pipeline_mod
import src.auto_action.detector as detector_mod

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
            smoothness=0.0
        )
        
        # We will intercept the camera bounds and the detected ROIs
        recorded_rois = []
        recorded_pairs = []

        original_detect = detector_mod._FrameDetector.detect
        original_build_camera_rect = pipeline_mod._build_camera_rect

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

        with patch("src.auto_action.pipeline._build_camera_rect", side_effect=mock_build_camera_rect), \
             patch("src.auto_action.detector._FrameDetector.detect", side_effect=mock_detect, autospec=True):
            
            success, out_path, msg = preprocess_video_for_dmd(gif_path, cfg)
            
        self.assertTrue(success, f"Pipeline failed on {filename}: {msg}")
        
        # --- SEMANTIC ASSERTIONS ---
        if "visage" in filename or "face" in filename:
            # We expect the camera to capture the top part of the detected ROIs (the face/hair)
            valid_roi_found = False
            for roi, cam in recorded_pairs:
                valid_roi_found = True
                rx, ry, rw, rh = roi
                cx, cy, cw, ch = cam
                
                cam_top = cy - ch / 2.0
                cam_bottom = cy + ch / 2.0
                
                # The face is located in the top 30% of the bounding box
                face_top = ry
                face_bottom = ry + rh * 0.30
                
                debug_info = f"Frame dims: {cam} vs ROI {roi}. Camera top {cam_top} is too low, missing the face at {face_top}-{face_bottom}"
                
                self.assertLessEqual(cam_top, face_bottom, debug_info)
                self.assertGreaterEqual(cam_bottom, face_top, debug_info)
            
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
