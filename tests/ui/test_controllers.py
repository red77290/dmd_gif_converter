import unittest
import threading
from unittest.mock import MagicMock, patch, call
from src.ui.controllers.conversion_controller import ConversionController
from src.ui.controllers.preview_controller import PreviewController


class TestConversionController(unittest.TestCase):

    def _make(self):
        cc = ConversionController()
        cc._view = MagicMock()
        cc._model = MagicMock()
        cc._model.build_params.return_value = {}
        cc._model.get.side_effect = lambda k, d=None: d
        return cc

    def test_bind_sets_view_and_model(self):
        cc = ConversionController()
        view, model = MagicMock(), MagicMock()
        cc.bind(view, model)
        self.assertIs(cc._view, view)
        self.assertIs(cc._model, model)

    def test_on_action_cancel_sets_flag(self):
        cc = self._make()
        cc.on_action("cancel")
        self.assertTrue(cc._cancel_flag)

    def test_on_action_unknown_is_noop(self):
        cc = self._make()
        cc.on_action("foobar")
        # No crash, cancel_flag stays False
        self.assertFalse(cc._cancel_flag)

    def test_start_conversion_launches_thread(self):
        cc = self._make()
        with patch.object(cc, "_run_conversion") as mock_run:
            cc.on_action("convert_all", ["/a.mp4"])
            cc._active_thread.join(timeout=1.0)
        mock_run.assert_called_once_with(["/a.mp4"])

    def test_start_conversion_skips_if_running(self):
        cc = self._make()
        alive_thread = MagicMock()
        alive_thread.is_alive.return_value = True
        cc._active_thread = alive_thread
        with patch.object(cc, "_run_conversion") as mock_run:
            cc.on_action("convert_all", ["/a.mp4"])
        mock_run.assert_not_called()

    def test_cancel_conversion_sets_flag(self):
        cc = self._make()
        cc._cancel_conversion()
        self.assertTrue(cc._cancel_flag)

    def test_run_conversion_calls_process_file(self):
        cc = self._make()
        cc._model.get.side_effect = lambda k, d=None: {"v_output_dir": "/out", "v_trim_start": 0.0, "v_trim_end": 0.0}.get(k, d)
        with patch("src.engine.conversion.core.process_file") as mock_pf, \
             patch("src.engine.conversion.services.job_expander.expand_conversion_jobs",
                   return_value=[("iid1", "/a.mp4", {}, "")]), \
             patch("os.makedirs"):
            mock_pf.return_value = (True, "ok")
            cc._run_conversion(["/a.mp4"])
        mock_pf.assert_called_once()
        cc._view.after.assert_called()

    def test_run_conversion_cancel_flag_stops_loop(self):
        cc = self._make()
        cc._cancel_flag = True
        with patch("src.engine.conversion.core.process_file") as mock_pf, \
             patch("src.engine.conversion.services.job_expander.expand_conversion_jobs",
                   return_value=[("iid1", "/a.mp4", {}, "")]):
            cc._run_conversion(["/a.mp4"])
        mock_pf.assert_not_called()

    def test_run_conversion_no_model_returns_early(self):
        cc = ConversionController()
        cc._view = MagicMock()
        cc._model = None
        cc._run_conversion(["/a.mp4"])
        # Should not crash

    def test_run_conversion_error_calls_on_error(self):
        cc = self._make()
        cc._model.get.side_effect = lambda k, d=None: {"v_output_dir": "/out", "v_trim_start": 0.0, "v_trim_end": 0.0}.get(k, d)
        with patch("src.engine.conversion.core.process_file") as mock_pf, \
             patch("src.engine.conversion.services.job_expander.expand_conversion_jobs",
                   return_value=[("iid1", "/a.mp4", {}, "")]), \
             patch("os.makedirs"):
            mock_pf.return_value = (False, "FFmpeg failed")
            cc._run_conversion(["/a.mp4"])
        self.assertTrue(cc._view.after.called)


class TestPreviewController(unittest.TestCase):

    def _make(self):
        pc = PreviewController()
        pc._view = MagicMock()
        pc._model = MagicMock()
        pc._view.after.return_value = 42  # fake job id
        pc._view.after_cancel = MagicMock()
        return pc

    def test_bind_sets_view_and_model(self):
        pc = PreviewController()
        view, model = MagicMock(), MagicMock()
        pc.bind(view, model)
        self.assertIs(pc._view, view)
        self.assertIs(pc._model, model)

    def test_on_action_schedule_refresh(self):
        pc = self._make()
        pc.on_action("schedule_refresh")
        pc._view.after.assert_called_with(PreviewController.DEBOUNCE_MS, pc._trigger_refresh)

    def test_on_action_stop_cancels_pending(self):
        pc = self._make()
        pc._pending_job = 42
        pc.on_action("stop")
        pc._view.after_cancel.assert_called_with(42)
        self.assertIsNone(pc._pending_job)

    def test_schedule_refresh_cancels_previous_job(self):
        pc = self._make()
        pc._pending_job = 99
        pc._view.after.return_value = 55
        pc.schedule_refresh()
        pc._view.after_cancel.assert_called_with(99)
        self.assertEqual(pc._pending_job, 55)

    def test_schedule_refresh_no_view_is_noop(self):
        pc = PreviewController()
        pc._view = None
        pc._schedule_refresh()  # Should not crash

    def test_trigger_refresh_calls_generate_preview(self):
        pc = self._make()
        pc._view.refresh_all_previews = MagicMock()
        pc._trigger_refresh()
        pc._view.refresh_all_previews.assert_called_once()
        self.assertIsNone(pc._pending_job)

    def test_trigger_refresh_no_method_is_safe(self):
        pc = self._make()
        # Remove the method to test graceful fallback
        del pc._view.refresh_all_previews
        pc._trigger_refresh()  # Should not crash

    def test_cancel_pending_without_view_is_safe(self):
        pc = PreviewController()
        pc._pending_job = 1
        pc._view = None
        pc._cancel_pending()  # Should not crash

    def test_on_action_unknown_is_noop(self):
        pc = self._make()
        pc.on_action("foobar")  # No crash


if __name__ == "__main__":
    unittest.main()
