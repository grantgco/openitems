from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea

from openitems.db.engine import session_scope
from openitems.db.models import Task
from openitems.domain import notes


class QuickNoteScreen(ModalScreen[bool]):
    """Lightweight modal for appending a note to a task without opening the
    full edit dialog. Bound to ``n`` from the main screen."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id
        self._task_name = ""
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is not None:
                self._task_name = task.name
        self.body_input = TextArea("", id="note-body", show_line_numbers=False)
        self.body_input.styles.height = 8

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label(f"[b]add note[/b]  ·  {self._task_name}", classes="modal-title")
            yield Label("Body  (^S to save, Esc to cancel)", classes="dim")
            yield self.body_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self.body_input.focus()

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        body = self.body_input.text.strip()
        if not body:
            self.app.notify("Note body is empty.", severity="warning")
            return
        with session_scope() as s:
            task = s.get(Task, self.task_id)
            if task is None:
                self.app.notify("Task not found.", severity="error")
                self.dismiss(False)
                return
            try:
                notes.add(s, task, body)
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")
                return
        self.app.notify("Note added.")
        self.dismiss(True)
