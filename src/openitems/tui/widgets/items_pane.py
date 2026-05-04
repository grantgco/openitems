from __future__ import annotations

from datetime import UTC, date, datetime

import humanize
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import DataTable, Label

from openitems.db.models import Task
from openitems.domain.dates import start_of_week
from openitems.domain.tasks import auto_close_at, is_late
from openitems.tui import palette
from openitems.tui.widgets.task_format import format_due, format_priority, format_tags


class ItemsPane(Vertical):
    """Center pane: tabular list of tasks."""

    class TaskFocused(Message):
        def __init__(self, task_id: str | None) -> None:
            self.task_id = task_id
            super().__init__()

    def __init__(self) -> None:
        super().__init__(id="items-pane", classes="pane")
        self.table = DataTable(zebra_stripes=False, header_height=1, cursor_type="row")
        self._tasks: list[Task] = []
        self._today: date = date.today()

    def compose(self) -> ComposeResult:
        yield Label("[b]items[/b]")
        yield self.table

    def _ensure_columns(self) -> None:
        if not self.table.columns:
            self.table.add_columns("#", "task", "tags", "pri", "due")

    def on_mount(self) -> None:
        self._ensure_columns()

    @property
    def selected_task(self) -> Task | None:
        if not self._tasks or self.table.cursor_row < 0:
            return None
        if self.table.cursor_row >= len(self._tasks):
            return None
        return self._tasks[self.table.cursor_row]

    def populate(self, tasks: list[Task], *, today: date | None = None) -> None:
        self._ensure_columns()
        self._today = today or date.today()
        self._tasks = list(tasks)
        self.table.clear()
        monday = start_of_week(self._today)
        for idx, task in enumerate(self._tasks, start=1):
            note_count = len(task.notes)
            name_cell = Text(task.name, style=palette.FG)
            if task.focus_week == monday:
                name_cell.append(" ★", style=palette.ACCENT)
            if note_count:
                name_cell.append(f"  ✎{note_count}", style=palette.DIM)
            close_at = auto_close_at(task)
            if close_at is not None:
                delta = close_at - datetime.now(UTC).replace(tzinfo=None)
                chip = (
                    f"  ⏳ closes in {humanize.naturaldelta(delta)}"
                    if delta.total_seconds() > 0
                    else "  ⏳ closes any moment"
                )
                name_cell.append(chip, style=palette.DIM)
            self.table.add_row(
                Text(str(idx).rjust(3), style=palette.DIM),
                name_cell,
                format_tags(task.labels),
                format_priority(task.priority),
                format_due(task.due_date, is_late(task, self._today)),
            )
        if self._tasks:
            self.table.move_cursor(row=0)
        self._emit_focus()

    def _emit_focus(self) -> None:
        task = self.selected_task
        self.post_message(self.TaskFocused(task.id if task else None))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._emit_focus()
