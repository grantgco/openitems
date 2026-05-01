from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from openitems.tui import palette


class StatusBar(Static):
    """Bottom keymap legend.

    Renders pairs of (key, label) joined by `│` separators in rule color.
    """

    BINDINGS_CHEATSHEET: list[tuple[str, str]] = [
        ("Tab", "pane"),
        ("j/k", "move"),
        ("a", "add"),
        ("e", "edit"),
        ("d", "delete"),
        ("space", "check"),
        ("s", "advance"),
        ("p", "priority"),
        ("/", "filter"),
        ("u", "undo"),
        ("x", "export"),
        ("X", "quick-x"),
        ("E", "engagement"),
        ("?", "help"),
        ("q", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__(self._render_text(), id="status-bar")

    def _render_text(self) -> Text:
        text = Text(no_wrap=True)
        for i, (key, label) in enumerate(self.BINDINGS_CHEATSHEET):
            if i:
                text.append("  │  ", style=palette.RULE)
            text.append(key, style=f"bold {palette.ACCENT}")
            text.append(" ", style=palette.DIM)
            text.append(label, style=palette.DIM)
        return text

    def refresh_text(self) -> None:
        self.update(self._render_text())
