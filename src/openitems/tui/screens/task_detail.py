from __future__ import annotations

from datetime import UTC, datetime

import humanize
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, OptionList, Select, TextArea
from textual.widgets.option_list import Option

from openitems.db.engine import session_scope
from openitems.db.models import Task
from openitems.domain import buckets as buckets_mod
from openitems.domain import checklists, notes, tasks
from openitems.domain.constants import PRIORITIES
from openitems.domain.dates import DateParseError, parse_strict as parse_date_strict
from openitems.domain.text import parse_labels


class TaskDetailScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id
        with session_scope() as s:
            task = s.get(Task, task_id)
            self._bucket_names = (
                buckets_mod.names_for(s, task.engagement) if task else []
            )
        self.name_input = Input(id="task-name")
        self.bucket_input = Input(
            id="task-bucket",
            suggester=SuggestFromList(self._bucket_names, case_sensitive=False),
        )
        self.priority_select = Select([(p, p) for p in PRIORITIES], id="task-priority")
        self.assigned_input = Input(id="task-assigned")
        self.start_input = Input(id="task-start", placeholder="Start — e.g. today")
        self.due_input = Input(id="task-due", placeholder="Due — e.g. 2026-06-01")
        self.labels_input = Input(id="task-labels")
        self.desc_input = TextArea("", id="task-desc", show_line_numbers=False)
        self.desc_input.styles.height = 6
        self.checklist_input = Input(placeholder="Add checklist item, press Enter", id="checklist-add")
        self.checklist_options = OptionList(id="checklist-options")
        self.note_input = Input(placeholder="Add note (thought / update), press Enter", id="note-add")
        self.note_options = OptionList(id="note-options")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]edit task[/b]", classes="modal-title")
            yield Label("Name", classes="dim")
            yield self.name_input
            with Horizontal():
                with Vertical():
                    yield Label("Workflow stage", classes="dim")
                    yield self.bucket_input
                with Vertical():
                    yield Label("Priority", classes="dim")
                    yield self.priority_select
            yield Label("Assigned to", classes="dim")
            yield self.assigned_input
            yield Label("Start", classes="dim")
            yield self.start_input
            yield Label("Due", classes="dim")
            yield self.due_input
            yield Label("Tags", classes="dim")
            yield self.labels_input
            yield Label("Description", classes="dim")
            yield self.desc_input
            yield Label("Checklist  (space toggles selected, del removes)", classes="dim")
            yield self.checklist_options
            yield self.checklist_input
            yield Label("Notes  (newest first, append-only)", classes="dim")
            yield self.note_options
            yield self.note_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self._load()
        self.name_input.focus()

    def _load(self) -> None:
        with session_scope() as s:
            task = s.get(Task, self.task_id)
            if task is None:
                self.app.notify("Task not found.", severity="error")
                self.dismiss(False)
                return
            self.name_input.value = task.name
            self.bucket_input.value = task.bucket.name if task.bucket else ""
            self.priority_select.value = task.priority
            self.assigned_input.value = task.assigned_to
            self.start_input.value = task.start_date.strftime("%Y-%m-%d") if task.start_date else ""
            self.due_input.value = task.due_date.strftime("%Y-%m-%d") if task.due_date else ""
            self.labels_input.value = task.labels
            self.desc_input.text = task.description
            self._refresh_checklist(task)
            self._refresh_notes(task)

    def _refresh_checklist(self, task: Task) -> None:
        self.checklist_options.clear_options()
        for c in task.checklist_items:
            if c.deleted_at is not None:
                continue
            prefix = "[x] " if c.completed else "[ ] "
            self.checklist_options.add_option(Option(prefix + c.text, id=c.id))

    def _refresh_notes(self, task: Task) -> None:
        self.note_options.clear_options()
        now = datetime.now(UTC).replace(tzinfo=None)
        for n in notes.list_for(task):
            relative = humanize.naturaltime(now - n.created_at)
            preview = n.body.replace("\n", " | ")
            if len(preview) > 80:
                preview = preview[:77] + "…"
            self.note_options.add_option(Option(f"{relative}  ·  {preview}", id=n.id))

    @on(Input.Submitted, "#note-add")
    def _add_note(self, event: Input.Submitted) -> None:
        body = event.value.strip()
        if not body:
            return
        with session_scope() as s:
            task = s.get(Task, self.task_id)
            if task is None:
                return
            try:
                notes.add(s, task, body)
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")
                return
            self._refresh_notes(task)
        self.note_input.value = ""

    @on(Input.Submitted, "#checklist-add")
    def _add_check(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        with session_scope() as s:
            task = s.get(Task, self.task_id)
            if task is None:
                return
            checklists.add(s, task, text)
            self._refresh_checklist(task)
        self.checklist_input.value = ""

    @on(OptionList.OptionSelected, "#checklist-options")
    def _toggle_check(self, event: OptionList.OptionSelected) -> None:
        cid = event.option.id
        if not cid:
            return
        with session_scope() as s:
            task = s.get(Task, self.task_id)
            if task is None:
                return
            for c in task.checklist_items:
                if c.id == cid and c.deleted_at is None:
                    checklists.toggle(s, c)
                    break
            self._refresh_checklist(task)

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        try:
            start_date = parse_date_strict(self.start_input.value, field="Start")
            due_date = parse_date_strict(self.due_input.value, field="Due")
        except DateParseError as exc:
            self.app.notify(str(exc), severity="error")
            return
        pending_note = self.note_input.value.strip()
        pending_check = self.checklist_input.value.strip()
        try:
            with session_scope() as s:
                task = s.get(Task, self.task_id)
                if task is None:
                    return
                bucket_name = self.bucket_input.value.strip()
                if bucket_name:
                    bucket = buckets_mod.get_or_create(s, task.engagement, bucket_name)
                    bucket_id = bucket.id
                else:
                    bucket_id = None
                tasks.update(
                    s,
                    task,
                    name=self.name_input.value,
                    description=self.desc_input.text,
                    priority=str(self.priority_select.value or task.priority),
                    assigned_to=self.assigned_input.value,
                    start_date=start_date,
                    due_date=due_date,
                    labels=", ".join(parse_labels(self.labels_input.value)),
                    bucket_id=bucket_id,
                )
                if pending_note:
                    notes.add(s, task, pending_note)
                if pending_check:
                    checklists.add(s, task, pending_check)
        except ValueError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.dismiss(True)
