import unittest
from unittest.mock import MagicMock, patch
import customtkinter as ctk
from src.ui.panels.left_panel import LeftPanel


def _make_left_panel():
    with patch.object(ctk.CTkFrame, "__init__", return_value=None), \
         patch.object(LeftPanel, "_build_ui", return_value=None), \
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
        self.assertIn("\U0001f39e", panel._tree.insert.call_args[1]["text"])

    def test_video_icon(self):
        panel = _make_left_panel()
        panel._tree.insert.return_value = "iid1"
        panel._add_file_raw("/foo/movie.mp4")
        self.assertIn("\U0001f3ac", panel._tree.insert.call_args[1]["text"])

    def test_long_name_truncated(self):
        panel = _make_left_panel()
        panel._tree.insert.return_value = "iid1"
        panel._add_file_raw("/foo/" + "x"*30 + ".mp4")
        self.assertIn("\u2026", panel._tree.insert.call_args[1]["text"])


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
