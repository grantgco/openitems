"""Cross-engagement triage screen.

Shows live, non-done tasks across every active engagement, grouped by
due-date band so a user can plan *what's on my plate today / this week*
without switching engagements.

Editing is in-place via the existing ``TaskDetailScreen`` (Enter / e),
plus a ``c`` hotkey that jumps a task straight to its engagement's
terminal done-state bucket. Filtering reuses ``domain.search.apply``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import date

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Input, Static

from openitems.db.engine import session_scope
from openitems.db.models import Task
from openitems.domain import tasks as tasks_mod
from openitems.domain import triage
from openitems.domain.search import TaskFilter, apply
from openitems.tui import palette
from openitems.tui.widgets.filter_bar import FilterBar
from openitems.tui.widgets.task_format import format_due, format_priority, format_tags

_BAND_STYLE: dict[triage.DueBand, str] = {
    "overdue": f"bold {palette.RED}",
    "today": f"bold {palette.ACCENT}",
    "this_week": palette.CYAN,
    "later": palette.DIM,
    "no_due": palette.DIM,
}

_ENGAGEMENT_WIDTH = 14


class AllItemsScreen(Screen):
    """Read-many / edit-in-place view of every active engagement's open work."""

    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        # DataTable consumes `enter` for its own row-select binding; we listen
        # to `DataTable.RowSelected` below instead. `e` stays as a screen-level
        # alias because no child consumes it.
        Binding("e", "edit_task", "edit"),
        Binding("s", "advance_bucket", "advance"),
        Binding("c", "mark_done", "done"),
        Binding("slash", "focus_filter", "filter"),
        Binding("j", "move_down", "down", show=False),
        Binding("k", "move_up", "up", show=False),
        Binding("g", "top", "top", show=False),
        Binding("G", "bottom", "bottom", show=False),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
    ]

    DEFAULT_CSS = """
    AllItemsScreen #all-titlebar {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    AllItemsScreen #all-titlebar .heading {
        color: #5ee5e5;
        text-style: bold;
    }
    AllItemsScreen #all-table-wrap {
        height: 1fr;
        background: #251f38;
        border: round #ff8a3a;
        padding: 0 1;
    }
    AllItemsScreen #all-status {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    AllItemsScreen #all-status .key {
        color: #ff8a3a;
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.heading = Static("[b]all engagements[/b]", classes="heading")
        self.filter_bar = FilterBar()
        self.table = DataTable(zebra_stripes=False, header_height=1, cursor_type="row")
        self.status = Static(self._status_text(), id="all-status")
        self._filter = TaskFilter()
        self._row_task_ids: list[str] = []
        self._today: date = date.today()

    def compose(self) -> ComposeResult:
        yield Static(id="all-titlebar")
        yield self.heading
        yield self.filter_bar
        with Vertical(id="all-table-wrap"):
            yield self.table
        yield self.status

    def on_mount(self) -> None:
        self.table.add_columns("when", "client", "task", "tags", "pri", "due")
        self.reload()
        self.table.focus()

    # ── data ──────────────────────────────────────────────────────────

    def reload(self) -> None:
        self._today = date.today()
        with session_scope() as s:
            all_open = triage.list_open_across_engagements(s)
            visible = apply(replace(self._filter, today=self._today), all_open)
            bands = triage.bucket_by_due(visible, today=self._today)
            self._populate_table(bands)
            self._update_status(visible, bands)

    def _populate_table(
        self, bands: dict[triage.DueBand, list[Task]]
    ) -> None:
        self.table.clear()
        self._row_task_ids = []
        for band in triage.BAND_ORDER:
            for task in bands[band]:
                self._row_task_ids.append(task.id)
                self.table.add_row(
                    Text(triage.BAND_LABELS[band], style=_BAND_STYLE[band]),
                    _engagement_cell(task),
                    _task_cell(task),
                    format_tags(task.labels),
                    format_priority(task.priority),
                    format_due(task.due_date, tasks_mod.is_late(task, self._today)),
                )
        if self._row_task_ids:
            self.table.move_cursor(row=0)

    def _update_status(
        self,
        visible: Iterable[Task],
        bands: dict[triage.DueBand, list[Task]],
    ) -> None:
        total = sum(1 for _ in visible)
        parts = [
            f"{total} open",
            f"{len(bands['overdue'])} overdue",
            f"{len(bands['today'])} today",
            f"{len(bands['this_week'])} this week",
        ]
        keys = "  ".join(
            [
                "[b]Enter[/b] edit",
                "[b]s[/b] advance",
                "[b]c[/b] done",
                "[b]/[/b] filter",
                "[b]Esc[/b] back",
            ]
        )
        self.heading.update(
            f"[b]all engagements[/b]  ·  {' · '.join(parts)}"
        )
        self.status.update(self._status_text(keys))

    @staticmethod
    def _status_text(keys: str = "") -> str:
        return keys or " "

    # ── selection helpers ─────────────────────────────────────────────

    def _selected_task_id(self) -> str | None:
        if not self._row_task_ids:
            return None
        row = self.table.cursor_row
        if row < 0 or row >= len(self._row_task_ids):
            return None
        return self._row_task_ids[row]

    # ── actions ───────────────────────────────────────────────────────

    def action_back(self) -> None:
        if self.focused is self.filter_bar:
            self.table.focus()
            return
        self.app.pop_screen()

    def action_edit_task(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        from openitems.tui.screens.task_detail import TaskDetailScreen

        def _after(result: bool) -> None:
            if result:
                self.reload()

        self.app.push_screen(TaskDetailScreen(task_id), _after)

    def action_advance_bucket(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            tasks_mod.advance_bucket(s, task)
            new_name = task.bucket.name if task.bucket else "(no bucket)"
        self.app.notify(f"→ {new_name}")
        self.reload()

    def action_mark_done(self) -> None:
        """Move the selected task to its engagement's terminal done-state.

        Default workflow → "Closed". If the engagement has no done-state
        bucket configured, notify and no-op rather than guessing.
        """
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            done = triage.done_bucket_for(s, task.engagement)
            if done is None:
                self.app.notify(
                    "No done-state bucket on this engagement.",
                    severity="warning",
                )
                return
            tasks_mod.update(s, task, bucket_id=done.id)
            engagement_name = task.engagement.name
            bucket_name = done.name
        self.app.notify(f"{engagement_name} → {bucket_name}")
        self.reload()

    def action_focus_filter(self) -> None:
        self.filter_bar.focus()

    def action_move_down(self) -> None:
        self._forward_key("down")

    def action_move_up(self) -> None:
        self._forward_key("up")

    def action_top(self) -> None:
        self._forward_key("home")

    def action_bottom(self) -> None:
        self._forward_key("end")

    def _forward_key(self, key: str) -> None:
        focused = self.app.focused
        if focused is None:
            return
        from textual.events import Key

        focused.post_message(Key(key=key, character=None))

    def action_help(self) -> None:
        from openitems.tui.screens.help import HelpScreen

        self.app.push_screen(HelpScreen())

    @on(Input.Changed, "#filter-bar")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._filter = replace(self._filter, text=event.value)
        self.reload()

    @on(DataTable.RowSelected)
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_edit_task()


def _engagement_cell(task: Task) -> Text:
    name = task.engagement.name if task.engagement else "—"
    if len(name) > _ENGAGEMENT_WIDTH:
        name = name[: _ENGAGEMENT_WIDTH - 1] + "…"
    style = palette.MAGENTA if task.engagement and task.engagement.is_inbox else palette.CYAN
    return Text(name, style=style)


def _task_cell(task: Task) -> Text:
    cell = Text(task.name, style=palette.FG)
    note_count = len(task.notes)
    if note_count:
        cell.append(f"  ✎{note_count}", style=palette.DIM)
    return cell
