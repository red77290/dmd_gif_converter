"""Tests for Renderer (auto_action layer) — no Tkinter, uses numpy/cv2."""
import unittest
import numpy as np
import cv2
from src.engine.auto_action.renderer import Renderer


def _bgr_frame(h=240, w=320):
    """Build a random BGR frame for testing."""
    return np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)


class TestCropFrameStatic(unittest.TestCase):
    def test_returns_cropped_frame(self):
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)  # centre + size
        result = Renderer.crop_frame_static(frame, cam)
        self.assertEqual(result.shape[2], 3)
        self.assertGreater(result.shape[0], 0)
        self.assertGreater(result.shape[1], 0)

    def test_preserves_3_channels(self):
        frame = _bgr_frame(480, 640)
        cam = (320.0, 240.0, 320.0, 160.0)
        result = Renderer.crop_frame_static(frame, cam)
        self.assertEqual(len(result.shape), 3)


class TestRenderNoBgSub(unittest.TestCase):
    def test_output_is_correct_size(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=False)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        result = renderer.render(frame, cam)
        self.assertEqual(result.shape, (32, 128, 3))

    def test_output_dtype_uint8(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=False)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        result = renderer.render(frame, cam)
        self.assertEqual(result.dtype, np.uint8)

    def test_render_with_roi_no_bg_sub(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=False)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        roi = (100, 80, 80, 80)
        result = renderer.render(frame, cam, roi=roi)
        self.assertEqual(result.shape, (32, 128, 3))


class TestRenderWithBgSub(unittest.TestCase):
    def test_render_with_roi(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        roi = (100, 80, 80, 80)
        result = renderer.render(frame, cam, roi=roi)
        self.assertEqual(result.shape, (32, 128, 3))

    def test_render_no_roi_no_cached_mask(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        # No roi, no cached mask — should fall back to ones mask
        result = renderer.render(frame, cam, roi=None)
        self.assertEqual(result.shape, (32, 128, 3))

    def test_render_no_roi_uses_cached_mask(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        roi = (100, 80, 80, 80)
        # First render with roi — builds cached mask
        renderer.render(frame, cam, roi=roi)
        self.assertIsNotNone(renderer._last_vignette_mask)
        # Second render without roi — should use cached mask
        result = renderer.render(frame, cam, roi=None)
        self.assertEqual(result.shape, (32, 128, 3))

    def test_tail_frame_uses_cached_mask(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        roi = (100, 80, 80, 80)
        renderer.render(frame, cam, roi=roi)  # warm up cache
        result = renderer.render(frame, cam, roi=None, is_tail=True)
        self.assertEqual(result.shape, (32, 128, 3))

    def test_tail_frame_no_cache_uses_ones(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        frame = _bgr_frame(240, 320)
        cam = (160.0, 120.0, 160.0, 80.0)
        result = renderer.render(frame, cam, roi=None, is_tail=True)
        self.assertEqual(result.shape, (32, 128, 3))


class TestComputeVignette(unittest.TestCase):
    def test_not_tail_with_roi_builds_mask(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        roi = (80, 60, 80, 80)
        mask = renderer._compute_vignette(roi, is_tail=False)
        self.assertIsNotNone(mask)
        self.assertEqual(mask.shape, (240, 320))
        self.assertIsNotNone(renderer._last_vignette_mask)

    def test_not_tail_no_roi_no_cache_ones(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        mask = renderer._compute_vignette(None, is_tail=False)
        self.assertTrue(np.all(mask == 1.0))

    def test_not_tail_no_roi_with_cache(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        cached = np.full((240, 320), 0.5, dtype=np.float32)
        renderer._last_vignette_mask = cached
        mask = renderer._compute_vignette(None, is_tail=False)
        self.assertTrue(np.array_equal(mask, cached))

    def test_tail_with_cache(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        cached = np.full((240, 320), 0.7, dtype=np.float32)
        renderer._last_vignette_mask = cached
        mask = renderer._compute_vignette(None, is_tail=True)
        self.assertTrue(np.array_equal(mask, cached))

    def test_tail_no_cache_ones(self):
        renderer = Renderer(frame_w=320, frame_h=240, out_w=128, out_h=32, bg_sub_enable=True)
        mask = renderer._compute_vignette(None, is_tail=True)
        self.assertTrue(np.all(mask == 1.0))


if __name__ == "__main__":
    unittest.main()

