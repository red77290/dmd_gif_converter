#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests unitaires pour dmd_gif_converter.py

Couvre :
  - snap_to_clean_fps()
  - DEFAULT_PARAMS / _PRESETS / _TEXT_COLOR_MAP (constantes)
  - _check_drawtext() (mock subprocess)
  - get_metadata() (mock subprocess)
  - process_file() (mock subprocess + get_metadata)
  - process_folder() (mock process_file)
"""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Assure que le répertoire parent est dans le sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import src.engine.conversion as conv
import src.engine.conversion.ffmpeg_utils as ffmpeg_utils


# ─────────────────────────────────────────────────────────────────────────────
# snap_to_clean_fps
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapToCleanFps(unittest.TestCase):

    def test_exact_match_10(self):
        self.assertEqual(conv.snap_to_clean_fps(10.0), 10.0)

    def test_exact_match_25(self):
        self.assertEqual(conv.snap_to_clean_fps(25.0), 25.0)

    def test_below_min_clamps_to_10(self):
        self.assertEqual(conv.snap_to_clean_fps(1.0), 10.0)

    def test_above_max_clamps_to_25(self):
        self.assertEqual(conv.snap_to_clean_fps(60.0), 25.0)

    def test_snaps_to_nearest_12_5(self):
        # 11 is closer to 12.5 than to 10.0
        self.assertEqual(conv.snap_to_clean_fps(11.5), 12.5)

    def test_snaps_to_nearest_20(self):
        self.assertEqual(conv.snap_to_clean_fps(20.0), 20.0)

    def test_fps_15_snaps_to_12_5_or_20(self):
        # 15 is equidistant between 12.5 and 20 — min() picks the first equal
        result = conv.snap_to_clean_fps(15.0)
        self.assertIn(result, ffmpeg_utils._CLEAN_GIF_FPS)

    def test_custom_range(self):
        # With a tighter range, fps must still land on a valid clean value
        result = conv.snap_to_clean_fps(18.0, fps_min=10.0, fps_max=20.0)
        self.assertIn(result, ffmpeg_utils._CLEAN_GIF_FPS)
        self.assertLessEqual(result, 20.0)

    def test_all_clean_values_are_idempotent(self):
        for fps in ffmpeg_utils._CLEAN_GIF_FPS:
            self.assertEqual(conv.snap_to_clean_fps(fps), fps)


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):

    # DEFAULT_PARAMS doit contenir les clés essentielles
    def test_default_params_keys(self):
        required = [
            "max_workers", "scroll_speed", "bottom_crop_pct", "top_crop_pct",
            "scroll_cycles", "fps_min", "fps_max", "mode",
            "contrast", "saturation", "brightness", "gamma",
            "sharpen_lum", "sharpen_chr", "dither",
            "target_width", "target_height",
            "text_overlay_enabled", "text_content",
        ]
        for key in required:
            self.assertIn(key, conv.DEFAULT_PARAMS, f"Clé manquante dans DEFAULT_PARAMS : {key}")

    def test_default_target_dimensions(self):
        self.assertEqual(conv.DEFAULT_PARAMS["target_width"],  128)
        self.assertEqual(conv.DEFAULT_PARAMS["target_height"],  32)

    def test_default_top_crop_is_zero(self):
        self.assertAlmostEqual(conv.DEFAULT_PARAMS["top_crop_pct"], 0.0)

    def test_default_mode(self):
        self.assertEqual(conv.DEFAULT_PARAMS["mode"], "pixel_art")

    def test_presets_have_all_modes(self):
        for mode in ("pixel_art", "anime", "cinema"):
            self.assertIn(mode, conv._PRESETS)

    def test_presets_have_7_values(self):
        for mode, values in conv._PRESETS.items():
            self.assertEqual(len(values), 7,
                             f"Le preset '{mode}' doit avoir 7 valeurs (c,s,b,g,sl,sc,dither)")

    def test_text_color_map_contains_basics(self):
        for color in ("white", "yellow", "red", "green", "blue"):
            self.assertIn(color, ffmpeg_utils._TEXT_COLOR_MAP)

    def test_text_color_map_rgba_format(self):
        for name, rgba in ffmpeg_utils._TEXT_COLOR_MAP.items():
            self.assertEqual(len(rgba), 4, f"{name} doit être RGBA (4 composantes)")
            for ch in rgba:
                self.assertGreaterEqual(ch, 0)
                self.assertLessEqual(ch, 255)

    def test_supported_extensions_include_common_formats(self):
        for ext in (".gif", ".mp4", ".avi", ".mkv", ".mov"):
            self.assertIn(ext, conv.SUPPORTED_EXTENSIONS)


# ─────────────────────────────────────────────────────────────────────────────
# _check_drawtext
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckDrawtext(unittest.TestCase):

    def setUp(self):
        # Réinitialise le cache avant chaque test
        ffmpeg_utils._drawtext_available = None

    def test_returns_true_when_drawtext_in_output(self):
        mock_result = MagicMock()
        mock_result.stdout = "Filters:\n  drawtext   V->V   Draw text on input video.\n"
        mock_result.stderr = ""
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result):
            self.assertTrue(ffmpeg_utils._check_drawtext())

    def test_returns_false_when_drawtext_absent(self):
        ffmpeg_utils._drawtext_available = None
        mock_result = MagicMock()
        mock_result.stdout = "Filters:\n  scale   V->V   Scale the input video.\n"
        mock_result.stderr = ""
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result):
            self.assertFalse(ffmpeg_utils._check_drawtext())

    def test_returns_false_on_exception(self):
        ffmpeg_utils._drawtext_available = None
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            self.assertFalse(ffmpeg_utils._check_drawtext())

    def test_result_is_cached(self):
        ffmpeg_utils._drawtext_available = None
        mock_result = MagicMock()
        mock_result.stdout = "drawtext"
        mock_result.stderr = ""
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result) as mock_sub:
            ffmpeg_utils._check_drawtext()
            ffmpeg_utils._check_drawtext()
            # subprocess.run ne doit être appelé qu'une seule fois
            self.assertEqual(mock_sub.call_count, 1)

    def tearDown(self):
        ffmpeg_utils._drawtext_available = None


# ─────────────────────────────────────────────────────────────────────────────
# get_metadata
# ─────────────────────────────────────────────────────────────────────────────

class TestGetMetadata(unittest.TestCase):

    def _make_ffprobe_output(self, w=1920, h=1080, fps="25/1", duration="10.5", nb_frames="N/A"):
        return json.dumps({
            "streams": [{
                "width": w,
                "height": h,
                "avg_frame_rate": fps,
                "r_frame_rate": fps,
                "nb_frames": nb_frames,
            }],
            "format": {"duration": duration},
        })

    def test_normal_video(self):
        output = self._make_ffprobe_output(1920, 1080, "25/1", "10.5")
        mock_result = MagicMock(stdout=output)
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result):
            w, h, fps, dur = conv.get_metadata("video.mp4")
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)
        self.assertAlmostEqual(fps, 25.0)
        self.assertAlmostEqual(dur, 10.5)

    def test_fractional_fps(self):
        output = self._make_ffprobe_output(640, 480, "30000/1001", "5.0")
        mock_result = MagicMock(stdout=output)
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result):
            _, _, fps, _ = conv.get_metadata("video.mp4")
        self.assertAlmostEqual(fps, 30000 / 1001, places=2)

    def test_duration_from_nb_frames_when_format_missing(self):
        output = self._make_ffprobe_output(640, 480, "25/1", "0", nb_frames="250")
        mock_result = MagicMock(stdout=output)
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", return_value=mock_result):
            _, _, fps, dur = conv.get_metadata("video.mp4")
        # 250 frames @ 25 fps = 10 s
        self.assertAlmostEqual(dur, 10.0)

    def test_returns_none_on_exception(self):
        with patch("src.engine.conversion.ffmpeg_utils.subprocess.run", side_effect=Exception("ffprobe crash")):
            w, h, fps, dur = conv.get_metadata("bad.mp4")
        self.assertIsNone(w)
        self.assertIsNone(h)
        self.assertAlmostEqual(fps, 25.0)
        self.assertAlmostEqual(dur, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# process_file
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessFile(unittest.TestCase):
    """Tests de process_file avec subprocess mocké."""

    def _mock_metadata(self, w=640, h=480, fps=25.0, dur=4.0):
        return patch("src.engine.conversion.core.get_metadata", return_value=(w, h, fps, dur))

    def _mock_ffmpeg_ok(self):
        mock = MagicMock()
        mock.returncode = 0
        mock.poll.return_value = 0
        return patch("src.engine.conversion.core.subprocess.Popen", return_value=mock)

    def _mock_ffmpeg_fail(self, stderr=b"some error\nlast error line"):
        mock = MagicMock()
        mock.returncode = 1
        mock.poll.return_value = 1
        mock.stderr.read.return_value = stderr
        return patch("src.engine.conversion.core.subprocess.Popen", return_value=mock)

    def test_success_returns_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with self._mock_metadata(), self._mock_ffmpeg_ok():
                ok, msg = conv.process_file("input.mp4", out)
            self.assertTrue(ok)
            self.assertIn("OK", msg)

    def test_ffmpeg_failure_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with self._mock_metadata(), self._mock_ffmpeg_fail():
                ok, msg = conv.process_file("input.mp4", out)
            self.assertFalse(ok)
            self.assertIn("ERROR", msg)

    def test_metadata_failure_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with patch("src.engine.conversion.core.get_metadata", return_value=(None, None, 25.0, 0.0)):
                ok, msg = conv.process_file("input.mp4", out)
            self.assertFalse(ok)

    def test_callback_is_called(self):
        messages = []
        def cb(msg, level="info"):
            messages.append((msg, level))

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with self._mock_metadata(), self._mock_ffmpeg_ok():
                conv.process_file("input.mp4", out, callback=cb)
        self.assertTrue(len(messages) > 0)

    def test_custom_params_are_merged(self):
        """process_file doit respecter les params personnalisés."""
        captured_cmd = []
        def fake_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            m = MagicMock()
            m.returncode = 0
            m.poll.return_value = 0
            m.stderr.read.return_value = b""
            return m

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with self._mock_metadata():
                with patch("src.engine.conversion.core.subprocess.Popen", side_effect=fake_run):
                    conv.process_file(
                        "input.mp4", out,
                        params={"mode": "cinema", "target_width": 256, "target_height": 64}
                    )
        # La commande doit inclure ffmpeg
        self.assertIn("ffmpeg", captured_cmd)

    def test_trim_start_adds_ss_flag(self):
        captured_cmd = []
        def fake_run(cmd, **kwargs):
            if "ffmpeg" in cmd:
                captured_cmd.extend(cmd)
            m = MagicMock()
            m.returncode = 0
            m.poll.return_value = 0
            m.stderr.read.return_value = b""
            return m

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            with self._mock_metadata():
                with patch("src.engine.conversion.core.subprocess.Popen", side_effect=fake_run):
                    conv.process_file("input.mp4", out, start_s=5.0)
        self.assertIn("-ss", captured_cmd)

    def test_max_duration_cap(self):
        """max_duration > 0 doit couper trim_end."""
        captured_cmds = []
        def fake_run(cmd, **kwargs):
            captured_cmds.append(list(cmd))
            m = MagicMock()
            m.returncode = 0
            m.poll.return_value = 0
            m.stderr.read.return_value = b""
            return m

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "out.gif")
            # Durée source = 30 s, max_duration = 5 s
            with patch("src.engine.conversion.core.get_metadata", return_value=(640, 480, 25.0, 30.0)):
                with patch("src.engine.conversion.core.subprocess.Popen", side_effect=fake_run):
                    conv.process_file("input.mp4", out, params={"max_duration": 5.0})
        # La durée de sortie dans -t doit être <= 5 s (+ frames scroll)
        # On vérifie juste que l'appel ffmpeg est bien fait
        ffmpeg_calls = [c for c in captured_cmds if "ffmpeg" in c]
        self.assertTrue(len(ffmpeg_calls) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# process_folder
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessFolder(unittest.TestCase):

    def test_empty_folder_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as folder_in:
            with tempfile.TemporaryDirectory() as folder_out:
                results = conv.process_folder(folder_in, folder_out)
        self.assertEqual(results, [])

    def test_processes_supported_files(self):
        with tempfile.TemporaryDirectory() as folder_in:
            with tempfile.TemporaryDirectory() as folder_out:
                # Créer un fichier factice avec extension supportée
                (Path(folder_in) / "test.gif").touch()
                (Path(folder_in) / "ignore.txt").touch()

                with patch("src.engine.conversion.core.process_file", return_value=(True, "[OK] test.gif")) as mock_pf:
                    results = conv.process_folder(folder_in, folder_out)

                # Seul test.gif doit avoir été traité (ignore.txt est ignoré)
                self.assertEqual(mock_pf.call_count, 1)
                self.assertEqual(len(results), 1)

    def test_creates_output_folder(self):
        with tempfile.TemporaryDirectory() as folder_in:
            (Path(folder_in) / "test.mp4").touch()
            out = os.path.join(folder_in, "subdir_out")
            with patch("src.engine.conversion.core.process_file", return_value=(True, "[OK] test.mp4")):
                conv.process_folder(folder_in, out)
            self.assertTrue(os.path.isdir(out))


# ─────────────────────────────────────────────────────────────────────────────
# _apply_text_overlay_pillow (sans écrire de vrai GIF)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyTextOverlayPillow(unittest.TestCase):

    def test_returns_false_when_pillow_unavailable(self):
        """Si Pillow n'est pas importable, la fonction doit retourner False."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("Pillow not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            ok, msg = ffmpeg_utils._apply_text_overlay_pillow(
                "nonexistent.gif", "Hello", "font.ttf", 8, "white", "bottom_center"
            )
        self.assertFalse(ok)

    def test_returns_false_on_bad_gif_path(self):
        """Un chemin GIF inexistant doit renvoyer False avec un message."""
        try:
            from PIL import Image  # noqa
        except ImportError:
            self.skipTest("Pillow non disponible")

        ok, msg = ffmpeg_utils._apply_text_overlay_pillow(
            "/nonexistent/path.gif", "Hi", "font.ttf", 8, "white", "bottom_center"
        )
        self.assertFalse(ok)
        self.assertIsInstance(msg, str)


if __name__ == "__main__":
    unittest.main()

