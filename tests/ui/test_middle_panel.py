import unittest
from unittest.mock import MagicMock, patch

class TestMiddlePanelLogic(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app._converted_data = {
            "iid1": {"path": "/fake/path1.mp4", "score": 80},
            "iid2": {"path": "/fake/path2.mp4", "score": 40},
            "iid3": {"path": "/fake/path3.mp4", "score": 20},
        }
        self.app._converted_paths = {"/fake/path1.mp4", "/fake/path2.mp4", "/fake/path3.mp4"}
        self.app._tree_converted = MagicMock()
        self.app._tree_converted.get_children.return_value = ("iid1", "iid2", "iid3")
        self.app._tree_converted.exists.return_value = True
        
        # We need to extract the methods from the mixin to test them independently
        from src.ui.panels.middle import MiddlePanelMixin
        self.clear_converted = MiddlePanelMixin._clear_converted.__get__(self.app)
        self.cleanup_by_score = MiddlePanelMixin._cleanup_by_score.__get__(self.app)

    @patch("src.ui.panels.middle.messagebox")
    def test_clear_converted_cancels_on_no(self, mock_msg):
        mock_msg.askyesno.return_value = False
        
        self.clear_converted()
        
        # Tree and data should remain untouched
        self.app._tree_converted.delete.assert_not_called()
        self.assertEqual(len(self.app._converted_data), 3)

    @patch("src.ui.panels.middle.messagebox")
    def test_clear_converted_success(self, mock_msg):
        mock_msg.askyesno.return_value = True
        
        self.clear_converted()
        
        # Tree should be deleted and data cleared
        self.app._tree_converted.delete.assert_called_with("iid1", "iid2", "iid3")
        self.assertEqual(len(self.app._converted_data), 0)
        self.assertEqual(len(self.app._converted_paths), 0)
        self.assertEqual(self.app._selected_converted_iid, "")
        self.app._update_converted_count.assert_called()
        self.app._update_statistics.assert_called()

    @patch("src.ui.panels.middle.messagebox")
    def test_clear_converted_empty_tree_safe(self, mock_msg):
        # Emulate the empty tree scenario that previously caused a crash
        self.app._tree_converted.get_children.return_value = ()
        mock_msg.askyesno.return_value = True
        
        self.clear_converted()
        
        # Delete should NOT be called if children is empty, to avoid empty unpack exception
        self.app._tree_converted.delete.assert_not_called()
        self.assertEqual(len(self.app._converted_data), 0)

    @patch("os.path.exists")
    @patch("src.ui.panels.middle.messagebox")
    def test_cleanup_by_score_success(self, mock_msg, mock_exists):
        mock_msg.askyesno.return_value = True
        mock_exists.return_value = True
        
        with patch.dict("sys.modules", {"send2trash": None}):
            with patch("os.remove") as mock_remove:
                # We want to remove <= 50 (should remove iid2 and iid3)
                self.cleanup_by_score(50)
                
                # remove should be called for both files AND their sidecars (since exists=True)
                self.assertEqual(mock_remove.call_count, 4)
                
                # Data should be updated
                self.assertIn("iid1", self.app._converted_data)
                self.assertNotIn("iid2", self.app._converted_data)
                self.assertNotIn("iid3", self.app._converted_data)
                self.assertEqual(len(self.app._converted_paths), 1)

    @patch("os.path.exists")
    @patch("src.ui.panels.middle.messagebox")
    def test_cleanup_by_score_file_already_deleted(self, mock_msg, mock_exists):
        mock_msg.askyesno.return_value = True
        # Simulate file not found on disk, so exists returns False
        mock_exists.return_value = False
        
        with patch.dict("sys.modules", {"send2trash": None}):
            with patch("os.remove") as mock_remove:
                # Remove <= 50 (iid2 and iid3)
                self.cleanup_by_score(50)
                
                # remove should not be called since os.path.exists returns False
                mock_remove.assert_not_called()
                
                # BUT the UI elements should still be removed
                self.assertNotIn("iid2", self.app._converted_data)
                self.assertNotIn("iid3", self.app._converted_data)
                self.assertEqual(len(self.app._converted_paths), 1)

    @patch("os.path.exists")
    @patch("src.ui.panels.middle.messagebox")
    def test_cleanup_by_score_safe_delete_exception(self, mock_msg, mock_exists):
        mock_msg.askyesno.return_value = True
        mock_exists.return_value = True
        
        with patch.dict("sys.modules", {"send2trash": None}):
            with patch("os.remove") as mock_remove:
                # Simulate a permission error during delete
                mock_remove.side_effect = Exception("Permission denied")
                
                self.cleanup_by_score(50)
                
                # The exception should be caught, warning logged, but UI should still be cleared
                self.app._log.assert_called()
                self.assertNotIn("iid2", self.app._converted_data)
                self.assertNotIn("iid3", self.app._converted_data)

if __name__ == "__main__":
    unittest.main()
