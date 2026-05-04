from __future__ import annotations

from rich.text import Text
from textual.events import Resize
from textual.widgets import Static

from openitems.tui import palette


class StatusBar(Static):
    """Bottom keymap legend.

    Renders pairs of (key, label) joined by ``│`` separators in rule color.
    Adapts to terminal width: entries are dropped from *the middle of the
    list* (``OPTIONAL_MIDDLE[-1]`` first, working leftward), while the
    essential head (``j/k`` … ``i jot``) and the tail (``? more`` /
    ``q quit``) are always shown. This keeps the daily-most-used keys
    plus the discovery / escape hatches visible at every width.

    Less-used bindings (``M / p / u / x / X / o / O / L``) are documented
    in the HelpScreen — pressing ``?`` is the safety net.
    """

    # Daily-essential, always shown.
    ESSENTIAL_HEAD: list[tuple[str, str]] = [
        ("j/k", "move"),
        ("a", "add"),
        ("e", "edit"),
        ("n", "note"),
        ("i", "jot"),
    ]
    # Shown in place of the head when sitting on the Inbox engagement —
    # surfaces M (move-to-engagement) so promoting jotted items is
    # discoverable without opening the help screen.
    INBOX_HEAD: list[tuple[str, str]] = [
        ("j/k", "move"),
        ("M", "→ engagement"),
        ("e", "edit"),
        ("a", "add"),
        ("i", "jot"),
    ]
    # Shown when there's room. Most-important first; dropped from the END
    # of this list when narrow terminals can't fit them.
    OPTIONAL_MIDDLE: list[tuple[str, str]] = [
        ("/", "filter"),
        ("s", "advance"),
        ("f", "focus"),
        ("d", "del"),
        ("D", "digest"),
        ("E", "switch"),
    ]
    # Discovery + escape — always shown at the right edge.
    ESSENTIAL_TAIL: list[tuple[str, str]] = [
        ("?", "more"),
        ("q", "quit"),
    ]

    SEP = " │ "  # 3 cells

    def __init__(self) -> None:
        super().__init__("", id="status-bar")
        self._inbox_mode = False

    def set_inbox_mode(self, active: bool) -> None:
        if active == self._inbox_mode:
            return
        self._inbox_mode = active
        self.update(self._render_for_width(self.size.width or 200))

    def on_mount(self) -> None:
        self.update(self._render_for_width(self.size.width or 200))

    def on_resize(self, event: Resize) -> None:
        self.update(self._render_for_width(event.size.width))

    def _render_for_width(self, width: int) -> Text:
        """Pick the largest middle-subset that fits in ``width`` cells."""
        head = self.INBOX_HEAD if self._inbox_mode else self.ESSENTIAL_HEAD
        for n in range(len(self.OPTIONAL_MIDDLE), -1, -1):
            entries = head + self.OPTIONAL_MIDDLE[:n] + self.ESSENTIAL_TAIL
            text = self._render_entries(entries)
            if text.cell_len <= width:
                return text
        # Even head + tail don't fit — render anyway (Textual will clip).
        return self._render_entries(head + self.ESSENTIAL_TAIL)

    def _render_entries(self, entries: list[tuple[str, str]]) -> Text:
        text = Text(no_wrap=True)
        for i, (key, label) in enumerate(entries):
            if i:
                text.append(self.SEP, style=palette.RULE)
            text.append(key, style=f"bold {palette.ACCENT}")
            text.append(" ", style=palette.DIM)
            text.append(label, style=palette.DIM)
        return text
