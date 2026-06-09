import numpy as np
import pytest
import cv2
from src.plugins.scorers.dmd_scorers import DMDReadabilityScore, DMDVisibilityScore, SceneChangeScore

def test_dmd_readability_score_empty():
    empty_frame = np.array([])
    assert DMDReadabilityScore.compute(empty_frame) == 0.0

def test_dmd_readability_score_black():
    black_frame = np.zeros((32, 128, 3), dtype=np.uint8)
    score = DMDReadabilityScore.compute(black_frame)
    # No contrast and no valid shapes
    assert score < 0.2

def test_dmd_readability_score_good_contrast():
    # Create a frame with clear contrasting shapes
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (40, 20), (255, 255, 255), -1)
    cv2.rectangle(frame, (60, 5), (90, 25), (200, 200, 200), -1)
    
    score = DMDReadabilityScore.compute(frame)
    # Should be quite readable (contrast + distinct shapes)
    assert score > 0.4

def test_dmd_visibility_score_empty():
    assert DMDVisibilityScore.compute(np.array([])) == 0.0

def test_dmd_visibility_score_basic():
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (50, 25), (255, 255, 255), -1)
    score = DMDVisibilityScore.compute(frame)
    assert score > 0.1

def test_dmd_visibility_score_with_rect():
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    cv2.rectangle(frame, (10, 10), (50, 25), (255, 255, 255), -1)
    score_no_rect = DMDVisibilityScore.compute(frame)
    score_with_rect = DMDVisibilityScore.compute(frame, (10, 10, 40, 15))
    assert score_with_rect > score_no_rect

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
