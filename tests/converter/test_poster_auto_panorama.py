from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

import dmd_gif_converter
from src.engine.api import STATIC_IMAGE_EXTENSIONS, is_static_image_source
from src.engine.conversion.core import process_file, process_folder
from src.engine.conversion.quality import evaluate_gif_quality
from src.engine.conversion.services.batch_orchestrator import BatchOrchestrator


def _make_banded_poster(width: int = 200, height: int = 360, rgba: bool = False) -> Image.Image:
    """Create a synthetic poster with distinct top/middle/bottom color bands and detail."""
    channels = 4 if rgba else 3
    arr = np.zeros((height, width, channels), dtype=np.uint8)
    h3 = height // 3
    # Top band: bright red + yellow grid
    arr[:h3, :, 0] = 230
    arr[:h3, :, 1] = 40
    arr[:h3, ::8, 1] = 220
    # Middle band: bright green + white stripes
    arr[h3 : 2 * h3, :, 1] = 215
    arr[h3 : 2 * h3, ::10, :] = 245 if not rgba else [245, 245, 245, 255]
    # Bottom band: vivid cyan/blue + magenta accents
    arr[2 * h3 :, :, 1] = 170
    arr[2 * h3 :, :, 2] = 245
    arr[2 * h3 :, 4::12, 0] = 235
    if rgba:
        arr[:, :, 3] = 255
        # Transparent border strip on left/right to verify #000000 compositing
        arr[:, :16, :] = [255, 255, 255, 0]
        arr[:, -16:, :] = [255, 255, 255, 0]
    return Image.fromarray(arr, mode="RGBA" if rgba else "RGB")


