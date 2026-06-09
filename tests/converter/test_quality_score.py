import numpy as np
import pytest
from src.engine.conversion.quality import (
    _evaluate_dmd_frame, _get_rating, _fallback_result,
    _save_score_sidecar, load_score_sidecar, evaluate_gif_quality,
)

def test_evaluate_dmd_frame_empty():
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    res = _evaluate_dmd_frame(frame)
    assert res["score"] < 20
    assert "Screen mostly empty" in res["reasons"]

def test_evaluate_dmd_frame_full():
    frame = np.ones((32, 128, 3), dtype=np.uint8) * 255
    res = _evaluate_dmd_frame(frame)
    assert "Screen too cluttered" in res["reasons"]
    assert "Excellent occupancy" in res["reasons"] # Occupancy is 1.0

def test_get_rating():
    rating, color = _get_rating(25)
    assert rating == "Bad"
    assert color == "🔴"
    
    rating, color = _get_rating(95)
    assert rating == "Excellent"
    assert color == "🌟"

def test_load_score_sidecar(tmp_path):
    from src.engine.conversion.quality import load_score_sidecar, _save_score_sidecar
    import os
    
    gif_path = str(tmp_path / "test.gif")
    
    # Missing sidecar
    assert load_score_sidecar(gif_path) is None
    
    # Save and load
    _save_score_sidecar(gif_path, {"score": 88, "rating": "🌟", "reasons": ["Nice contrast", "Good flow"]})
    assert os.path.exists(gif_path + ".scores.json")
    
    data = load_score_sidecar(gif_path)
    assert data["score"] == 88
    assert data["rating"] == "🌟"
    assert data["reasons"] == ["Nice contrast", "Good flow"]
    assert len(data["reasons"]) == 2

def test_evaluate_dmd_frame_none():
    result = _evaluate_dmd_frame(None)
    assert result["score"] == 0.0
    assert "Empty frame" in result["reasons"]


def test_evaluate_dmd_frame_size_zero():
    result = _evaluate_dmd_frame(np.array([]))
    assert result["score"] == 0.0


def test_evaluate_dmd_frame_good_contrast():
    frame = np.zeros((32, 128, 3), dtype=np.uint8)
    frame[8:24, 32:96] = 200
    result = _evaluate_dmd_frame(frame)
    assert result["score"] > 0.3


def test_get_rating_all_thresholds():
    cases = [
        (0,   "Bad"),
        (30,  "Bad"),
        (31,  "Poor"),
        (50,  "Poor"),
        (51,  "Acceptable"),
        (70,  "Acceptable"),
        (71,  "Good"),
        (85,  "Good"),
        (86,  "Excellent"),
        (100, "Excellent"),
    ]
    for score, expected_rating in cases:
        rating, _ = _get_rating(score)
        assert rating == expected_rating, f"score={score}: expected {expected_rating}, got {rating}"


def test_fallback_result_structure():
    r = _fallback_result("File not found")
    assert r["score"] == 0
    assert r["rating"] == "Unknown"
    assert "File not found" in r["reasons"]
    assert r["color"] == "⚪"


def test_evaluate_gif_quality_file_not_found():
    r = evaluate_gif_quality("/nonexistent/path/does_not_exist.gif")
    assert r["score"] == 0
    assert r["rating"] == "Unknown"


def test_save_sidecar_bad_path_no_crash():
    # Should silently pass on permission error
    _save_score_sidecar("/nonexistent_dir_xyz/file.gif", {"score": 80})
