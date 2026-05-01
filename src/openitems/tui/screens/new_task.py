from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, Select, TextArea

from openitems.db.engine import session_scope
from openitems.domain import buckets as buckets_mod
from openitems.domain import engagements, tasks
from openitems.domain.constants import PRIORITIES
from openitems.domain.dates import DateParseError, parse_strict as parse_date_strict
from openitems.domain.tasks import TaskInput
from openitems.domain.text import parse_labels


class NewTaskScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, engagement_slug)
            self._bucket_names = (
                buckets_mod.names_for(s, engagement) if engagement else []
            )
        self.name_input = Input(placeholder="Task name", id="task-name")
        self.bucket_input = Input(
            placeholder="Workflow stage (e.g. Backlog)",
            id="task-bucket",
            value=self._bucket_names[0] if self._bucket_names else "",
            suggester=SuggestFromList(self._bucket_names, case_sensitive=False),
        )
        self.priority_select = Select(
            [(p, p) for p in PRIORITIES], value="Medium", id="task-priority"
        )
        self.assigned_input = Input(placeholder="Assigned to (free text)", id="task-assigned")
        self.start_input = Input(placeholder="Start — e.g. today", id="task-start")
        self.due_input = Input(placeholder="Due — e.g. 2026-06-01", id="task-due")
        self.labels_input = Input(placeholder="Tags, comma-separated", id="task-labels")
        self.desc_input = TextArea("", id="task-desc", show_line_numbers=False)
        self.desc_input.styles.height = 6

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label("[b]new task[/b]", classes="modal-title")
            yield self.name_input
            with Horizontal():
                yield self.bucket_input
                yield self.priority_select
            yield self.assigned_input
            with Horizontal():
                with Vertical():
                    yield Label("Start", classes="dim")
                    yield self.start_input
                with Vertical():
                    yield Label("Due", classes="dim")
                    yield self.due_input
            yield self.labels_input
            yield Label("Description", classes="dim")
            yield self.desc_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self.name_input.focus()

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        name = self.name_input.value.strip()
        if not name:
            self.app.notify("Name is required.", severity="warning")
            return
        try:
            start_date = parse_date_strict(self.start_input.value, field="Start")
            due_date = parse_date_strict(self.due_input.value, field="Due")
        except DateParseError as exc:
            self.app.notify(str(exc), severity="error")
            return
        try:
            input_ = TaskInput(
                name=name,
                description=self.desc_input.text,
                priority=str(self.priority_select.value or "Medium"),
                assigned_to=self.assigned_input.value,
                start_date=start_date,
                due_date=due_date,
                labels=parse_labels(self.labels_input.value),
                bucket_name=self.bucket_input.value.strip() or None,
            )
            with session_scope() as s:
                e = engagements.get_by_slug(s, self.engagement_slug)
                if e is None:
                    self.app.notify("Engagement disappeared.", severity="error")
                    return
                tasks.create(s, e, input_)
        except ValueError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.dismiss(True)
