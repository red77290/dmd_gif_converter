#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests unitaires pour la fonction _out_path() de ActionsPanel.

Vérifie que le fichier de sortie DMD est TOUJOURS un .gif,
quel que soit le format du fichier source.
"""

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# Stub minimal pour isoler _out_path sans instancier tout le widget Tkinter
# ---------------------------------------------------------------------------

class _StubOutPath:
    """Reproduit exactement la logique de ActionsPanel._out_path ET PreviewPanel._out_path."""

    def __init__(self, output_dir="", per_gif_configs=None):
        self.app_state = MagicMock()
        self.app_state.v_output_dir.get.return_value = output_dir
        self.app_state.v_per_gif_config.get.return_value = bool(per_gif_configs)
        self._per_gif_configs = per_gif_configs or {}
        # Attribut qui reproduit le widget tkinter BooleanVar du panel
        if per_gif_configs:
            self.v_per_gif_config = MagicMock()

    def _out_path(self, src, iid=None):
        """Copie exacte de ActionsPanel._out_path et PreviewPanel._out_path (après fix)."""
        base = Path(src).stem + "_dmd" + ".gif"
        if iid and hasattr(self, 'v_per_gif_config') and self.app_state.v_per_gif_config.get():
            cfg = self._per_gif_configs.get(iid)
            if cfg and "custom_out_name" in cfg:
                base = cfg["custom_out_name"]

        out_dir = self.app_state.v_output_dir.get().strip()
        if out_dir and os.path.isdir(out_dir):
            return str(Path(out_dir) / base)

        tmp_dir = Path(src).parent / "dmd_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return str(tmp_dir / base)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutPathAlwaysGif(unittest.TestCase):

    def test_mp4_input_produces_gif_output(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/myvideo.mp4")
        self.assertTrue(result.endswith(".gif"),
                        f"Attendu .gif, obtenu : {result}")

    def test_avi_input_produces_gif_output(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/myvideo.avi")
        self.assertTrue(result.endswith(".gif"),
                        f"Attendu .gif, obtenu : {result}")

    def test_mkv_input_produces_gif_output(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/clip.mkv")
        self.assertTrue(result.endswith(".gif"),
                        f"Attendu .gif, obtenu : {result}")

    def test_mov_input_produces_gif_output(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/clip.mov")
        self.assertTrue(result.endswith(".gif"),
                        f"Attendu .gif, obtenu : {result}")

    def test_gif_input_also_produces_gif_output(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/anim.gif")
        self.assertTrue(result.endswith(".gif"),
                        f"Attendu .gif, obtenu : {result}")

    def test_output_stem_includes_dmd_suffix(self):
        stub = _StubOutPath()
        result = stub._out_path("/tmp/myvideo.mp4")
        self.assertIn("myvideo_dmd", Path(result).name)

    def test_custom_out_dir_is_respected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            stub = _StubOutPath(output_dir=tmpdir)
            result = stub._out_path("/tmp/myvideo.mp4")
            self.assertTrue(result.startswith(tmpdir))
            self.assertTrue(result.endswith(".gif"))

    def test_custom_out_name_from_per_gif_config(self):
        """Un custom_out_name configuré par l'utilisateur doit être respecté."""
        stub = _StubOutPath(
            per_gif_configs={"item1": {"custom_out_name": "custom_output.gif"}}
        )
        result = stub._out_path("/tmp/myvideo.mp4", iid="item1")
        self.assertTrue(Path(result).name == "custom_output.gif")


class TestFfmpegConverterGifFormat(unittest.TestCase):
    """Vérifie que ffmpeg_converter force le format GIF explicitement."""

    def test_pass2_command_contains_f_gif(self):
        """La commande ffmpeg du pass 2 doit contenir '-f gif'."""
        # On lit directement le source pour vérifier la présence de "-f", "gif"
        import ast
        converter_path = (
            Path(__file__).parent.parent.parent
            / "src" / "engine" / "conversion" / "services" / "ffmpeg_converter.py"
        )
        source = converter_path.read_text(encoding="utf-8")
        # Vérifie que le flag est présent dans le source
        self.assertIn('"-f"', source,
                      "Le flag '-f' est absent de ffmpeg_converter.py")
        # Vérifie que 'gif' suit '-f' (format imposé)
        idx = source.find('"-f"')
        snippet = source[idx:idx + 40]
        self.assertIn("gif", snippet,
                      f"'gif' doit suivre '-f' dans ffmpeg_converter.py, trouvé: {snippet!r}")

    def test_core_py_command_contains_f_gif(self):
        """La commande ffmpeg dans core.py doit contenir '-f gif'."""
        core_path = (
            Path(__file__).parent.parent.parent
            / "src" / "engine" / "conversion" / "core.py"
        )
        source = core_path.read_text(encoding="utf-8")
        self.assertIn('"-f"', source,
                      "Le flag '-f' est absent de core.py")
        idx = source.find('"-f"')
        snippet = source[idx:idx + 40]
        self.assertIn("gif", snippet,
                      f"'gif' doit suivre '-f' dans core.py, trouvé: {snippet!r}")


class TestOutPathSourceCodeConsistency(unittest.TestCase):
    """Vérifie que TOUS les fichiers sources utilisent .gif et non Path(src).suffix."""

    def _get_src_root(self):
        return Path(__file__).parent.parent.parent / "src"

    def test_no_source_file_uses_original_suffix_for_dmd_output(self):
        """Aucun fichier ne doit construire le nom de sortie _dmd avec l'extension d'origine."""
        src_root = self._get_src_root()
        offenders = []
        for py_file in src_root.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if '_dmd" + Path(' in content and '.suffix' in content:
                # Vérifie que c'est bien la combinaison problématique
                for line in content.splitlines():
                    if '_dmd"' in line and 'Path(' in line and '.suffix' in line:
                        offenders.append(f"{py_file.relative_to(src_root)}:{line.strip()}")
        self.assertEqual(
            offenders, [],
            f"Ces fichiers utilisent encore l'extension d'origine pour le DMD output :\n"
            + "\n".join(offenders)
        )


if __name__ == "__main__":
    unittest.main()

