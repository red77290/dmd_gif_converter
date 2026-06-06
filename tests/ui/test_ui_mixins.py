import unittest
from unittest.mock import MagicMock, patch

with patch("customtkinter.set_appearance_mode"), patch("customtkinter.set_default_color_theme"):
    from src.ui.app import DMDConverterApp

class TestLeftPanelLogic(unittest.TestCase):
    @patch("src.ui.panels.left.filedialog")
    @patch("src.ui.panels.left.messagebox")
    def test_add_files_duplicate_handling(self, mock_msg, mock_fd):
        app = MagicMock()
        app._file_paths = {"/mock/path1.mp4"}
        app._file_data = {"item1": "/mock/path1.mp4"}
        
        # Test adding a duplicate file
        mock_fd.askopenfilenames.return_value = ("/mock/path1.mp4",)
        
        from src.ui.panels.left import LeftPanelMixin
        LeftPanelMixin.add_files(app)
        
        # Should not be added to tree
        app.tree.insert.assert_not_called()

class TestSettingsLogic(unittest.TestCase):
    def test_let_me_handle_it_toggle(self):
        app = MagicMock()
        app.v_let_me_handle_it = MagicMock()
        app.v_let_me_handle_it.get.return_value = True
        
        app.v_auto_color_enabled = MagicMock()
        app.v_auto_action_enabled = MagicMock()
        app.v_action_smart_auto_crop = MagicMock()
        app.v_bg_sub_enable = MagicMock()
        app.v_dmd_visibility_score_enabled = MagicMock()
        
        app._lmh_widgets = [MagicMock(), MagicMock()]
        app._lmh_saved_state = {}
        
        from src.ui.panels.settings import SettingsPanelMixin
        SettingsPanelMixin._on_let_me_handle_toggle(app)
        
        app.v_auto_color_enabled.set.assert_called_with(True)
        app.v_auto_action_enabled.set.assert_called_with(True)
        app.v_action_smart_auto_crop.set.assert_called_with(True)
        app.v_dmd_visibility_score_enabled.set.assert_called_with(True)
        
        for w in app._lmh_widgets:
            w.configure.assert_called_with(state="disabled")

if __name__ == "__main__":
    unittest.main()
