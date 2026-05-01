from __future__ import annotations

from sqlalchemy.orm import Session

from openitems.db.models import ChecklistItem, Task


def add(session: Session, task: Task, text: str, *, completed: bool = False) -> ChecklistItem:
    text = text.strip()
    if not text:
        raise ValueError("Checklist item text cannot be empty")
    next_order = max((c.sort_order for c in task.checklist_items), default=-1) + 1
    item = ChecklistItem(
        task_id=task.id, text=text, completed=completed, sort_order=next_order
    )
    session.add(item)
    task.checklist_items.append(item)
    session.flush()
    return item


def toggle(session: Session, item: ChecklistItem) -> ChecklistItem:
    item.completed = not item.completed
    return item


def remove(session: Session, item: ChecklistItem) -> None:
    session.delete(item)


def reorder(session: Session, task: Task, ordered_ids: list[str]) -> None:
    by_id = {c.id: c for c in task.checklist_items}
    for idx, cid in enumerate(ordered_ids):
        if cid in by_id:
            by_id[cid].sort_order = idx
