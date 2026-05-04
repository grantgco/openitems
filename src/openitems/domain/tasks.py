from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openitems.db.models import Bucket, Engagement, Task
from openitems.domain.constants import PRIORITIES, STATUSES
from openitems.domain.text import clean_text, join_labels


@dataclass
class TaskInput:
    name: str
    description: str = ""
    priority: str = "Medium"
    status: str = "Intake"
    assigned_to: str = ""
    start_date: date | None = None
    due_date: date | None = None
    labels: list[str] | None = None
    bucket_name: str | None = None


_DONE_STATUSES = frozenset({"Dropped", "Resolved", "Closed"})


def is_completed(task: Task) -> bool:
    """A task is completed if its bucket is a done-state bucket.

    Bucket is the workflow primary signal — `status` mirrors it (and is kept
    in sync by ``_sync_status_with_bucket``).
    """
    if task.bucket is not None and task.bucket.is_done_state:
        return True
    return task.status in _DONE_STATUSES


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
    stmt = (
        select(Task)
        .where(Task.engagement_id == engagement.id)
        .options(
            selectinload(Task.notes),
            selectinload(Task.checklist_items),
            selectinload(Task.bucket),
        )
    )
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


_NON_DONE_NAME_HINTS: tuple[str, ...] = ("Intake", "In Progress", "Deferred")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _sync_status_with_bucket(task: Task) -> None:
    """Keep ``task.status`` consistent with the workflow stage and stamp/clear
    ``resolved_at`` when crossing into or out of an auto-close bucket.

    Bucket flags drive the status string:
      - ``auto_close_after_days`` set → "Resolved" (stamp ``resolved_at`` if null)
      - ``is_done_state`` and bucket name is "Dropped" → "Dropped"
      - ``is_done_state`` otherwise → "Closed"
      - non-done bucket whose name matches a known status verbatim → that name
      - otherwise: keep status if still in STATUSES, else reset to "In Progress"
    """
    bucket = task.bucket
    if bucket is not None and bucket.auto_close_after_days is not None:
        task.status = "Resolved"
        if task.resolved_at is None:
            task.resolved_at = _utcnow()
        return

    # Anywhere else: leaving (or never entering) a hold bucket clears the stamp.
    task.resolved_at = None

    if bucket is not None and bucket.is_done_state:
        task.status = "Dropped" if bucket.name.strip().lower() == "dropped" else "Closed"
        return

    if bucket is not None:
        match = bucket.name.strip().lower()
        for hint in _NON_DONE_NAME_HINTS:
            if hint.lower() == match:
                task.status = hint
                return

    if task.status not in STATUSES:
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


def toggle_focus(
    session: Session, task: Task, *, today: date | None = None
) -> Task:
    """Stamp the task with the current week's Monday, or clear it.

    Used by the F (focus) keybind to mark which tasks matter this week.
    The "this week" filter (TaskFilter.focus_only) shows only tasks whose
    ``focus_week`` equals the start of the current ISO week, so a stamp
    expires automatically once the week rolls over.
    """
    from openitems.domain.dates import start_of_week

    today = today or date.today()
    monday = start_of_week(today)
    task.focus_week = None if task.focus_week == monday else monday
    session.flush()
    return task


def move_to_engagement(
    session: Session, task: Task, target: Engagement
) -> Task:
    """Move ``task`` to ``target`` engagement, landing in target's Backlog.

    Why Backlog: the task's existing ``bucket_id`` belongs to the source
    engagement and is meaningless in the new one. Picking the first
    workflow stage of the target ("Backlog" by seed convention) keeps the
    task visible and lets the user advance it the usual way.

    No-op when target is already the task's engagement.
    """
    from openitems.domain import buckets as buckets_mod

    if task.engagement_id == target.id:
        return task
    target_buckets = buckets_mod.list_for(session, target)
    landing = next(iter(target_buckets), None)
    task.engagement_id = target.id
    task.bucket_id = landing.id if landing else None
    task.bucket = landing
    _sync_status_with_bucket(task)
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
    if "external_url" in changes:
        from openitems.domain.text import normalize_url

        raw = changes["external_url"]
        task.external_url = normalize_url(str(raw) if raw is not None else None)
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


def sweep_auto_close(
    session: Session,
    engagement: Engagement,
    *,
    now: datetime | None = None,
) -> int:
    """Promote tasks past their hold window to the next workflow stage.

    Looks for live tasks in any bucket with ``auto_close_after_days`` set,
    where ``resolved_at + days`` is in the past, and advances each via
    ``advance_bucket``. Returns the number promoted. Idempotent.
    """
    from openitems.domain import buckets as buckets_mod

    now = now or _utcnow()
    stmt = (
        select(Task)
        .join(Bucket, Task.bucket_id == Bucket.id)
        .where(
            Task.engagement_id == engagement.id,
            Task.deleted_at.is_(None),
            Bucket.auto_close_after_days.is_not(None),
            Task.resolved_at.is_not(None),
        )
        .options(selectinload(Task.bucket))
    )
    promoted = 0
    for task in session.scalars(stmt):
        bucket = task.bucket
        if bucket is None or bucket.auto_close_after_days is None or task.resolved_at is None:
            continue
        if task.resolved_at + timedelta(days=bucket.auto_close_after_days) > now:
            continue
        next_bucket = buckets_mod.next_in_workflow(session, engagement, bucket)
        if next_bucket is None or next_bucket.id == bucket.id:
            continue
        task.bucket_id = next_bucket.id
        task.bucket = next_bucket
        _sync_status_with_bucket(task)
        promoted += 1
    if promoted:
        session.flush()
    return promoted


def soft_delete(session: Session, task: Task) -> None:
    task.deleted_at = datetime.now(UTC).replace(tzinfo=None)


def restore(session: Session, task: Task) -> None:
    task.deleted_at = None


def overdue_count(tasks: Iterable[Task], today: date | None = None) -> int:
    today = today or date.today()
    return sum(1 for t in tasks if is_late(t, today))


def high_priority_count(tasks: Iterable[Task]) -> int:
    return sum(1 for t in tasks if t.priority in {"Important", "Urgent"})


def auto_close_at(task: Task) -> datetime | None:
    """Return the moment a Resolved task will auto-promote, or None."""
    bucket = task.bucket
    if (
        bucket is None
        or bucket.auto_close_after_days is None
        or task.resolved_at is None
    ):
        return None
    return task.resolved_at + timedelta(days=bucket.auto_close_after_days)


def completed_checks(task: Task) -> int:
    return sum(1 for c in task.checklist_items if c.completed and c.deleted_at is None)


def total_checks(task: Task) -> int:
    return sum(1 for c in task.checklist_items if c.deleted_at is None)


def progress_summary(tasks: Iterable[Task]) -> tuple[int, int]:
    """Return ``(done, total)`` across the iterable, counting bucket-driven done."""
    items = list(tasks)
    done = sum(1 for t in items if is_completed(t))
    return done, len(items)
