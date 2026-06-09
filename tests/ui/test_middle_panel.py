import unittest
from unittest.mock import MagicMock, patch
import customtkinter as ctk
from src.ui.panels.middle_panel import MiddlePanel


def _make_panel():
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
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
        self.assertIn("\u2026", text)


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
        with patch.dict("sys.modules", {"send2trash": None}), \
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
        panel._stat_vars["Premium"].configure.assert_called_with(text="\U0001f31f 1")


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
