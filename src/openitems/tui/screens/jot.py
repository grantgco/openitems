"""Brain-dump capture: append a task to the inbox engagement.

Bound to ``i`` from anywhere on the main screen. Doesn't switch the active
engagement — the thought goes to the inbox and is triaged later (or via
the ``M`` move-to-engagement keybind on the inbox view).
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from openitems.db.engine import session_scope
from openitems.domain import engagements as engagements_mod
from openitems.domain import tasks as tasks_mod
from openitems.domain.tasks import TaskInput


class JotScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.body_input = Input(
            placeholder="thought goes here — Enter or ^S to drop into Inbox",
            id="jot-body",
        )

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]jot[/b]  ·  drops into Inbox", classes="modal-title")
            yield Label(
                "[dim]Enter or ^S to save · Esc to cancel[/dim]",
                classes="dim",
            )
            yield self.body_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self.body_input.focus()

    @on(Input.Submitted, "#jot-body")
    def _on_submit(self, _: Input.Submitted) -> None:
        self.action_save()

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        body = self.body_input.value.strip()
        if not body:
            self.app.notify("Empty thought.", severity="warning")
            return
        with session_scope() as s:
            inbox = engagements_mod.ensure_inbox(s)
            try:
                tasks_mod.create(s, inbox, TaskInput(name=body))
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")
                return
        self.app.notify(f"→ Inbox · {body[:40]}{'…' if len(body) > 40 else ''}")
        self.dismiss(True)
