from __future__ import annotations

from datetime import UTC, date, datetime

import humanize
from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, Static

from openitems.db.models import Task
from openitems.domain import notes as notes_mod
from openitems.domain.tasks import completed_checks, is_late, total_checks
from openitems.tui import palette
from openitems.tui.widgets.task_format import format_date, format_priority, format_tags

_MAX_NOTES_IN_DETAIL = 3
_NOTE_PREVIEW_CHARS = 60


class DetailPane(Vertical):
    """Right pane: title + labelled fields + description + checklist."""

    class ChecklistToggled(Message):
        def __init__(self, item_id: str) -> None:
            self.item_id = item_id
            super().__init__()

    def __init__(self) -> None:
        super().__init__(id="detail-pane", classes="pane")
        self._title = Label("[b]detail[/b]")
        self._body = Static("", id="detail-body")
        self._current_task: Task | None = None

    def compose(self) -> ComposeResult:
        yield self._title
        yield self._body

    def show_empty(self) -> None:
        self._current_task = None
        self._title.update("[b]detail[/b]")
        self._body.update(Text("nothing selected", style=palette.DIM))

    def show_task(self, task: Task | None, *, today: date | None = None) -> None:
        if task is None:
            self.show_empty()
            return
        self._current_task = task
        today = today or date.today()
        late = is_late(task, today)

        self._title.update(Text(task.name, style=f"bold {palette.ACCENT}"))

        rows: list[Text | Group] = []
        bucket_label = task.bucket.name if task.bucket else "—"
        if task.bucket and task.bucket.is_done_state:
            bucket_text = Text(bucket_label, style=f"bold {palette.GREEN}")
        else:
            bucket_text = Text(bucket_label, style=palette.FG)
        rows.append(_field_text("stage", bucket_text))
        rows.append(_field_text("tags", format_tags(task.labels) if task.labels else Text("—", style=palette.DIM)))
        rows.append(_field_text("priority", format_priority(task.priority)))
        rows.append(_field("assigned", task.assigned_to or "—"))
        rows.append(_field_text("start", format_date(task.start_date)))

        due_text = format_date(task.due_date)
        if late:
            due_text = Text.assemble(due_text, Text("  (overdue)", style=f"bold {palette.RED}"))
        rows.append(_field_text("due", due_text))

        rows.append(Text(""))
        rows.append(Text("─ description ──────────────", style=palette.DIM))
        if task.description:
            rows.append(Text(task.description, style=palette.FG))
        else:
            rows.append(Text("—", style=palette.DIM))

        checks = [c for c in task.checklist_items if c.deleted_at is None]
        if checks:
            done = completed_checks(task)
            total = total_checks(task)
            rows.append(Text(""))
            rows.append(
                Text(f"─ checklist  {done}/{total} ───────────", style=palette.DIM)
            )
            for c in checks:
                marker = Text("[x]  ", style=palette.GREEN) if c.completed else Text("[ ]  ", style=palette.DIM)
                rows.append(Text.assemble(marker, Text(c.text, style=palette.FG if c.completed else palette.DIM)))

        recent_notes = notes_mod.list_for(task)
        rows.append(Text(""))
        if recent_notes:
            now = datetime.now(UTC).replace(tzinfo=None)
            shown = recent_notes[:_MAX_NOTES_IN_DETAIL]
            header_suffix = (
                f"  ({len(recent_notes)})"
                if len(recent_notes) > _MAX_NOTES_IN_DETAIL
                else ""
            )
            rows.append(
                Text(f"─ notes{header_suffix}  (n to add) ──────", style=palette.DIM)
            )
            for n in shown:
                relative = humanize.naturaltime(now - n.created_at)
                preview = n.body.replace("\n", " | ")
                if len(preview) > _NOTE_PREVIEW_CHARS:
                    preview = preview[: _NOTE_PREVIEW_CHARS - 1] + "…"
                glyph = notes_mod.glyph_for(n.kind)
                rows.append(
                    Text.assemble(
                        Text(f"{glyph}  ", style=palette.ACCENT),
                        Text(relative, style=palette.DIM),
                        Text("  ·  ", style=palette.DIM),
                        Text(preview, style=palette.FG),
                    )
                )
            if len(recent_notes) > _MAX_NOTES_IN_DETAIL:
                hidden = len(recent_notes) - _MAX_NOTES_IN_DETAIL
                rows.append(
                    Text(f"… {hidden} older (open with e)", style=palette.DIM)
                )
        else:
            rows.append(Text("─ notes  (n to add) ──────────", style=palette.DIM))
            rows.append(Text("no notes yet", style=palette.DIM))

        self._body.update(Group(*rows))


def _field(label: str, value: str) -> Text:
    text = Text()
    text.append(label.ljust(9), style=palette.DIM)
    text.append(value, style=palette.FG)
    return text


def _field_text(label: str, value_text: Text) -> Text:
    prefix = Text(label.ljust(9), style=palette.DIM)
    return Text.assemble(prefix, value_text)
