from unittest.mock import MagicMock, patch

import customtkinter as ctk

from src.ui.preview.preview_player import PreviewPlayer

def _make_player():
    with patch.object(ctk.CTkScrollableFrame, "__init__", return_value=None), \
         patch.object(PreviewPlayer, "_build_preview_area", return_value=None), \
         patch.object(PreviewPlayer, "grid_columnconfigure", return_value=None), \
         patch.object(PreviewPlayer, "grid_rowconfigure", return_value=None), \
         patch.object(PreviewPlayer, "bind", return_value=None):
        player = PreviewPlayer(MagicMock(), MagicMock())
        player._canvas = MagicMock()
        return player

def test_preview_player_instantiation():
    player = _make_player()
    assert player is not None


def test_preview_player_static_poster_routes_auto_preview_to_dmd_generation(tmp_path):
    from PIL import Image

    poster_path = tmp_path / "poster.png"
    Image.new("RGBA", (180, 320), (200, 60, 40, 255)).save(poster_path, format="PNG")

    player = _make_player()
    player.panel = MagicMock()
    player._auto_canvas = MagicMock()
    player._auto_canvas.winfo_width.return_value = 320
    player._auto_info = MagicMock()
    player._auto_tmpdir = None
    player._auto_pending_src = None
    player._current_path = str(poster_path)
    player._start_dmd_generation = MagicMock()

    player._on_auto_static_poster(180, 320, 128, 32)

    assert player._auto_rendering is False
    player._start_dmd_generation.assert_called_once_with(str(poster_path))
    info_text = player._auto_info.configure.call_args.kwargs["text"]
    assert "vertical" in info_text
    assert "128×32" in info_text


def test_preview_player_animate_src_single_frame_does_not_schedule_blink_loop():
    from PIL import Image

    player = _make_player()
    player._src_pil_frames = [Image.new("RGB", (160, 240), (120, 180, 220))]
    player._src_frames = [None]
    player._src_delays = [1000]
    player._src_idx = 0
    player._src_canvas = MagicMock()
    player.after = MagicMock()

    with patch("src.ui.preview.preview_player.ImageTk.PhotoImage", return_value=MagicMock()):
        player._animate_src()

    player._src_canvas.create_image.assert_called_once()
    player.after.assert_not_called()

