import numpy as np
import pytest
import cv2
from src.plugins.trackers.tracker import SceneChangeScore

def test_scene_change_score_identical():
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (50, 25), (255, 255, 255), -1)
    score = SceneChangeScore.compute(frame, frame)
    assert score == pytest.approx(1.0, 0.01)

def test_scene_change_score_different():
    frame_a = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame_a, (10, 10), (50, 25), (255, 255, 255), -1)
    frame_b = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame_b, (70, 10), (100, 25), (255, 255, 255), -1)
    score = SceneChangeScore.compute(frame_a, frame_b)
    assert score < 1.0
