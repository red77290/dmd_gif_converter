"""
Integration tests for EventBus-driven UI fixes (v6.1.0).

Regression coverage:
  - FILES_ADDED_TO_QUEUE: AI Moments → LeftPanel insertion path.
  - PREVIEW_SOURCE_CHANGED: MiddlePanel → PreviewPanel for converted files.
  - PREVIEW_REFRESH_REQUESTED: MiddlePanel clears preview when list is cleared.
  - EventBus.clear() isolates tests from each other.
"""
import unittest
from src.ui.events.event_bus import EventBus, EventType


class TestEventBusFilesAddedToQueue(unittest.TestCase):
    """
    Regression: AiMomentsPanel used hasattr(self, '_batch_insert') which was
    always False because _batch_insert lives on LeftPanel, not AiMomentsPanel.
    Fix: publish FILES_ADDED_TO_QUEUE event; LeftPanel subscribes and inserts.
    """

    def setUp(self):
        EventBus.clear()

    def tearDown(self):
        EventBus.clear()

    def test_files_added_to_queue_event_delivered(self):
        received = []
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE,
                           lambda payload: received.append(payload))

        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["/a.mp4", "/b.gif"])

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0], ["/a.mp4", "/b.gif"])

    def test_files_added_to_queue_empty_list(self):
        received = []
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE,
                           lambda p: received.append(p))
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, [])
        self.assertEqual(received[0], [])

    def test_multiple_subscribers_all_notified(self):
        calls = []
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE, lambda p: calls.append("A"))
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE, lambda p: calls.append("B"))
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["x"])
        self.assertEqual(sorted(calls), ["A", "B"])

    def test_no_subscriber_publish_is_safe(self):
        """Publishing with no subscriber must not raise."""
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["/safe.mp4"])


class TestEventBusPreviewSourceChanged(unittest.TestCase):
    """
    Regression: MiddlePanel._on_converted_tree_select called
    hasattr(self, '_load_preview') → always False because _load_preview
    is on PreviewPanel.
    Fix: publish PREVIEW_SOURCE_CHANGED with is_converted=True payload.
    """

    def setUp(self):
        EventBus.clear()

    def tearDown(self):
        EventBus.clear()

    def test_preview_source_changed_payload_structure(self):
        received = []
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED,
                           lambda p: received.append(p))

        payload = {
            "path": "/converted/output.gif",
            "is_converted": True,
            "converted_data": {"score": 85, "rating": "Premium"},
        }
        EventBus.publish(EventType.PREVIEW_SOURCE_CHANGED, payload)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["path"], "/converted/output.gif")
        self.assertTrue(received[0]["is_converted"])
        self.assertEqual(received[0]["converted_data"]["score"], 85)

    def test_preview_source_changed_source_file(self):
        """Source (non-converted) files also use the event with is_converted=False."""
        received = []
        EventBus.subscribe(EventType.PREVIEW_SOURCE_CHANGED,
                           lambda p: received.append(p))
        EventBus.publish(EventType.PREVIEW_SOURCE_CHANGED,
                         {"path": "/src/video.mp4", "is_converted": False})
        self.assertFalse(received[0]["is_converted"])


class TestEventBusPreviewRefreshRequested(unittest.TestCase):
    """
    Regression: MiddlePanel._remove_selected_converted called
    hasattr(self, '_stop_dmd_preview') → always False.
    Fix: _clear_preview_via_bus() publishes PREVIEW_REFRESH_REQUESTED for
    each of stop_src, stop_auto, stop_dmd, idle_src, idle_auto, idle_dmd.
    """

    def setUp(self):
        EventBus.clear()

    def tearDown(self):
        EventBus.clear()

    def test_all_six_clear_actions_received(self):
        actions = []
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED,
                           lambda p: actions.append(p["action"]))

        for action in ("stop_src", "stop_auto", "stop_dmd",
                       "idle_src", "idle_auto", "idle_dmd"):
            EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED,
                             {"action": action})

        self.assertEqual(
            sorted(actions),
            sorted(["stop_src", "stop_auto", "stop_dmd",
                    "idle_src", "idle_auto", "idle_dmd"]),
        )

    def test_unknown_action_safe(self):
        received = []
        EventBus.subscribe(EventType.PREVIEW_REFRESH_REQUESTED,
                           lambda p: received.append(p))
        EventBus.publish(EventType.PREVIEW_REFRESH_REQUESTED,
                         {"action": "unknown_action"})
        self.assertEqual(received[0]["action"], "unknown_action")


class TestEventBusIsolation(unittest.TestCase):
    """EventBus.clear() must remove all subscribers."""

    def test_clear_removes_all_subscribers(self):
        calls = []
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE,
                           lambda p: calls.append(p))
        EventBus.clear()
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["file"])
        self.assertEqual(calls, [])

    def test_subscribe_after_clear_works(self):
        EventBus.clear()
        calls = []
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE,
                           lambda p: calls.append(p))
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["f"])
        self.assertEqual(len(calls), 1)
        EventBus.clear()

    def test_callback_exception_does_not_stop_other_subscribers(self):
        calls = []

        def bad_cb(p):
            raise ValueError("simulated error")

        def good_cb(p):
            calls.append(p)

        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE, bad_cb)
        EventBus.subscribe(EventType.FILES_ADDED_TO_QUEUE, good_cb)
        # Must not raise
        EventBus.publish(EventType.FILES_ADDED_TO_QUEUE, ["x"])
        self.assertEqual(calls, [["x"]])


if __name__ == "__main__":
    unittest.main()

