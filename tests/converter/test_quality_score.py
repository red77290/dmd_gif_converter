import numpy as np
from src.converter.quality import _evaluate_dmd_frame, _get_rating

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
    from src.converter.quality import load_score_sidecar, _save_score_sidecar
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
