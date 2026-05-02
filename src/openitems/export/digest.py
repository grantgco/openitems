"""Markdown handoff digest — client-facing status summary.

The existing `.xlsx` exporter (``workbook.py``) is a *workplan* — a port of
the original VBA macro that dumps every open task with its checklist. For a
weekly client email or end-of-day summary you want a different shape:
counts, what shipped, what's still open, and recent activity.

Markdown is the right format: it pastes cleanly into Gmail / Slack / Notion
/ Linear, and renders to plain text in plain text contexts.

This module is a pure function — no I/O. The caller (``cli.py`` or the TUI
``MainScreen`` ``D`` keybind) is responsible for fetching data and writing
the output to disk.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from openitems.db.models import Engagement, Task, TaskNote
from openitems.domain import notes as notes_mod
from openitems.domain.constants import HIGH_PRIORITIES, PRIORITY_RANK
from openitems.domain.tasks import is_completed, is_late
from openitems.domain.text import parse_labels


def render_digest(
    engagement: Engagement,
    all_tasks: Iterable[Task],
    all_notes: Iterable[TaskNote],
    *,
    since: date,
    until: date,
    today: date,
) -> str:
    """Build a Markdown digest for ``engagement`` covering ``since``..``until``.

    ``all_tasks`` should be the full list (including completed) and
    ``all_notes`` the full activity feed for the engagement (newest-first).
    Filtering by date range happens here so the function stays a pure
    transformation suitable for unit tests.

    The result is a multi-section document:
        # Acme Co — Apr 28 to May 5
        **Status:** 12 open · 2 overdue · 3 high-priority

        ## Completed (3)
        ## Overdue (2)
        ## In progress (5)
        ## Activity (14 notes)
    """
    tasks_list = [t for t in all_tasks if t.deleted_at is None]
    notes_list = list(all_notes)

    open_tasks = [t for t in tasks_list if not is_completed(t)]
    overdue = [t for t in open_tasks if is_late(t, today)]
    high_priority = [t for t in open_tasks if t.priority in HIGH_PRIORITIES]

    # Heuristic: completed-in-range = currently in a done-state bucket AND
    # task's updated_at falls inside the window. Without a persisted audit
    # log we can't track *when* the bucket transition happened — `updated_at`
    # is the closest proxy. F10 (audit log persistence) would tighten this.
    completed_in_range = [
        t
        for t in tasks_list
        if is_completed(t)
        and t.updated_at is not None
        and since <= t.updated_at.date() <= until
    ]

    activity_in_range = [
        n for n in notes_list if since <= n.created_at.date() <= until
    ]

    out: list[str] = []
    out.append(f"# {engagement.name} — {_format_range(since, until)}")
    out.append("")
    out.append(
        f"**Status:** {len(open_tasks)} open · "
        f"{len(overdue)} overdue · "
        f"{len(high_priority)} high-priority"
    )
    out.append("")

    if completed_in_range:
        out.append(f"## Completed ({len(completed_in_range)})")
        for t in sorted(
            completed_in_range,
            key=lambda x: x.updated_at or x.created_at,
            reverse=True,
        ):
            out.extend(_render_task_bullet(t, with_last_note=True))
        out.append("")

    if overdue:
        out.append(f"## Overdue ({len(overdue)})")
        for t in sorted(overdue, key=lambda x: x.due_date or date.max):
            assigned = f" ({t.assigned_to})" if t.assigned_to else ""
            due = t.due_date.strftime("%m-%d") if t.due_date else "—"
            out.append(f"- **{t.name}**{assigned} — was due {due}")
        out.append("")

    in_progress = [t for t in open_tasks if t not in overdue]
    if in_progress:
        out.append(f"## In progress ({len(in_progress)})")
        for t in sorted(
            in_progress,
            key=lambda x: (-PRIORITY_RANK.get(x.priority, 0), x.name.lower()),
        ):
            out.extend(_render_task_bullet(t, with_last_note=True))
        out.append("")

    if activity_in_range:
        out.append(f"## Activity ({len(activity_in_range)} notes)")
        out.extend(_render_activity(activity_in_range))
        out.append("")

    if not (completed_in_range or overdue or in_progress or activity_in_range):
        out.append("_No activity in this range._")
        out.append("")

    return "\n".join(out).rstrip() + "\n"


# ── helpers ──────────────────────────────────────────────────────────────


def _render_task_bullet(t: Task, *, with_last_note: bool) -> list[str]:
    """One-or-two-line Markdown bullet for a task. Optional last-note quote."""
    pieces = [f"- **{t.name}**"]
    if t.assigned_to:
        pieces.append(f" ({t.assigned_to})")
    tags = parse_labels(t.labels)
    if tags:
        pieces.append("  " + " ".join(f"`{tag}`" for tag in tags))
    out = ["".join(pieces)]
    if with_last_note:
        recent = next(iter(notes_mod.list_for(t)), None)
        if recent is not None:
            glyph = notes_mod.glyph_for(recent.kind)
            preview = recent.body.replace("\n", " ").strip()
            if len(preview) > 120:
                preview = preview[:119] + "…"
            stamp = recent.created_at.strftime("%Y-%m-%d")
            out.append(f"  > {glyph} {stamp}: {preview}")
    return out


def _render_activity(notes_iter: Iterable[TaskNote]) -> list[str]:
    """Render a flat chronological activity feed."""
    rendered: list[str] = []
    for n in notes_iter:
        glyph = notes_mod.glyph_for(n.kind)
        stamp = n.created_at.strftime("%a %b %d")
        task_name = n.task.name if n.task is not None else "(unknown task)"
        body = n.body.replace("\n", " ").strip()
        rendered.append(f"- {stamp} {glyph} **{task_name}** — {body}")
    return rendered


def _format_range(since: date, until: date) -> str:
    if since == until:
        return since.strftime("%b %-d, %Y")
    if since.year == until.year:
        return f"{since.strftime('%b %-d')} to {until.strftime('%b %-d, %Y')}"
    return f"{since.strftime('%b %-d, %Y')} to {until.strftime('%b %-d, %Y')}"
