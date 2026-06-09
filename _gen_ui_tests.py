"""Generator script — creates UI test files without passing large strings through terminal."""
import os, textwrap

BASE = os.path.join(os.path.dirname(__file__), "tests", "ui")

# ── test_middle_panel.py ──────────────────────────────────────────────────────
MIDDLE = textwrap.dedent("""\
    import unittest
    from unittest.mock import MagicMock, patch
    import customtkinter as ctk
    from src.ui.panels.middle_panel import MiddlePanel


    def _make_panel():
        with patch.object(ctk.CTkFrame, "__init__", return_value=None), \\
             patch.object(MiddlePanel, "_build_ui", return_value=None):
            panel = MiddlePanel(MagicMock(), MagicMock())
        panel._tree_converted = MagicMock()
        panel._converted_count_lbl = MagicMock()
        panel._stat_vars = {k: MagicMock() for k in
                            ["total", "Premium", "Good", "Acceptable", "Poor", "Bad"]}
        return panel


    def _make_with_data():
        panel = _make_panel()
        panel._converted_data = {
            "iid1": {"path": "/a.gif", "score": 80, "rating": "Good", "color": "G", "reasons": []},
            "iid2": {"path": "/b.gif", "score": 40, "rating": "Poor", "color": "P", "reasons": []},
            "iid3": {"path": "/c.gif", "score": 20, "rating": "Bad",  "color": "B", "reasons": []},
        }
        panel._converted_paths = {"/a.gif", "/b.gif", "/c.gif"}
        panel._tree_converted.get_children.return_value = ("iid1", "iid2", "iid3")
        panel._tree_converted.exists.return_value = True
        return panel


    class TestAddConvertedFile(unittest.TestCase):
        def test_new_file_stored(self):
            panel = _make_panel()
            panel._tree_converted.insert.return_value = "iid1"
            panel._add_converted_file("/out/foo.gif", {"score": 80, "rating": "Good", "color": "G", "reasons": ["r"]})
            self.assertIn("iid1", panel._converted_data)
            self.assertEqual(panel._converted_data["iid1"]["score"], 80)
            self.assertIn("/out/foo.gif", panel._converted_paths)

        def test_duplicate_ignored(self):
            panel = _make_panel()
            panel._converted_paths.add("/out/foo.gif")
            panel._add_converted_file("/out/foo.gif", {"score": 80, "rating": "Good", "color": "G", "reasons": []})
            panel._tree_converted.insert.assert_not_called()

        def test_long_name_truncated(self):
            panel = _make_panel()
            panel._tree_converted.insert.return_value = "iid1"
            panel._add_converted_file("/out/" + "a"*30 + ".gif", {"score": 50, "rating": "Acceptable", "color": "A", "reasons": []})
            text = panel._tree_converted.insert.call_args[1]["text"]
            self.assertIn("\\u2026", text)


    class TestClearConverted(unittest.TestCase):
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_cancelled(self, mock_msg):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = False
            panel._clear_converted()
            panel._tree_converted.delete.assert_not_called()
            self.assertEqual(len(panel._converted_data), 3)

        @patch("os.path.exists", return_value=False)
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_success(self, mock_msg, _):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = True
            with patch.dict("sys.modules", {"send2trash": None}):
                panel._clear_converted()
            panel._tree_converted.delete.assert_called_with("iid1", "iid2", "iid3")
            self.assertEqual(len(panel._converted_data), 0)
            self.assertEqual(panel._selected_converted_iid, "")

        @patch("src.ui.panels.middle_panel.messagebox")
        def test_empty_list_noop(self, mock_msg):
            _make_panel()._clear_converted()
            mock_msg.askyesno.assert_not_called()

        @patch("os.path.exists", return_value=False)
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_empty_tree_safe(self, mock_msg, _):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = True
            panel._tree_converted.get_children.return_value = ()
            with patch.dict("sys.modules", {"send2trash": None}):
                panel._clear_converted()
            panel._tree_converted.delete.assert_not_called()
            self.assertEqual(len(panel._converted_data), 0)


    class TestCleanupByScore(unittest.TestCase):
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_no_match_info(self, mock_msg):
            _make_with_data()._cleanup_by_score(10)
            mock_msg.showinfo.assert_called()
            mock_msg.askyesno.assert_not_called()

        @patch("src.ui.panels.middle_panel.messagebox")
        def test_cancel_intact(self, mock_msg):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = False
            panel._cleanup_by_score(50)
            self.assertEqual(len(panel._converted_data), 3)

        @patch("os.path.exists", return_value=True)
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_removes_below_threshold(self, mock_msg, _):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = True
            with patch.dict("sys.modules", {"send2trash": None}), patch("os.remove"):
                panel._cleanup_by_score(50)
            self.assertIn("iid1", panel._converted_data)
            self.assertNotIn("iid2", panel._converted_data)
            self.assertNotIn("iid3", panel._converted_data)

        @patch("os.path.exists", return_value=False)
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_file_missing_ui_still_cleared(self, mock_msg, _):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = True
            with patch.dict("sys.modules", {"send2trash": None}), patch("os.remove") as m:
                panel._cleanup_by_score(50)
            m.assert_not_called()
            self.assertNotIn("iid2", panel._converted_data)

        @patch("os.path.exists", return_value=True)
        @patch("src.ui.panels.middle_panel.messagebox")
        def test_exception_caught(self, mock_msg, _):
            panel = _make_with_data()
            mock_msg.askyesno.return_value = True
            with patch.dict("sys.modules", {"send2trash": None}), \\
                 patch("os.remove", side_effect=PermissionError("denied")):
                panel._cleanup_by_score(50)
            self.assertNotIn("iid2", panel._converted_data)


    class TestRemoveSelectedConverted(unittest.TestCase):
        def test_empty_sel_noop(self):
            panel = _make_panel()
            panel._tree_converted.selection.return_value = ()
            panel._remove_selected_converted()
            panel._tree_converted.delete.assert_not_called()

        def test_removes_from_data_and_paths(self):
            panel = _make_panel()
            panel._converted_data = {"iid1": {"path": "/a.gif"}}
            panel._converted_paths = {"/a.gif"}
            panel._tree_converted.selection.return_value = ("iid1",)
            panel._remove_selected_converted()
            self.assertNotIn("iid1", panel._converted_data)
            self.assertNotIn("/a.gif", panel._converted_paths)
            self.assertEqual(panel._selected_converted_iid, "")


    class TestSortConverted(unittest.TestCase):
        def test_by_score(self):
            panel = _make_panel()
            panel._tree_converted.get_children.return_value = ("a", "b", "c")
            scores = {"a": "P 40%", "b": "B 20%", "c": "E 80%"}
            panel._tree_converted.set.side_effect = lambda k, col: scores[k]
            panel._sort_converted("score")
            panel._tree_converted.move.assert_called()

        def test_by_category(self):
            panel = _make_panel()
            panel._tree_converted.get_children.return_value = ("a", "b")
            cats = {"a": "Good", "b": "Excellent"}
            panel._tree_converted.set.side_effect = lambda k, col: cats[k]
            panel._sort_converted("Category")
            panel._tree_converted.move.assert_called()

        def test_by_name(self):
            panel = _make_panel()
            panel._tree_converted.get_children.return_value = ("a", "b")
            panel._tree_converted.item.side_effect = lambda k: {"a": {"text": " z.gif"}, "b": {"text": " a.gif"}}[k]
            panel._tree_converted.set.side_effect = lambda k, col: ""
            panel._sort_converted("name")
            panel._tree_converted.move.assert_called()

        def test_toggles_direction(self):
            panel = _make_panel()
            panel._tree_converted.get_children.return_value = ()
            panel._sort_converted("score")
            panel._sort_converted("score")
            self.assertFalse(panel._sort_dirs["score"])


    class TestUpdateStatistics(unittest.TestCase):
        def test_empty(self):
            panel = _make_panel()
            panel._update_statistics()
            panel._stat_vars["total"].configure.assert_called_with(text="Tot: 0")

        def test_mixed(self):
            panel = _make_panel()
            panel._converted_data = {"a": {"rating": "Excellent"}, "b": {"rating": "Good"}, "c": {"rating": "Bad"}}
            panel._update_statistics()
            panel._stat_vars["total"].configure.assert_called_with(text="Tot: 3")
            panel._stat_vars["Premium"].configure.assert_called_with(text="\\U0001f31f 1")


    class TestOnFilterChanged(unittest.TestCase):
        def _p(self, q="", preset="All"):
            panel = _make_panel()
            panel.app_state.v_search_converted.get.return_value = q
            panel.app_state.v_filter_preset.get.return_value = preset
            panel._tree_converted.get_children.return_value = ()
            return panel

        def test_no_filter_all_shown(self):
            panel = self._p()
            panel._converted_data = {
                "a": {"path": "/foo.gif", "score": 90, "rating": "Excellent", "color": "E"},
                "b": {"path": "/bar.gif", "score": 50, "rating": "Acceptable", "color": "A"},
            }
            panel._on_filter_changed()
            self.assertEqual(panel._tree_converted.insert.call_count, 2)

        def test_text_filter_excludes(self):
            panel = self._p(q="bar")
            panel._converted_data = {"a": {"path": "/foo.gif", "score": 90, "rating": "Excellent", "color": "E"}}
            panel._on_filter_changed()
            panel._tree_converted.insert.assert_not_called()

        def test_excellent_only_preset(self):
            panel = self._p(preset="Excellent Only")
            panel._converted_data = {
                "a": {"path": "/foo.gif", "score": 50, "rating": "Acceptable", "color": "A"},
                "b": {"path": "/bar.gif", "score": 90, "rating": "Excellent",  "color": "E"},
            }
            panel._on_filter_changed()
            self.assertEqual(panel._tree_converted.insert.call_count, 1)


    class TestClearPreviewViaBus(unittest.TestCase):
        def test_publishes_six_actions(self):
            from src.ui.events.event_bus import EventBus, EventType
            received = []
            EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, lambda p: received.append(p["action"]))
            _make_panel()._clear_preview_via_bus()
            self.assertEqual({"stop_src", "stop_auto", "stop_dmd", "idle_src", "idle_auto", "idle_dmd"}, set(received))
            EventBus.clear()


    class TestOnConvertedTreeSelect(unittest.TestCase):
        def setUp(self):
            from src.ui.events.event_bus import EventBus
            EventBus.clear()
        def tearDown(self):
            from src.ui.events.event_bus import EventBus
            EventBus.clear()

        def test_same_iid_no_event(self):
            from src.ui.events.event_bus import EventBus, EventType
            received = []
            EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, lambda p: received.append(p))
            panel = _make_panel()
            panel._selected_converted_iid = "iid1"
            panel._converted_data = {"iid1": {"path": "/a.gif"}}
            panel._tree_converted.selection.return_value = ("iid1",)
            panel._tree_converted.focus.return_value = "iid1"
            panel._on_converted_tree_select()
            self.assertEqual(len(received), 0)

        def test_new_selection_publishes(self):
            from src.ui.events.event_bus import EventBus, EventType
            received = []
            EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, lambda p: received.append(p))
            panel = _make_panel()
            panel._selected_converted_iid = ""
            panel._converted_data = {"iid2": {"path": "/b.gif"}}
            panel._tree_converted.selection.return_value = ("iid2",)
            panel._tree_converted.focus.return_value = "iid2"
            panel._on_converted_tree_select()
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0]["path"], "/b.gif")

        def test_empty_selection_returns_early(self):
            from src.ui.events.event_bus import EventBus, EventType
            received = []
            EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED, lambda p: received.append(p))
            panel = _make_panel()
            panel._tree_converted.selection.return_value = ()
            panel._on_converted_tree_select()
            self.assertEqual(len(received), 0)


    if __name__ == "__main__":
        unittest.main()
    """)

