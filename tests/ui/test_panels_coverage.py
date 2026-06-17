import pytest
from src.ui.app import DMDConverterApp
from src.ui.panels.left_panel import LeftPanel
from src.ui.panels.middle_panel import MiddlePanel
from src.ui.panels.ai_moments_panel import AiMomentsPanel
from src.ui.preview.preview_panel import PreviewPanel
from src.ui.panels.log_console import LogConsole

def test_panels_coverage():
    assert hasattr(LeftPanel, 'add_files')
    assert hasattr(MiddlePanel, 'browse_output')
    assert hasattr(AiMomentsPanel, '_ai_select_video')
    assert hasattr(PreviewPanel, '_on_source_changed')
    assert hasattr(LogConsole, 'clear_log')
