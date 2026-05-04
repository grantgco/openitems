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
  i                   jot — brain-dump into Inbox
  L                   activity log (all notes, this engagement)
  M                   move task to another engagement
  d                   soft-delete
  u                   undo last delete
  s                   advance task to next workflow stage
  p                   cycle priority
  f                   toggle ★ "this week" focus on selected task
  space               toggle next checklist item

[b]other[/b]
  /                   focus filter / search
  x                   open export wizard (.xlsx workplan)
  X                   quick-export with last settings
  D                   write Markdown digest (this week, opens in default app)
  E                   switch engagement (also: edit URLs)
  A                   "my plate" — open items across every engagement
  P                   policies for the active engagement
  R                   renewal radar — policies across every engagement
  o                   open active engagement URL in browser
  O                   open selected task's external URL in browser
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
