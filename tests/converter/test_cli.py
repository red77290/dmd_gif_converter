import unittest
import argparse
from src.engine.conversion.cli import _build_parser

class TestCliArgs(unittest.TestCase):
    def setUp(self):
        self.parser = _build_parser()
        
    def test_ai_moments_flags(self):
        args = self.parser.parse_args(["--ai-moments", "--ai-moments-count", "5", "--ai-moments-strategy", "Action"])
        self.assertTrue(args.ai_moments)
        self.assertEqual(args.ai_moments_count, 5)
        self.assertEqual(args.ai_moments_strategy, "Action")
        
    def test_ai_moments_defaults(self):
        args = self.parser.parse_args([])
        self.assertFalse(args.ai_moments)
        self.assertEqual(args.ai_moments_count, 10)
        self.assertEqual(args.ai_moments_strategy, "Balanced")
        self.assertEqual(args.ai_moments_dur_min, 2.0)
        self.assertEqual(args.ai_moments_dur_max, 5.0)

    def test_ai_moments_only_flag(self):
        args = self.parser.parse_args(["--ai-moments-only"])
        self.assertTrue(args.ai_moments_only)
        self.assertFalse(args.ai_moments) # Should be false by default parser, logic handles it in main

    def test_advanced_ui_parameters(self):
        args = self.parser.parse_args([
            "--action-bottom-crop", "0.25",
            "--action-auto-bottom-crop",
            "--action-vertical-bias", "-0.5",
            "--no-scroll",
            "--zoom", "1.5",
            "--hue-shift", "180.0",
            "--text-bg",
            "--text-style", "shadow"
        ])
        self.assertEqual(args.action_bottom_crop, 0.25)
        self.assertTrue(args.action_auto_bottom_crop)
        self.assertEqual(args.action_vertical_bias, -0.5)
        self.assertFalse(args.scroll_enabled) # --no-scroll sets scroll_enabled to False
        self.assertEqual(args.zoom, 1.5)
        self.assertEqual(args.hue_shift, 180.0)
        self.assertTrue(args.text_bg)
        self.assertEqual(args.text_style, "shadow")

    def test_auto_detector_fallback(self):
        args = self.parser.parse_args(["--action-auto-detector-fallback"])
        self.assertTrue(args.action_auto_detector_fallback)

    def test_smart_ratio_bypass(self):
        args = self.parser.parse_args(["--no-smart-ratio-bypass"])
        self.assertFalse(args.smart_ratio_bypass)

if __name__ == "__main__":
    unittest.main()
