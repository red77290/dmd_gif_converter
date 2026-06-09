import unittest
from unittest.mock import MagicMock
from src.ui.events.event_bus import EventBus, EventType

class TestEventBus(unittest.TestCase):
    def setUp(self):
        # Clear any existing subscribers before each test
        EventBus.clear()

    def tearDown(self):
        EventBus.clear()

    def test_subscribe_and_publish(self):
        mock_handler = MagicMock()
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, mock_handler)
        
        EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED, {"test": "data"})
        
        mock_handler.assert_called_once_with({"test": "data"})

    def test_unsubscribe(self):
        mock_handler = MagicMock()
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, mock_handler)
        EventBus.unsubscribe(EventType.PREVIEW_REFRESH_REQUESTED, mock_handler)
        
        EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED)
        
        mock_handler.assert_not_called()

    def test_publish_without_subscribers(self):
        # Should not raise any exceptions
        try:
            EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED)
        except Exception as e:
            self.fail(f"Publishing to empty topic raised exception: {e}")

    def test_multiple_subscribers(self):
        handler1 = MagicMock()
        handler2 = MagicMock()
        
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, handler1)
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED, handler2)
        
        EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED, "payload")
        
        handler1.assert_called_once_with("payload")
        handler2.assert_called_once_with("payload")

if __name__ == "__main__":
    unittest.main()