# ── test_ui_mixins.py ─────────────────────────────────────────────────────────
MIXINS = textwrap.dedent("""\
    import unittest
    from unittest.mock import MagicMock, patch
    import customtkinter as ctk
    from src.ui.panels.left_panel import LeftPanel


    def _make_left_panel():
        with patch.object(ctk.CTkFrame, "__init__", return_value=None), \\
             patch.object(LeftPanel, "_build_ui", return_value=None), \\
             patch("src.ui.panels.left_panel.EventBus.subscribe"):
            panel = LeftPanel(MagicMock(), MagicMock())
        panel._tree = MagicMock()
        panel._count_lbl = MagicMock()
        panel.after = MagicMock()
        return panel


    class TestAddFileRaw(unittest.TestCase):
        def test_new_file_inserted(self):
            panel = _make_left_panel()
            panel._tree.insert.return_value = "iid1"
            panel._add_file_raw("/foo/bar.mp4")
            self.assertIn("/foo/bar.mp4", panel._file_paths)
            self.assertEqual(panel._file_data["iid1"], "/foo/bar.mp4")

        def test_duplicate_skipped(self):
            panel = _make_left_panel()
            panel._file_paths.add("/foo/bar.mp4")
            panel._add_file_raw("/foo/bar.mp4")
            panel._tree.insert.assert_not_called()

        def test_gif_icon(self):
            panel = _make_left_panel()
            panel._tree.insert.return_value = "iid1"
            panel._add_file_raw("/foo/anim.gif")
            self.assertIn("\\U0001f39e", panel._tree.insert.call_args[1]["text"])

        def test_video_icon(self):
            panel = _make_left_panel()
            panel._tree.insert.return_value = "iid1"
            panel._add_file_raw("/foo/movie.mp4")
            self.assertIn("\\U0001f3ac", panel._tree.insert.call_args[1]["text"])

        def test_long_name_truncated(self):
            panel = _make_left_panel()
            panel._tree.insert.return_value = "iid1"
            panel._add_file_raw("/foo/" + "x"*30 + ".mp4")
            self.assertIn("\\u2026", panel._tree.insert.call_args[1]["text"])


    class TestBatchInsert(unittest.TestCase):
        def test_single_batch(self):
            panel = _make_left_panel()
            panel._tree.insert.side_effect = lambda *a, **kw: str(id(kw))
            panel._batch_insert(["/a.mp4", "/b.mp4", "/c.mp4"], 0)
            self.assertEqual(len(panel._file_paths), 3)

        def test_dedup(self):
            panel = _make_left_panel()
            panel._file_paths.add("/a.mp4")
            panel._tree.insert.side_effect = lambda *a, **kw: str(id(kw))
            panel._batch_insert(["/a.mp4", "/b.mp4"], 0)
            self.assertEqual(panel._tree.insert.call_count, 1)

        def test_empty(self):
            panel = _make_left_panel()
            panel._batch_insert([], 0)
            panel._tree.insert.assert_not_called()


    class TestUpdateCount(unittest.TestCase):
        def test_zero(self):
            _make_left_panel()._update_count()

        def test_one_file(self):
            panel = _make_left_panel()
            panel._file_data["iid1"] = "/a.mp4"
            panel._update_count()
            panel._count_lbl.configure.assert_called_with(text="1 file")

        def test_many(self):
            panel = _make_left_panel()
            panel._file_data = {"a": "/a.mp4", "b": "/b.mp4", "c": "/c.mp4"}
            panel._update_count()
            panel._count_lbl.configure.assert_called_with(text="3 files")


    class TestOnFilesAddedToQueue(unittest.TestCase):
        def test_with_list(self):
            panel = _make_left_panel()
            panel._on_files_added_to_queue(["/x.mp4"])
            panel.after.assert_called_once()

        def test_empty_list(self):
            panel = _make_left_panel()
            panel._on_files_added_to_queue([])
            panel.after.assert_not_called()

        def test_none_payload(self):
            panel = _make_left_panel()
            panel._on_files_added_to_queue(None)
            panel.after.assert_not_called()

        def test_dict_payload(self):
            panel = _make_left_panel()
            panel._on_files_added_to_queue({"path": "/x.mp4"})
            panel.after.assert_not_called()


    class TestScanFolderRefresh(unittest.TestCase):
        @patch("os.listdir", return_value=["a.mp4", "b.gif"])
        @patch("os.path.join", side_effect=lambda d, f: "/" + f)
        def test_new_files_triggers_after(self, _j, _l):
            _make_left_panel()._scan_folder_refresh("/d")

        @patch("os.listdir", return_value=["a.mp4"])
        @patch("os.path.join", side_effect=lambda d, f: "/a.mp4")
        def test_no_new_files(self, _j, _l):
            panel = _make_left_panel()
            panel._file_paths.add("/a.mp4")
            panel._scan_folder_refresh("/d")
            panel.after.assert_called()

        @patch("os.listdir", return_value=[])
        def test_empty_folder(self, _l):
            panel = _make_left_panel()
            panel._scan_folder_refresh("/d")
            panel.after.assert_called()


    class TestRemoveSelected(unittest.TestCase):
        def test_empty_noop(self):
            panel = _make_left_panel()
            panel._tree.selection.return_value = ()
            panel._remove_selected()
            panel._tree.delete.assert_not_called()

        def test_removes_item(self):
            panel = _make_left_panel()
            panel._file_data = {"iid1": "/a.mp4"}
            panel._file_paths = {"/a.mp4"}
            panel._tree.selection.return_value = ("iid1",)
            panel._selected_iid = "other"
            panel._remove_selected()
            self.assertNotIn("iid1", panel._file_data)

        def test_clears_selected_iid(self):
            panel = _make_left_panel()
            panel._file_data = {"iid1": "/a.mp4"}
            panel._file_paths = {"/a.mp4"}
            panel._selected_iid = "iid1"
            panel._tree.selection.return_value = ("iid1",)
            for m in ["_stop_src_preview", "_stop_auto_preview", "_stop_dmd_preview",
                      "_draw_canvas_idle", "_draw_auto_canvas_idle", "_draw_dmd_canvas_idle"]:
                setattr(panel, m, MagicMock())
            panel._trim_frame = MagicMock()
            panel._remove_selected()
            self.assertEqual(panel._selected_iid, "")


    if __name__ == "__main__":
        unittest.main()
    """)

