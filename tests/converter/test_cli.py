import unittest
import argparse
from src.converter.cli import _build_parser

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

if __name__ == "__main__":
    unittest.main()
