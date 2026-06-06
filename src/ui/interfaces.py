"""
Abstract contracts for the Model-View-Controller (MVC) pattern used in the UI.
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional


class IModel(ABC):
    """Base contract for data models — holds application state."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Return a setting value by key."""
        pass

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Update a setting value."""
        pass

    @abstractmethod
    def snapshot(self) -> Dict[str, Any]:
        """Return a full copy of the current state."""
        pass

    @abstractmethod
    def restore(self, state: Dict[str, Any]) -> None:
        """Restore state from a snapshot dict."""
        pass


class IView(ABC):
    """Base contract for UI views — displays data, emits events."""

    @abstractmethod
    def build(self) -> None:
        """Construct and lay out all widgets."""
        pass

    @abstractmethod
    def update(self) -> None:
        """Refresh the view to reflect the current model state."""
        pass


class IController(ABC):
    """Base contract for controllers — orchestrates model ↔ view interactions."""

    @abstractmethod
    def bind(self, view: IView, model: IModel) -> None:
        """Connect the controller to its view and model."""
        pass

    @abstractmethod
    def on_action(self, action: str, payload: Any = None) -> None:
        """Handle a user action dispatched from the view."""
        pass


class IPanel(ABC):
    """Contract for an individual UI panel widget."""

    @abstractmethod
    def build(self, parent) -> Any:
        """Build the panel, attach it to the parent widget, and return the root frame."""
        pass

    @abstractmethod
    def refresh(self) -> None:
        """Update the panel to reflect current state."""
        pass
