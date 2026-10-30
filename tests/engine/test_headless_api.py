"""
Unit and integration tests for the headless library API (`dmd_gif_converter` / `src.engine.api`).
"""

import ast
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

import dmd_gif_converter
from dmd_gif_converter import (
    DMDS_HEADER_SIZE,
    DMDS_MAGIC,
    DMDS_VERSION,
    DmdClipConfig,
    DmdMediaProcessor,
    DmdProcessedAssets,
    __version__,
    extract_frames_from_gif,
    read_rgb565_stream_header,
    rgb565_le_to_rgb888,
    rgb888_to_rgb565_le,
    truncate_gif_bytes,
    truncate_rgb565_stream,
    write_rgb565_stream,
)


def test_version_and_top_level_exports():
    assert isinstance(__version__, str) and len(__version__) > 0
    assert dmd_gif_converter.__version__ == __version__
    assert DmdMediaProcessor is not None
    assert DmdClipConfig is not None
    assert DmdProcessedAssets is not None


def test_engine_and_plugins_have_zero_gui_imports():
    """
    Guarantee that `src/engine/` and `src/plugins/` can be imported in a headless
    Docker container without `tkinter` or `customtkinter` installed.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    forbidden = {"tkinter", "customtkinter", "darkdetect", "send2trash"}

    for subdir in ("src/engine", "src/plugins"):
        folder = repo_root / subdir
        for py_file in folder.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".")[0]
                        assert root_mod not in forbidden, (
                            f"Forbidden GUI import '{alias.name}' found in headless module {py_file}"
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".")[0]
                    assert root_mod not in forbidden, (
                        f"Forbidden GUI import 'from {node.module}' found in headless module {py_file}"
                    )
                    assert not node.module.startswith("src.ui"), (
                        f"Forbidden UI dependency 'from {node.module}' found in headless module {py_file}"
                    )


def test_rgb565_conversion_and_roundtrip():
    width, height = 32, 32
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = 248  # Pure 5-bit red max
    rgb[:, :, 1] = 124  # 6-bit green mid
    rgb[:, :, 2] = 64   # 5-bit blue

    raw = rgb888_to_rgb565_le(rgb)
    assert len(raw) == width * height * 2 == 2048

    restored = rgb565_le_to_rgb888(raw, width, height)
    assert restored.shape == (height, width, 3)
    np.testing.assert_array_equal(restored[:, :, 0], 248)
    np.testing.assert_array_equal(restored[:, :, 1], 124)
    np.testing.assert_array_equal(restored[:, :, 2], 64)


def test_rgb565_stream_write_read_and_truncate(tmp_path: Path):
    width, height, fps = 128, 32, 15
    total_frames = 45  # 3.0 seconds at 15 FPS
    frames = [
        np.full((height, width, 3), fill_value=(i * 5) % 255, dtype=np.uint8)
        for i in range(total_frames)
    ]

    stream_file = tmp_path / "test_clip.rgb565.stream"
    written = write_rgb565_stream(frames, stream_file, fps=fps)
    assert written == total_frames
    assert stream_file.exists()

    frame_bytes = width * height * 2  # 8192 bytes
    assert stream_file.stat().st_size == DMDS_HEADER_SIZE + total_frames * frame_bytes

    meta = read_rgb565_stream_header(stream_file)
    assert meta["magic"] == "DMDS"
    assert meta["version"] == DMDS_VERSION
    assert meta["fps"] == fps
    assert meta["width"] == width
    assert meta["height"] == height
    assert meta["total_frames"] == total_frames
    assert meta["frame_byte_size"] == frame_bytes
    assert meta["duration_s"] == 3.0

    # Truncate from 3.0s (45 frames) down to 1.0s (15 frames)
    truncated_bytes = truncate_rgb565_stream(stream_file, max_duration_s=1.0)
    assert len(truncated_bytes) == DMDS_HEADER_SIZE + 15 * frame_bytes
    trunc_meta = read_rgb565_stream_header(truncated_bytes)
    assert trunc_meta["total_frames"] == 15
    assert trunc_meta["duration_s"] == 1.0


def test_truncate_gif_bytes(tmp_path: Path):
    gif_path = tmp_path / "anim.gif"
    imgs = [
        Image.fromarray(np.full((32, 128, 3), fill_value=i * 20, dtype=np.uint8))
        for i in range(10)
    ]
    # 10 frames * 100ms = 1.0s total
    imgs[0].save(
        gif_path,
        format="GIF",
        save_all=True,
        append_images=imgs[1:],
        duration=100,
        loop=0,
    )

    # Truncate to 0.4s -> should keep 4 frames
    short_bytes = truncate_gif_bytes(gif_path, max_duration_s=0.4)
    short_path = tmp_path / "short.gif"
    short_path.write_bytes(short_bytes)

    frames, _fps = extract_frames_from_gif(short_path)
    assert len(frames) == 4


def test_process_poster_and_pan_backdrop(tmp_path: Path):
    src_img_path = tmp_path / "source_artwork.png"
    src_arr = np.zeros((240, 320, 3), dtype=np.uint8)
    src_arr[:, :, 0] = 180
    src_arr[60:180, 80:240, 1] = 220
    Image.fromarray(src_arr).save(src_img_path)

    processor = DmdMediaProcessor()

    poster_png, poster_rgb565 = processor.process_poster(
        src_img_path, tmp_path, width=32, height=32, stem="boxart"
    )
    assert poster_png.exists()
    assert poster_rgb565.exists()
    assert poster_rgb565.stat().st_size == 32 * 32 * 2

    snap_png, snap_rgb565 = processor.process_pan_backdrop(
        src_img_path, tmp_path, width=128, height=72, stem="backdrop"
    )
    assert snap_png.exists()
    assert snap_rgb565.exists()
    assert snap_rgb565.stat().st_size == 128 * 72 * 2

    # Test smooth top-to-bottom panorama on both 128x32 landscape and 64x128 TATE vertical
    pan_res = processor.process_image_panorama(
        src_img_path, tmp_path, width=128, height=32, duration_s=2.5, fps=16, stem="jacket_pan"
    )
    assert pan_res.gif_path is not None and pan_res.gif_path.exists()
    assert pan_res.rgb565_stream_path is not None and pan_res.rgb565_stream_path.exists()
    assert pan_res.width == 128
    assert pan_res.height == 32
    assert pan_res.frame_count >= 30

    pan_tate = processor.process_image_panorama(
        src_img_path, tmp_path, width=64, height=128, duration_s=2.5, fps=16, stem="tate_pan"
    )
    assert pan_tate.rgb565_stream_path is not None and pan_tate.rgb565_stream_path.exists()
    assert pan_tate.width == 64
    assert pan_tate.height == 128


def test_tate_panorama_left_to_right_scroll_and_zero_aspect_distortion(tmp_path: Path):
    from dmd_gif_converter import resolve_panorama_scroll_axis

    # 1. Verify orientation-driven axis matrix:
    #    - TATE (H > W) ALWAYS scrolls left-to-right ("horizontal")
    #    - YOKO (W > H) ALWAYS scrolls top-to-bottom ("vertical")
    #    - Square (W == H) scrolls "horizontal" when src_w > src_h else "vertical"
    assert resolve_panorama_scroll_axis(400, 600, 64, 128) == "horizontal"
    assert resolve_panorama_scroll_axis(400, 600, 32, 128) == "horizontal"
    assert resolve_panorama_scroll_axis(1280, 720, 64, 128) == "horizontal"
    assert resolve_panorama_scroll_axis(320, 224, 64, 128) == "horizontal"
    assert resolve_panorama_scroll_axis(320, 224, 32, 128) == "horizontal"
    assert resolve_panorama_scroll_axis(800, 240, 64, 128) == "horizontal"

    assert resolve_panorama_scroll_axis(400, 600, 128, 32) == "vertical"
    assert resolve_panorama_scroll_axis(1280, 720, 128, 32) == "vertical"
    assert resolve_panorama_scroll_axis(1280, 720, 128, 64) == "vertical"
    assert resolve_panorama_scroll_axis(800, 240, 128, 64) == "vertical"
    assert resolve_panorama_scroll_axis(800, 240, 128, 32) == "vertical"
    assert resolve_panorama_scroll_axis(800, 200, 256, 64) == "vertical"

    assert resolve_panorama_scroll_axis(1280, 720, 64, 64) == "horizontal"
    assert resolve_panorama_scroll_axis(400, 600, 64, 64) == "vertical"

    processor = DmdMediaProcessor()

    # 2. Wide screenshot / marquee (360x180, 2:1) on TATE 64x128 -> MUST pan Left -> Right
    #    Left third = RED, Center third = GREEN (with a 60x60 white square to check 1:1 ratio), Right third = BLUE
    wide_arr = np.zeros((180, 360, 3), dtype=np.uint8)
    wide_arr[:, :120, 0] = 240       # Left = Red
    wide_arr[:, 120:240, 1] = 240    # Middle = Green
    wide_arr[:, 240:, 2] = 240       # Right = Blue
    wide_arr[60:120, 150:210, :] = 255  # 60x60 exact 1:1 square in center
    wide_path = tmp_path / "wide_scene.png"
    Image.fromarray(wide_arr).save(wide_path)

    res_tate = processor.process_image_panorama(
        wide_path,
        tmp_path,
        width=64,
        height=128,
        duration_s=2.5,
        fps=16,
        smart_color_boost=False,
        stem="tate_ltr",
    )
    assert res_tate.gif_path is not None and res_tate.gif_path.exists()
    frames_tate, _ = extract_frames_from_gif(res_tate.gif_path)
    assert len(frames_tate) >= 20
    assert frames_tate[0].shape == (128, 64, 3)

    # Zero black bars on top or bottom
    assert frames_tate[0][:4, :, :].max(axis=2).mean() > 120
    assert frames_tate[0][-4:, :, :].max(axis=2).mean() > 120

    first_mean = frames_tate[0].mean(axis=(0, 1))
    mid_frame = frames_tate[len(frames_tate) // 2]
    last_mean = frames_tate[-1].mean(axis=(0, 1))

    # Starts on Left (Red dominant) and finishes on Right (Blue dominant)
    assert first_mean[0] > first_mean[2] + 80, f"Expected Red start on left, got {first_mean}"
    assert last_mean[2] > last_mean[0] + 80, f"Expected Blue end on right, got {last_mean}"

    # Verify zero aspect-ratio distortion: 60px square in 180px height scaled uniformly to 128px height
    # must have height ~= 60 * (128 / 180) = 42.7px (NOT stretched to 128px or squashed!)
    white_mask = (
        (mid_frame[:, :, 0] > 210)
        & (mid_frame[:, :, 1] > 210)
        & (mid_frame[:, :, 2] > 210)
    )
    ys, xs = np.where(white_mask)
    assert len(ys) > 0, "Centered white square should be visible at mid-pan"
    box_h = int(ys.max() - ys.min() + 1)
    box_w = int(xs.max() - xs.min() + 1)
    assert 36 <= box_h <= 48, f"Expected ~43px undistorted square height, got {box_h}"
    assert abs(box_w - box_h) <= 6, f"Expected 1:1 undistorted square, got {box_w}x{box_h}"

    # 3. Portrait jacket (200x360) on TATE 64x128 -> ALSO pans Left -> Right (never static!),
    #    zooms to cover with zero black bars, and centers vertically!
    port_arr = np.zeros((360, 200, 3), dtype=np.uint8)
    port_arr[:, :90, 0] = 240    # Left = Red
    port_arr[:, 110:, 2] = 240   # Right = Blue
    port_arr[150:210, :, 1] = 220  # Vertical center band = Green
    port_path = tmp_path / "portrait_jacket.png"
    Image.fromarray(port_arr).save(port_path)

    res_port = processor.process_image_panorama(
        port_path,
        tmp_path,
        width=64,
        height=128,
        duration_s=2.5,
        fps=16,
        smart_color_boost=False,
        stem="tate_jacket_ltr",
    )
    assert res_port.gif_path is not None
    frames_port, _ = extract_frames_from_gif(res_port.gif_path)
    p_first = frames_port[0].mean(axis=(0, 1))
    p_last = frames_port[-1].mean(axis=(0, 1))
    assert p_first[0] > p_first[2] + 40, f"Expected Left=Red start on TATE portrait jacket, got {p_first}"
    assert p_last[2] > p_last[0] + 40, f"Expected Right=Blue end on TATE portrait jacket, got {p_last}"
    # Zero black bars on top/bottom and green band remains vertically centered around row 64
    assert frames_port[0][:4, :, :].max(axis=2).mean() > 100
    assert frames_port[0][-4:, :, :].max(axis=2).mean() > 100
    green_rows = np.where(frames_port[0][:, :, 1].mean(axis=1) > 120)[0]
    assert len(green_rows) > 0 and abs(float(green_rows.mean()) - 63.5) <= 6.0

    # 4. Wide 4:1 marquee (400x100) on YOKO 128x32 -> MUST pan Top -> Bottom (never static!),
    #    zooming uniformly to eliminate black bars and centering horizontally!
    yoko_marq = np.zeros((100, 400, 3), dtype=np.uint8)
    yoko_marq[:45, :, 0] = 240    # Top = Red
    yoko_marq[55:, :, 2] = 240    # Bottom = Blue
    yoko_marq[:, 170:230, 1] = 230  # Horizontal center band = Green
    yoko_path = tmp_path / "yoko_marquee.png"
    Image.fromarray(yoko_marq).save(yoko_path)

    res_yoko = processor.process_image_panorama(
        yoko_path,
        tmp_path,
        width=128,
        height=32,
        duration_s=2.5,
        fps=16,
        smart_color_boost=False,
        stem="yoko_marquee_ttb",
    )
    assert res_yoko.gif_path is not None
    frames_yoko, _ = extract_frames_from_gif(res_yoko.gif_path)
    y_first = frames_yoko[0].mean(axis=(0, 1))
    y_last = frames_yoko[-1].mean(axis=(0, 1))
    assert y_first[0] > y_first[2] + 50, f"Expected Top=Red start on YOKO marquee, got {y_first}"
    assert y_last[2] > y_last[0] + 50, f"Expected Bottom=Blue end on YOKO marquee, got {y_last}"
    # Zero black bars on left/right and green band remains horizontally centered around col 64
    assert frames_yoko[0][:, :4, :].max(axis=2).mean() > 100
    assert frames_yoko[0][:, -4:, :].max(axis=2).mean() > 100
    green_cols = np.where(frames_yoko[0][:, :, 1].mean(axis=0) > 120)[0]
    assert len(green_cols) > 0 and abs(float(green_cols.mean()) - 63.5) <= 6.0


def test_process_video_trailer_end_to_end(tmp_path: Path):
    video_path = tmp_path / "synthetic_trailer.mp4"
    fps = 15
    width, height = 320, 180
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, float(fps), (width, height))
    assert writer.isOpened()

    # Write 3 seconds (45 frames) with moving bright rectangle
    for idx in range(45):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x0 = (idx * 5) % (width - 60)
        cv2.rectangle(frame, (x0, 40), (x0 + 60, 140), (0, 200, 255), -1)
        writer.write(frame)
    writer.release()

    processor = DmdMediaProcessor()
    cfg = DmdClipConfig(
        width=128,
        height=32,
        fps=12,
        max_duration_s=2.0,
        use_ai_moments=False,
        use_auto_action=False,
        use_smart_color_boost=True,
    )
    result = processor.process_video_trailer(
        input_video=video_path,
        output_dir=tmp_path / "out",
        config=cfg,
        export_gif=True,
        export_rgb565_stream=True,
        stem="mslug_clip",
    )

    assert result.gif_path is not None and result.gif_path.exists()
    assert result.rgb565_stream_path is not None and result.rgb565_stream_path.exists()
    assert result.width == 128
    assert result.height == 32
    assert result.frame_count > 0

    header = read_rgb565_stream_header(result.rgb565_stream_path)
    assert header["width"] == 128
    assert header["height"] == 32
    assert header["total_frames"] == result.frame_count


def test_cinema_auto_action_smart_color_preserves_gentle_saturation(tmp_path: Path):
    """
    Regression test: `mode='cinema'` with `use_auto_action=True, use_smart_color_boost=True`
    must NOT be overwritten by legacy `pixel_art` 2.5-3.3x saturation or 1.8 sharpen.
    """
    video_path = tmp_path / "live_action_skin_tones.mp4"
    width, height, fps = 320, 180, 15
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(video_path), fourcc, float(fps), (width, height))
    assert writer.isOpened()

    # Warm natural skin-tone midtone (RGB ~ (182, 138, 114)) with gentle motion
    for idx in range(30):
        frame_bgr = np.zeros((height, width, 3), dtype=np.uint8)
        frame_bgr[:, :] = (114, 138, 182)
        x0 = 40 + (idx * 5) % 200
        cv2.circle(frame_bgr, (x0, 90), 28, (130, 156, 204), -1)
        writer.write(frame_bgr)
    writer.release()

    logs: list[str] = []
    processor = DmdMediaProcessor()
    cfg = DmdClipConfig(
        width=128,
        height=32,
        fps=15,
        max_duration_s=1.8,
        mode="cinema",
        use_ai_moments=False,
        use_auto_action=True,
        use_smart_color_boost=True,
    )
    res = processor.process_video_trailer(
        input_video=video_path,
        output_dir=tmp_path / "cinema_out",
        config=cfg,
        export_gif=True,
        export_rgb565_stream=True,
        stem="cinema_clip",
        callback=lambda m, _lvl: logs.append(m),
    )

    color_logs = [m for m in logs if "[COLOR" in m]
    assert color_logs, f"Expected [COLOR] log entry, got: {logs}"
    assert "auto-color/cinema" in color_logs[0]
    import re

    m_sat = re.search(r"→.*?sat=([0-9.]+)", color_logs[0])
    assert m_sat is not None, f"Could not parse output saturation from: {color_logs[0]}"
    sat_val = float(m_sat.group(1))
    assert 1.05 <= sat_val <= 1.38, f"Cinema saturation out of calibrated range: {sat_val}"

    # Verify skin-tone red channel in RGB565 stream is NOT blown out to 248 (0x1F)
    raw = res.rgb565_stream_path.read_bytes()[DMDS_HEADER_SIZE:]
    first_rgb = rgb565_le_to_rgb888(raw[: 128 * 32 * 2], 128, 32)
    mean_r = float(first_rgb[:, :, 0].mean())
    mean_g = float(first_rgb[:, :, 1].mean())
    assert mean_r < 225.0 and (mean_r - mean_g) < 75.0, (
        f"Unexpected red clipping on cinema midtones: R={mean_r:.1f}, G={mean_g:.1f}"
    )


def test_direct_rgb565_stream_preserves_true_16bit_gradients_with_and_without_gif(tmp_path: Path):
    """
    Regression test: `process_video_trailer(..., export_rgb565_stream=True)` must extract
    24-bit RGB directly into 16-bit RGB565 (>256 smooth colors per frame, never 256-color GIF
    quantized), both when `export_gif=True` and when `export_gif=False`.
    """
    assert dmd_gif_converter.SUPPORTS_DIRECT_RGB565_STREAM is True

    video_path = tmp_path / "smooth_gradient_ramp.avi"
    width, height, fps = 256, 64, 15
    # Uncompressed MJPG / high-bitrate video with a 2D full-spectrum RGB gradient (>1,500 RGB565 colors)
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(video_path), fourcc, float(fps), (width, height))
    assert writer.isOpened()

    xs = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    ys = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    for idx in range(24):
        shift = float(idx * 2)
        r = np.broadcast_to(np.clip(xs, 0, 255).astype(np.uint8), (height, width))
        g = np.broadcast_to(np.clip(ys, 0, 255).astype(np.uint8), (height, width))
        b = np.clip(255.0 - 0.5 * xs + 0.35 * ys - shift, 0, 255).astype(np.uint8)
        bgr = np.stack([b, g, r], axis=-1)
        writer.write(bgr)
    writer.release()

    processor = DmdMediaProcessor()
    cfg = DmdClipConfig(
        width=128,
        height=32,
        fps=15,
        max_duration_s=1.4,
        mode="cinema",
        use_ai_moments=False,
        use_auto_action=False,
        use_smart_color_boost=False,
    )

    # 1. Both GIF + RGB565 stream
    res_both = processor.process_video_trailer(
        input_video=video_path,
        output_dir=tmp_path / "both",
        config=cfg,
        export_gif=True,
        export_rgb565_stream=True,
        stem="grad_both",
    )
    assert res_both.gif_path is not None and res_both.gif_path.exists()
    assert res_both.rgb565_stream_path is not None and res_both.rgb565_stream_path.exists()
    assert res_both.fps == 15

    gif_frames, _ = extract_frames_from_gif(res_both.gif_path)
    gif_f0_565 = np.frombuffer(rgb888_to_rgb565_le(gif_frames[0]), dtype="<u2")
    gif_unique_colors = int(np.unique(gif_f0_565).size)
    assert gif_unique_colors <= 256

    stream_raw = res_both.rgb565_stream_path.read_bytes()[DMDS_HEADER_SIZE:]
    stream_f0_565 = np.frombuffer(stream_raw[: 128 * 32 * 2], dtype="<u2")
    stream_unique_colors = int(np.unique(stream_f0_565).size)
    assert stream_unique_colors > 600, (
        f"Expected true 16-bit RGB565 smooth gradient (>600 unique colors), got {stream_unique_colors} (GIF had {gif_unique_colors})"
    )

    # 2. Stream-only (`export_gif=False`)
    res_stream_only = processor.process_video_trailer(
        input_video=video_path,
        output_dir=tmp_path / "stream_only",
        config=cfg,
        export_gif=False,
        export_rgb565_stream=True,
        stem="grad_only",
    )
    assert res_stream_only.gif_path is None
    assert not (tmp_path / "stream_only" / "grad_only.gif").exists()
    assert res_stream_only.rgb565_stream_path is not None and res_stream_only.rgb565_stream_path.exists()
    assert res_stream_only.fps == 15
    only_raw = res_stream_only.rgb565_stream_path.read_bytes()[DMDS_HEADER_SIZE:]
    only_unique_colors = int(np.unique(np.frombuffer(only_raw[: 128 * 32 * 2], dtype="<u2")).size)
    assert only_unique_colors > 600


