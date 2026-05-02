"""Append-only task notes.

Notes are timestamped entries capturing thoughts and updates against a task.
They are deliberately immutable — no edit, no delete — so the chronological
log remains trustworthy. Display order is reverse-chronological (newest first).

Each note has a ``kind`` (one of ``NOTE_KINDS``) to classify the touchpoint —
call / email / meeting / decision / generic update — so a long note log
stays scannable.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openitems.db.models import Engagement, Task, TaskNote

NOTE_KINDS: tuple[str, ...] = (
    "update",
    "call",
    "email",
    "meeting",
    "decision",
)
DEFAULT_KIND = "update"

# Single-char glyphs used in inline rendering. Plain ASCII fallbacks keep
# narrow-terminal users sane; the glyphs themselves are BMP characters that
# render across modern macOS / Linux / Windows terminals.
KIND_GLYPHS: dict[str, str] = {
    "update": "·",
    "call": "☎",
    "email": "✉",
    "meeting": "◇",
    "decision": "★",
}


def add(
    session: Session,
    task: Task,
    body: str,
    *,
    kind: str = DEFAULT_KIND,
) -> TaskNote:
    body = body.strip()
    if not body:
        raise ValueError("Note body cannot be empty")
    if kind not in NOTE_KINDS:
        raise ValueError(f"Note kind must be one of {NOTE_KINDS}, got {kind!r}")
    note = TaskNote(body=body, kind=kind, task=task)
    session.add(note)
    session.flush()
    return note


def list_for(task: Task) -> list[TaskNote]:
    return sorted(task.notes, key=lambda n: n.created_at, reverse=True)


def list_for_engagement(
    session: Session, engagement: Engagement
) -> list[TaskNote]:
    """All notes across all non-deleted tasks in the engagement, newest first.

    The parent ``task`` relationship is eager-loaded so callers can render
    ``note.task.name`` without an additional query per row.
    """
    stmt = (
        select(TaskNote)
        .join(Task, Task.id == TaskNote.task_id)
        .where(Task.engagement_id == engagement.id)
        .where(Task.deleted_at.is_(None))
        .options(selectinload(TaskNote.task))
        .order_by(TaskNote.created_at.desc())
    )
    return list(session.scalars(stmt))


def cycle_kind(current: str, *, direction: int = 1) -> str:
    """Return the next/previous kind in NOTE_KINDS, wrapping around."""
    if current not in NOTE_KINDS:
        return DEFAULT_KIND
    idx = (NOTE_KINDS.index(current) + direction) % len(NOTE_KINDS)
    return NOTE_KINDS[idx]


def glyph_for(kind: str) -> str:
    return KIND_GLYPHS.get(kind, KIND_GLYPHS[DEFAULT_KIND])
