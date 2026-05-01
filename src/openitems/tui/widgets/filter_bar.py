from __future__ import annotations

from textual.widgets import Input


class FilterBar(Input):
    """Single-line fuzzy filter input. Empty input = show everything.

    Listen to ``textual.widgets.Input.Changed`` (filtered by ``#filter-bar``)
    in the parent screen — we deliberately do not introduce a custom message,
    because shadowing ``Input.Changed`` breaks Textual's auto-posting.
    """

    DEFAULT_CSS = """
    FilterBar {
        height: 1;
        background: #14171b;
        color: #d6d2c8;
        border: none;
        padding: 0 1;
    }
    FilterBar:focus { background: #1f1d18; color: #d6b35a; }
    """

    def __init__(self) -> None:
        super().__init__(
            placeholder="press / to filter — type to fuzzy-search",
            id="filter-bar",
        )
