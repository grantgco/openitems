from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class Titlebar(Horizontal):
    DEFAULT_CSS = """
    Titlebar { height: 1; }
    Titlebar .dot {
        width: 2; content-align: center middle;
    }
    Titlebar .dot.r { color: #d57367; }
    Titlebar .dot.y { color: #d6b35a; }
    Titlebar .dot.g { color: #88b070; }
    Titlebar .name { padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__(id="titlebar")
        self._engagement_label = Static("[no engagement]", classes="titlebar-engagement")
        self._counts_label = Static("0 open · 0 overdue · 0 high · 0/0 done", classes="titlebar-counts")

    def compose(self) -> ComposeResult:
        yield Static("●", classes="dot r")
        yield Static("●", classes="dot y")
        yield Static("●", classes="dot g")
        yield Static(" openitems · ", classes="name")
        yield self._engagement_label
        yield Static("  ·  ", classes="dim")
        yield self._counts_label

    def set_engagement(self, name: str | None) -> None:
        self._engagement_label.update(name or "[no engagement]")

    def set_counts(
        self, *, open_count: int, overdue: int, high: int, done: int, total: int
    ) -> None:
        self._counts_label.update(
            f"{open_count} open · {overdue} overdue · {high} high · {done}/{total} done"
        )
