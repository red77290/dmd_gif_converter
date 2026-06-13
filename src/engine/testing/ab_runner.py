import os
import glob
import logging
from src.engine.testing.ab_testing_engine import ABTestingEngine

logging.basicConfig(level=logging.INFO, format="%(message)s")

def run_all():
    ai_moment_dir = "tests/resources/ai_moment"
    use_cases_dir = "tests/resources/use_cases"
    
    # 1. AI Moments (Movies)
    if os.path.exists(ai_moment_dir):
        movies = glob.glob(os.path.join(ai_moment_dir, "*.mkv")) + glob.glob(os.path.join(ai_moment_dir, "*.avi"))
        # Limite à 1 pour gagner du temps
        for movie in movies:
            engine = ABTestingEngine(video_path=movie)
            options = {
                "moments_count": 3,
                "count": 3,
                "crit_action": True,
                "crit_epic": True,
                "crit_character": False,
                "crit_loopable": True,
                "crit_dmd": True,
                "strategy": "Balanced",
                "scoring_strategy": "balanced_v2",
                "w_action": 70, "w_epic": 100, "w_character": 40, "w_loopable": 70, "w_dmd": 100,
                "dur_min": 2.0,
                "dur_max": 5.0,
                "auto_framing": True,
                "opt_dmd": True
            }
            engine.run_ai_moments_ab_test(options) # Exécuté sur tout

    # 2. Conversions (Clips)
    if os.path.exists(use_cases_dir):
        clips = glob.glob(os.path.join(use_cases_dir, "*.mkv")) + glob.glob(os.path.join(use_cases_dir, "*.avi"))
        # Limit to first 3 clips for benchmarking speed
        for clip in clips:
            engine = ABTestingEngine(video_path=clip, sample_fps=0)
            engine.run_conversion_ab_test(strategy_names=["baseline_v1", "balanced_v2"])

if __name__ == "__main__":
    run_all()
