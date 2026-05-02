from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static

_HELP = """[b]navigation[/b]
  Tab / Shift+Tab     cycle pane focus
  j / k               move down / up
  g / G               top / bottom
  1-9                 jump to bucket N

[b]editing[/b]
  a                   new task
  e or enter          edit selected task
  n                   add note to selected task
  L                   activity log (all notes, this engagement)
  d                   soft-delete
  u                   undo last delete
  s                   advance task to next workflow stage
  p                   cycle priority
  space               toggle next checklist item

[b]other[/b]
  /                   focus filter / search
  x                   open export wizard
  X                   quick-export with last settings
  E                   switch engagement
  ?                   this help
  q                   quit"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "close", show=False)]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]keymap[/b]", classes="modal-title")
            yield Static(_HELP)

    def action_dismiss(self) -> None:
        self.dismiss(None)
