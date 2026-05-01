"""Tiny in-process undo stack.

Tracks the last destructive action (soft-delete) so the user can `u`-undo it.
We deliberately keep this in memory: it resets each session, doesn't try to
undo edits, and doesn't try to be a full audit log. Out of scope creep.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from openitems.db.models import Task


@dataclass
class UndoAction:
    description: str
    apply: Callable[[Session], None]


class UndoStack:
    def __init__(self, capacity: int = 32) -> None:
        self._stack: deque[UndoAction] = deque(maxlen=capacity)

    def push(self, action: UndoAction) -> None:
        self._stack.append(action)

    def pop(self) -> UndoAction | None:
        return self._stack.pop() if self._stack else None

    def peek(self) -> UndoAction | None:
        return self._stack[-1] if self._stack else None

    def __len__(self) -> int:
        return len(self._stack)


def make_restore_task(task_id: str, name: str) -> UndoAction:
    def _restore(session: Session) -> None:
        task = session.get(Task, task_id)
        if task is not None:
            task.deleted_at = None

    return UndoAction(description=f"Restore '{name}'", apply=_restore)
