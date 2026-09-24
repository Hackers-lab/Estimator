"""
canvas/history_manager.py
=========================
Manages undo/redo snapshot history for the CAD canvas.
"""
from __future__ import annotations
from typing import Any, Callable

class CanvasHistoryManager:
    """Encapsulates the canvas undo/redo stack."""

    def __init__(
        self,
        get_state_fn: Callable[[], dict],
        apply_state_fn: Callable[[dict, bool], None],
        max_history: int = 50
    ):
        self._get_state = get_state_fn
        self._apply_state = apply_state_fn
        self.max_history = max_history
        self.history: list[dict] = []
        self.history_index: int = -1
        self._is_undoing: bool = False

    @property
    def is_undoing(self) -> bool:
        return self._is_undoing

    @property
    def can_undo(self) -> bool:
        return self.history_index > 0

    @property
    def can_redo(self) -> bool:
        return self.history_index < len(self.history) - 1

    def push(self) -> bool:
        """Capture current state and push onto undo stack. Returns True if a state was pushed."""
        if self._is_undoing:
            return False

        state = self._get_state()

        # Don't push identical consecutive states
        if self.history and self.history_index >= 0:
            if state == self.history[self.history_index]:
                return False

        # Truncate redo future if actions were performed
        self.history = self.history[:self.history_index + 1]
        self.history.append(state)

        if len(self.history) > self.max_history:
            self.history.pop(0)
        else:
            self.history_index += 1
        return True

    def undo(self) -> bool:
        """Step backward in history."""
        if self.can_undo:
            self.history_index -= 1
            self._is_undoing = True
            try:
                self._apply_state(self.history[self.history_index], False)
            finally:
                self._is_undoing = False
            return True
        return False

    def redo(self) -> bool:
        """Step forward in history."""
        if self.can_redo:
            self.history_index += 1
            self._is_undoing = True
            try:
                self._apply_state(self.history[self.history_index], False)
            finally:
                self._is_undoing = False
            return True
        return False

    def clear(self) -> None:
        """Clear the undo/redo stack."""
        self.history.clear()
        self.history_index = -1
        self._is_undoing = False
