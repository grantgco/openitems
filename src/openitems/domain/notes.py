"""Append-only task notes.

Notes are timestamped entries capturing thoughts and updates against a task.
They are deliberately immutable — no edit, no delete — so the chronological
log remains trustworthy. Display order is reverse-chronological (newest first).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from openitems.db.models import Task, TaskNote


def add(session: Session, task: Task, body: str) -> TaskNote:
    body = body.strip()
    if not body:
        raise ValueError("Note body cannot be empty")
    note = TaskNote(body=body, task=task)
    session.add(note)
    session.flush()
    return note


def list_for(task: Task) -> list[TaskNote]:
    return sorted(task.notes, key=lambda n: n.created_at, reverse=True)