def _make_wide_marquee(width: int = 420, height: int = 130) -> Image.Image:
    """Create a horizontal marquee with distinct left/center/right color zones."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    w3 = width // 3
    arr[:, :w3, 0] = 235
    arr[::6, :w3, 1] = 200
    arr[:, w3 : 2 * w3, 1] = 225
    arr[::6, w3 : 2 * w3, 2] = 210
    arr[:, 2 * w3 :, 2] = 240
    arr[::6, 2 * w3 :, 0] = 220
    return Image.fromarray(arr, mode="RGB")


def test_is_static_image_source_distinguishes_static_vs_animated_and_video(tmp_path: Path):
    assert dmd_gif_converter.is_static_image_source is is_static_image_source
    assert ".png" in STATIC_IMAGE_EXTENSIONS
    assert ".webp" in STATIC_IMAGE_EXTENSIONS

    poster = _make_banded_poster(120, 180)
    for ext, fmt in [
        (".png", "PNG"),
        (".jpg", "JPEG"),
        (".webp", "WEBP"),
        (".bmp", "BMP"),
        (".tiff", "TIFF"),
    ]:
        p = tmp_path / f"sample{ext}"
        poster.save(p, format=fmt)
        assert is_static_image_source(p) is True

    # 1-frame static GIF -> True
    static_gif = tmp_path / "static_one_frame.gif"
    poster.save(static_gif, format="GIF")
    assert is_static_image_source(static_gif) is True

    # Multi-frame animated GIF -> False
    anim_gif = tmp_path / "animated.gif"
    frame2 = _make_wide_marquee(120, 180)
    poster.save(anim_gif, format="GIF", save_all=True, append_images=[frame2], duration=80, loop=0)
    assert is_static_image_source(anim_gif) is False

    # Video MP4 -> False
    mp4_path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(mp4_path), cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (128, 64))
    for i in range(10):
        frm = np.full((64, 128, 3), i * 20, dtype=np.uint8)
        writer.write(frm)
    writer.release()
    assert is_static_image_source(mp4_path) is False
    assert is_static_image_source("") is False
    assert is_static_image_source(None) is False


def test_let_me_handle_it_routes_portrait_poster_to_yoko_vertical_scroll(tmp_path: Path):
    poster_jpg = tmp_path / "flyer.jpg"
    _make_banded_poster(200, 360).save(poster_jpg, format="JPEG", quality=95)
    out_gif = tmp_path / "flyer_128x32.gif"

    # Exact parameters emitted by the UI when "Let Me Handle It" is checked
    ui_params = {
        "let_me_handle_it": True,
        "auto_action_enabled": True,
        "scroll_enabled": True,
        "bottom_crop_pct": 0.15,
        "target_width": 128,
        "target_height": 32,
    }

    with patch("src.engine.conversion.core.preprocess_video_for_dmd") as mock_yolo:
        ok, msg = process_file(str(poster_jpg), str(out_gif), params=ui_params)
        assert ok is True, msg
        mock_yolo.assert_not_called()

    assert out_gif.is_file()
    with Image.open(out_gif) as gif:
        assert gif.size == (128, 32)
        assert gif.n_frames >= 20
        gif.seek(0)
        first_frame = np.asarray(gif.convert("RGB"), dtype=np.float32)
        gif.seek(gif.n_frames // 2)
        mid_frame = np.asarray(gif.convert("RGB"), dtype=np.float32)

    # Confirm actual vertical camera travel across the poster (not a frozen frame)
    mean_diff = float(np.mean(np.abs(first_frame - mid_frame)))
    assert mean_diff > 25.0

    # Quality evaluator must score animated poster high (never 1-frame Auto-Trash penalty)
    q_res = evaluate_gif_quality(str(out_gif))
    assert q_res["score"] >= 50.0, q_res


def test_let_me_handle_it_routes_poster_to_tate_horizontal_scroll_with_zero_crop(tmp_path: Path):
    marquee_png = tmp_path / "marquee.png"
    _make_wide_marquee(420, 140).save(marquee_png, format="PNG")
    out_gif = tmp_path / "marquee_64x128.gif"

    ui_tate_params = {
        "let_me_handle_it": True,
        "auto_action_enabled": True,
        "bottom_crop_pct": 0.15,
        "target_width": 64,
        "target_height": 128,
    }
    ok, msg = process_file(str(marquee_png), str(out_gif), params=ui_tate_params)
    assert ok is True, msg

    with Image.open(out_gif) as gif:
        assert gif.size == (64, 128)
        assert gif.n_frames >= 20
        gif.seek(0)
        f0 = np.asarray(gif.convert("RGB"), dtype=np.float32)
        gif.seek(gif.n_frames // 3)
        f1 = np.asarray(gif.convert("RGB"), dtype=np.float32)
    assert float(np.mean(np.abs(f0 - f1))) > 20.0


def test_static_formats_rgba_webp_bmp_and_one_frame_gif_all_scroll_cleanly(tmp_path: Path):
    rgba_png = tmp_path / "transparent_logo.png"
    _make_banded_poster(160, 260, rgba=True).save(rgba_png, format="PNG")

    webp_img = tmp_path / "poster.webp"
    _make_banded_poster(180, 300).save(webp_img, format="WEBP")

    bmp_img = tmp_path / "poster.bmp"
    _make_banded_poster(180, 300).save(bmp_img, format="BMP")

    one_frame_gif = tmp_path / "single.gif"
    _make_banded_poster(180, 300).save(one_frame_gif, format="GIF")

    for src in (rgba_png, webp_img, bmp_img, one_frame_gif):
        out = tmp_path / f"out_{src.stem}.gif"
        ok, msg = process_file(
            str(src),
            str(out),
            params={
                "let_me_handle_it": True,
                "target_width": 128,
                "target_height": 32,
                "max_duration": 3.5,
            },
        )
        assert ok is True, f"{src.name} failed: {msg}"
        with Image.open(out) as gif:
            assert gif.size == (128, 32)
            assert gif.n_frames >= 15
            if src == rgba_png:
                gif.seek(0)
                arr0 = np.asarray(gif.convert("RGB"))
                # Left/right transparent border strips must be composited onto #000000 black
                assert float(np.mean(arr0[:, :4, :])) < 8.0


def test_manual_non_scrolling_mode_on_static_image_is_preserved(tmp_path: Path):
    poster = tmp_path / "manual_poster.png"
    _make_banded_poster(160, 240).save(poster, format="PNG")
    out_gif = tmp_path / "manual_out.gif"

    ok, msg = process_file(
        str(poster),
        str(out_gif),
        params={
            "let_me_handle_it": False,
            "auto_action_enabled": False,
            "scroll_enabled": False,
            "zoom": 1.0,
            "manual_x": 0,
            "manual_y": 10,
            "target_width": 128,
            "target_height": 32,
        },
    )
    assert ok is True, msg
    with Image.open(out_gif) as gif:
        assert gif.size == (128, 32)
        gif.seek(0)
        f0 = np.asarray(gif.convert("RGB"), dtype=np.float32)
        gif.seek(max(0, gif.n_frames - 1))
        flast = np.asarray(gif.convert("RGB"), dtype=np.float32)
    assert float(np.mean(np.abs(f0 - flast))) < 2.0


def test_process_folder_and_batch_orchestrator_handle_static_posters_without_yolo(tmp_path: Path):
    in_dir = tmp_path / "in_posters"
    out_dir = tmp_path / "out_posters"
    in_dir.mkdir()
    _make_banded_poster(180, 320).save(in_dir / "p1.jpg", format="JPEG")
    _make_wide_marquee(320, 120).save(in_dir / "p2.png", format="PNG")

    assert ".jpg" in BatchOrchestrator.SUPPORTED_EXTENSIONS
    assert ".png" in BatchOrchestrator.SUPPORTED_EXTENSIONS

    with patch("src.engine.conversion.core.preprocess_video_for_dmd") as mock_yolo:
        results = process_folder(
            str(in_dir),
            str(out_dir),
            params={
                "let_me_handle_it": False,
                "auto_action_enabled": True,
                "bottom_crop_pct": 0.15,
                "target_width": 128,
                "target_height": 32,
                "max_duration": 3.0,
            },
        )
        assert len(results) == 2
        assert all(ok for ok, _ in results), results
        mock_yolo.assert_not_called()

    for name in ("p1.gif", "p2.gif"):
        out_file = out_dir / name
        assert out_file.is_file()
        with Image.open(out_file) as gif:
            assert gif.size == (128, 32)
            assert gif.n_frames >= 15
