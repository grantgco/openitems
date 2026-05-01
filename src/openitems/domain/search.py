from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz

from openitems.db.models import Task
from openitems.domain.tasks import is_late
from openitems.domain.text import parse_labels


@dataclass
class TaskFilter:
    bucket_name: str | None = None
    tags: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    priorities: tuple[str, ...] = ()
    assignee: str | None = None
    overdue_only: bool = False
    unassigned_only: bool = False
    text: str = ""
    fuzzy_threshold: int = 60
    today: date | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


def _matches_text(task: Task, query: str, threshold: int) -> bool:
    if not query:
        return True
    haystack = f"{task.name} {task.description} {task.labels}"
    return fuzz.partial_ratio(query.lower(), haystack.lower()) >= threshold


def _has_any_tag(task: Task, tags: Iterable[str]) -> bool:
    if not tags:
        return True
    task_tags = {t.lower() for t in parse_labels(task.labels)}
    return any(tag.lower() in task_tags for tag in tags)


def apply(filter: TaskFilter, tasks: Iterable[Task]) -> list[Task]:
    today = filter.today or date.today()
    out: list[Task] = []
    for t in tasks:
        if filter.bucket_name is not None:
            if not t.bucket or t.bucket.name != filter.bucket_name:
                continue
        if not _has_any_tag(t, filter.tags):
            continue
        if filter.statuses and t.status not in filter.statuses:
            continue
        if filter.priorities and t.priority not in filter.priorities:
            continue
        if filter.assignee and t.assigned_to.lower() != filter.assignee.lower():
            continue
        if filter.overdue_only and not is_late(t, today):
            continue
        if filter.unassigned_only and t.assigned_to.strip():
            continue
        if filter.has_text and not _matches_text(t, filter.text, filter.fuzzy_threshold):
            continue
        out.append(t)
    return out