# ── test_ai_moments.py ────────────────────────────────────────────────────────
AI = textwrap.dedent("""\
    import unittest
    from unittest.mock import MagicMock, patch
    import customtkinter as ctk
    from src.ui.panels.ai_moments_panel import AiMomentsPanel


    class MockVar:
        def __init__(self, v=0.0): self._v = v
        def set(self, v): self._v = v
        def get(self): return self._v


    def _make():
        with patch.object(ctk.CTkFrame, "__init__", return_value=None), \\
             patch.object(AiMomentsPanel, "_build_ai_moments_panel", return_value=None):
            app_state = MagicMock()
            panel = AiMomentsPanel(MagicMock(), app_state)
        panel.app_state = app_state
        panel.app_state.v_playhead = MockVar(0.0)
        panel.app_state.v_manual_start = MockVar(0.0)
        panel.app_state.v_manual_end = MockVar(5.0)
        panel._lbl_selection = MagicMock()
        panel.after = MagicMock()
        return panel


    class TestSetInPoint(unittest.TestCase):
        def test_sets_start(self):
            p = _make()
            p.app_state.v_playhead.set(2.0)
            p._set_in_point()
            self.assertEqual(p.app_state.v_manual_start.get(), 2.0)
            p._lbl_selection.configure.assert_called()

        def test_pushes_end(self):
            p = _make()
            p.app_state.v_playhead.set(6.0)
            p.app_state.v_manual_end.set(5.0)
            p._set_in_point()
            self.assertEqual(p.app_state.v_manual_end.get(), 7.0)

        def test_end_unchanged_when_in_before(self):
            p = _make()
            p.app_state.v_playhead.set(1.0)
            p.app_state.v_manual_end.set(5.0)
            p._set_in_point()
            self.assertEqual(p.app_state.v_manual_end.get(), 5.0)


    class TestSetOutPoint(unittest.TestCase):
        def test_sets_end(self):
            p = _make()
            p.app_state.v_playhead.set(4.0)
            p.app_state.v_manual_start.set(2.0)
            p._set_out_point()
            self.assertEqual(p.app_state.v_manual_end.get(), 4.0)
            self.assertEqual(p.app_state.v_manual_start.get(), 2.0)

        def test_pushes_start(self):
            p = _make()
            p.app_state.v_playhead.set(1.0)
            p.app_state.v_manual_start.set(3.0)
            p._set_out_point()
            self.assertEqual(p.app_state.v_manual_end.get(), 1.0)
            self.assertEqual(p.app_state.v_manual_start.get(), 0.0)


    class TestTogglePlaySelection(unittest.TestCase):
        def test_starts_play(self):
            p = _make()
            p._ai_preview_cap = MagicMock()
            p._ai_preview_cap.get.return_value = 30.0
            p._is_playing_selection = False
            p._btn_play_selection = MagicMock()
            p._on_playhead_change = MagicMock()
            p._toggle_play_selection()
            self.assertTrue(p._is_playing_selection)
            p.after.assert_called()

        def test_stops_play(self):
            p = _make()
            p._ai_preview_cap = MagicMock()
            p._is_playing_selection = True
            p._btn_play_selection = MagicMock()
            p._toggle_play_selection()
            self.assertFalse(p._is_playing_selection)

        def test_no_cap_noop(self):
            p = _make()
            p._ai_preview_cap = None
            p._is_playing_selection = False
            p._toggle_play_selection()
            p.after.assert_not_called()


    class TestOnAiAnalysisComplete(unittest.TestCase):
        def test_enables_report_button(self):
            p = _make()
            p._btn_ai_show_report = MagicMock()
            p._ai_results = []
            p._add_moments_to_queue = MagicMock()
            p._show_ai_report_popup = MagicMock()
            p._populate_results = MagicMock()
            result = [MagicMock()]
            p._on_ai_analysis_complete(result)
            p._btn_ai_show_report.configure.assert_called_with(state="normal")
            self.assertEqual(p._ai_results, result)

        def test_no_results_noop_queue(self):
            p = _make()
            p._btn_ai_show_report = MagicMock()
            p._add_moments_to_queue = MagicMock()
            p._show_ai_report_popup = MagicMock()
            p._populate_results = MagicMock()
            p._on_ai_analysis_complete([])
            p._add_moments_to_queue.assert_not_called()


    if __name__ == "__main__":
        unittest.main()
    """)

