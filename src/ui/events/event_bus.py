import logging
from enum import Enum, auto
from typing import Callable, Dict, List, Any

logger = logging.getLogger("EventBus")

class EventType(Enum):
    # Preview Events
    PREVIEW_REFRESH_REQUESTED = auto()
    PREVIEW_SOURCE_CHANGED = auto()
    
    # Selection Events
    SELECTION_CHANGED = auto()
    FILES_ADDED_TO_QUEUE = auto()
    FILE_REMOVED_FROM_QUEUE = auto()
    
    # Settings Events
    SETTINGS_CHANGED = auto()
    GLOBAL_CONFIG_TOGGLED = auto()
    
    # AI Moments Events
    AI_MOMENT_EXTRACTION_STARTED = auto()
    AI_MOMENT_EXTRACTION_FINISHED = auto()
    
    # Conversion Events
    CONVERSION_STARTED = auto()
    CONVERSION_FINISHED = auto()
    CONVERSION_PROGRESS = auto()

class EventBus:
    """
    A simple synchronous Event Bus for decoupling UI components.
    """
    _subscribers: Dict[EventType, List[Callable[[Any], None]]] = {}

    @classmethod
    def subscribe(cls, event_type: EventType, callback: Callable[[Any], None]) -> None:
        if event_type not in cls._subscribers:
            cls._subscribers[event_type] = []
        if callback not in cls._subscribers[event_type]:
            cls._subscribers[event_type].append(callback)

    @classmethod
    def unsubscribe(cls, event_type: EventType, callback: Callable[[Any], None]) -> None:
        if event_type in cls._subscribers and callback in cls._subscribers[event_type]:
            cls._subscribers[event_type].remove(callback)

    @classmethod
    def publish(cls, event_type: EventType, payload: Any = None) -> None:
        if event_type in cls._subscribers:
            for callback in cls._subscribers[event_type]:
                try:
                    callback(payload)
                except Exception as e:
                    logger.error("Error in event callback for %s: %s", event_type, e, exc_info=True)

    @classmethod
    def clear(cls) -> None:
        """Clear all subscribers (useful for testing or full reset)."""
        cls._subscribers.clear()
