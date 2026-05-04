"""Read-only viewer for a single note's full body.

The note OptionLists in TaskDetailScreen / PolicyDetailScreen and the
ActivityLogScreen feed all truncate each note to a one-line preview so a
long history fits on screen. This modal shows the full body (with line
breaks preserved) so a long phone-call write-up or quoted email is
actually readable. TextArea is used in read-only mode so the body remains
selectable for copy-paste.
"""

from __future__ import annotations

from datetime import UTC, datetime

import humanize
from rich.markup import escape as rich_escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea

from openitems.domain import notes


class NoteViewerScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    NoteViewerScreen .modal {
        width: 90;
        max-width: 95%;
        max-height: 85%;
    }
    NoteViewerScreen #note-body-view {
        height: auto;
        min-height: 6;
        max-height: 30;
    }
    """

    BINDINGS = [
        Binding("escape,q", "close", "close", show=False),
    ]

    def __init__(
        self,
        *,
        body: str,
        kind: str,
        created_at: datetime,
        context: str = "",
    ) -> None:
        super().__init__()
        self._body = body
        self._kind = kind
        self._created_at = created_at
        self._context_label = context

    def compose(self) -> ComposeResult:
        glyph = notes.glyph_for(self._kind)
        now = datetime.now(UTC).replace(tzinfo=None)
        relative = humanize.naturaltime(now - self._created_at)
        absolute = self._created_at.strftime("%Y-%m-%d %H:%M")
        # Escape user-controlled context (task name) so brackets in a name
        # like "[review]" don't get parsed as Rich markup.
        suffix = (
            f"  ·  {rich_escape(self._context_label)}" if self._context_label else ""
        )

        body_widget = TextArea(
            self._body,
            read_only=True,
            soft_wrap=True,
            show_line_numbers=False,
            id="note-body-view",
        )

        with VerticalScroll(classes="modal"):
            yield Label(
                f"[b]note[/b]  ·  {glyph}  {self._kind}{suffix}",
                classes="modal-title",
            )
            yield Label(
                f"[dim]{relative}  ·  {absolute}  ·  Esc to close[/dim]"
            )
            yield body_widget

    def action_close(self) -> None:
        self.dismiss(None)
