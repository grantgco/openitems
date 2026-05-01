from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openitems.db.models import Bucket, Engagement, Task
from openitems.domain.constants import PRIORITIES, STATUSES
from openitems.domain.text import clean_text, join_labels


@dataclass
class TaskInput:
    name: str
    description: str = ""
    priority: str = "Medium"
    status: str = "Not Started"
    assigned_to: str = ""
    start_date: date | None = None
    due_date: date | None = None
    labels: list[str] | None = None
    bucket_name: str | None = None


def is_completed(task: Task) -> bool:
    """A task is completed if its bucket is a done-state bucket.

    Bucket is the workflow primary signal — `status` mirrors it (and is kept
    in sync by ``_sync_status_with_bucket``) so the existing `.xlsx` exporter,
    which filters on `status=='Completed'`, keeps working.
    """
    if task.bucket is not None and task.bucket.is_done_state:
        return True
    return task.status == "Completed"


def is_late(task: Task, today: date | None = None) -> bool:
    """Late = has due date in the past and not in a done state.

    Mirrors `modOpenItemsList.bas:180-184` (the in-the-past branch).
    Computed every read; never persisted.
    """
    if is_completed(task):
        return False
    if task.due_date is None:
        return False
    today = today or date.today()
    return task.due_date < today


def list_for(
    session: Session,
    engagement: Engagement,
    *,
    include_completed: bool = True,
    include_deleted: bool = False,
) -> list[Task]:
    stmt = select(Task).where(Task.engagement_id == engagement.id)
    if not include_deleted:
        stmt = stmt.where(Task.deleted_at.is_(None))
    stmt = stmt.order_by(Task.created_at.asc())
    rows = list(session.scalars(stmt))
    if include_completed:
        return rows
    return [t for t in rows if not is_completed(t)]


def _validate(input: TaskInput) -> None:
    if not input.name.strip():
        raise ValueError("Task name cannot be empty")
    if input.priority not in PRIORITIES:
        raise ValueError(f"Priority must be one of {PRIORITIES}")
    if input.status not in STATUSES:
        raise ValueError(f"Status must be one of {STATUSES}")


def _sync_status_with_bucket(task: Task) -> None:
    """Keep ``task.status`` consistent with the workflow stage.

    - Bucket is a done-state → status = "Completed"
    - Otherwise: leave existing status unless it was "Completed" (then bump to
      "In Progress" so the export and overdue logic don't trip).
    """
    if task.bucket is not None and task.bucket.is_done_state:
        task.status = "Completed"
    elif task.status == "Completed":
        task.status = "In Progress"


def create(session: Session, engagement: Engagement, input: TaskInput) -> Task:
    from openitems.domain import buckets as buckets_mod

    _validate(input)
    bucket: Bucket | None = None
    if input.bucket_name:
        bucket = buckets_mod.get_or_create(session, engagement, input.bucket_name)
    elif engagement.buckets:
        bucket = sorted(engagement.buckets, key=lambda b: b.sort_order)[0]

    task = Task(
        engagement_id=engagement.id,
        bucket_id=bucket.id if bucket else None,
        bucket=bucket,
        name=input.name.strip(),
        description=clean_text(input.description),
        priority=input.priority,
        status=input.status,
        assigned_to=input.assigned_to.strip(),
        start_date=input.start_date,
        due_date=input.due_date,
        labels=join_labels(input.labels or []),
    )
    _sync_status_with_bucket(task)
    session.add(task)
    session.flush()
    return task


def update(session: Session, task: Task, **changes: object) -> Task:
    if "name" in changes:
        name = str(changes["name"]).strip()
        if not name:
            raise ValueError("Task name cannot be empty")
        task.name = name
    if "description" in changes:
        task.description = clean_text(str(changes["description"]))
    if "priority" in changes:
        priority = str(changes["priority"])
        if priority not in PRIORITIES:
            raise ValueError(f"Priority must be one of {PRIORITIES}")
        task.priority = priority
    if "status" in changes:
        status = str(changes["status"])
        if status not in STATUSES:
            raise ValueError(f"Status must be one of {STATUSES}")
        task.status = status
    if "assigned_to" in changes:
        task.assigned_to = str(changes["assigned_to"]).strip()
    if "start_date" in changes:
        task.start_date = changes["start_date"]  # type: ignore[assignment]
    if "due_date" in changes:
        task.due_date = changes["due_date"]  # type: ignore[assignment]
    if "labels" in changes:
        labels_val = changes["labels"]
        if isinstance(labels_val, str):
            task.labels = labels_val
        else:
            task.labels = join_labels(list(labels_val))  # type: ignore[arg-type]
    if "bucket_id" in changes:
        new_bucket_id = changes["bucket_id"]
        task.bucket_id = new_bucket_id  # type: ignore[assignment]
        task.bucket = (
            session.get(Bucket, new_bucket_id) if new_bucket_id else None
        )
    _sync_status_with_bucket(task)
    return task


def advance_bucket(session: Session, task: Task) -> Task:
    """Move ``task`` to the next workflow stage.

    Used by the `s` keybinding in the TUI. If the task is already in the
    last bucket, it stays put.
    """
    from openitems.domain import buckets as buckets_mod

    next_bucket = buckets_mod.next_in_workflow(session, task.engagement, task.bucket)
    if next_bucket is None or (task.bucket and next_bucket.id == task.bucket.id):
        return task
    task.bucket_id = next_bucket.id
    task.bucket = next_bucket
    _sync_status_with_bucket(task)
    return task


def soft_delete(session: Session, task: Task) -> None:
    task.deleted_at = datetime.now(UTC).replace(tzinfo=None)


def restore(session: Session, task: Task) -> None:
    task.deleted_at = None


def overdue_count(tasks: Iterable[Task], today: date | None = None) -> int:
    today = today or date.today()
    return sum(1 for t in tasks if is_late(t, today))


def high_priority_count(tasks: Iterable[Task]) -> int:
    return sum(1 for t in tasks if t.priority in {"Important", "Urgent"})


def completed_checks(task: Task) -> int:
    return sum(1 for c in task.checklist_items if c.completed and c.deleted_at is None)


def total_checks(task: Task) -> int:
    return sum(1 for c in task.checklist_items if c.deleted_at is None)


def progress_summary(tasks: Iterable[Task]) -> tuple[int, int]:
    """Return ``(done, total)`` across the iterable, counting bucket-driven done."""
    items = list(tasks)
    done = sum(1 for t in items if is_completed(t))
    return done, len(items)