for fname, code in [
    ("test_middle_panel.py", MIDDLE),
    ("test_ui_mixins.py", MIXINS),
    ("test_ai_moments.py", AI),
]:
    path = os.path.join(BASE, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"Written: {path}")

# ── tests/ui/test_controllers.py ─────────────────────────────────────────────
CONTROLLERS = textwrap.dedent("""\
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
            cc._model.get.return_value = ""
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
            with patch("src.engine.conversion.core.process_file") as mock_pf, \\
                 patch("src.engine.conversion.services.job_expander.expand_conversion_jobs",
                       return_value=[("iid1", "/a.mp4", {}, "")]), \\
                 patch("os.makedirs"):
                mock_pf.return_value = (True, "ok")
                cc._run_conversion(["/a.mp4"])
            mock_pf.assert_called_once()
            cc._view.after.assert_called()

        def test_run_conversion_cancel_flag_stops_loop(self):
            cc = self._make()
            cc._cancel_flag = True
            with patch("src.engine.conversion.core.process_file") as mock_pf, \\
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
            with patch("src.engine.conversion.core.process_file") as mock_pf, \\
                 patch("src.engine.conversion.services.job_expander.expand_conversion_jobs",
                       return_value=[("iid1", "/a.mp4", {}, "")]), \\
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
            pc._view._generate_dmd_preview = MagicMock()
            pc._trigger_refresh()
            pc._view._generate_dmd_preview.assert_called_once()
            self.assertIsNone(pc._pending_job)

        def test_trigger_refresh_no_method_is_safe(self):
            pc = self._make()
            # Remove the method to test graceful fallback
            del pc._view._generate_dmd_preview
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
    """)

controllers_path = os.path.join(BASE, "test_controllers.py")
with open(controllers_path, "w", encoding="utf-8") as f:
    f.write(CONTROLLERS)
print(f"Written: {controllers_path}")


