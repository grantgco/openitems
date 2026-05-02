from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from openitems.tui import palette


@dataclass(frozen=True)
class BucketStat:
    """Snapshot of a workflow stage for the sidebar."""

    name: str
    total: int
    done: int
    is_done_state: bool


@dataclass(frozen=True)
class BucketSelection:
    """Identifies what the user picked in the bucket pane."""

    kind: str  # 'all' | 'bucket' | 'tag' | 'filter'
    value: str | None = None


class BucketPane(Vertical):
    """Left pane: All / workflow stages with progress / tags / filters."""

    class SelectionChanged(Message):
        def __init__(self, selection: BucketSelection) -> None:
            self.selection = selection
            super().__init__()

    def __init__(self) -> None:
        super().__init__(id="bucket-pane", classes="pane")
        self._option_list = OptionList(id="bucket-options")

    def compose(self) -> ComposeResult:
        yield Label("[b]workflow[/b]")
        yield self._option_list

    def focus_list(self) -> None:
        """Move focus to the inner OptionList. Used by the parent screen
        when cycling pane focus — keeps the OptionList private."""
        self._option_list.focus()

    def populate(
        self,
        *,
        total: int,
        done: int,
        buckets: list[BucketStat],
        tags: list[tuple[str, int]],
        filter_states: dict[str, bool] | None = None,
    ) -> None:
        states = filter_states or {
            "overdue_only": False,
            "unassigned": False,
            "focus_only": False,
        }
        opts: list[Option] = []
        opts.append(self._all_option(total, done))
        opts.append(self._make_section("─ workflow ─"))
        for stat in buckets:
            opts.append(self._make_bucket(stat))
        opts.append(self._make_section("─ tags ─"))
        if not tags:
            opts.append(self._make_section("(none)", muted=True))
        for name, count in tags:
            opts.append(self._make_tag(name, count))
        opts.append(self._make_section("─ filters ─"))
        opts.append(
            self._make_toggle("filter", "focus_only", "★ this week", states.get("focus_only", False))
        )
        opts.append(
            self._make_toggle("filter", "overdue_only", "overdue only", states["overdue_only"])
        )
        opts.append(
            self._make_toggle("filter", "unassigned", "unassigned", states["unassigned"])
        )
        self._option_list.clear_options()
        self._option_list.add_options(opts)

    @staticmethod
    def _all_option(total: int, done: int) -> Option:
        text = Text()
        text.append("▸ All", style=f"bold {palette.ACCENT}")
        text.append("  ")
        text.append(_progress_bar(done, total), style=palette.ACCENT)
        text.append(" ")
        text.append(f"{done}/{total}".rjust(6), style=palette.DIM)
        return Option(text, id="all::")

    @staticmethod
    def _make_bucket(stat: BucketStat) -> Option:
        text = Text()
        name_style = f"bold {palette.GREEN}" if stat.is_done_state else palette.FG
        text.append(stat.name.ljust(14), style=name_style)
        text.append(_progress_bar(stat.done, stat.total), style=palette.ACCENT)
        text.append(" ")
        text.append(str(stat.total).rjust(3), style=palette.DIM)
        return Option(text, id=f"bucket::{stat.name}")

    @staticmethod
    def _make_tag(name: str, count: int) -> Option:
        text = Text()
        text.append(name, style=palette.BLUE)
        text.append("  ")
        text.append(str(count).rjust(3), style=palette.DIM)
        return Option(text, id=f"tag::{name}")

    @staticmethod
    def _make_section(label: str, *, muted: bool = False) -> Option:
        return Option(
            Text(label, style=palette.DIM if not muted else palette.RULE),
            disabled=True,
        )

    @staticmethod
    def _make_toggle(kind: str, value: str, label: str, on: bool) -> Option:
        text = Text()
        text.append(label, style=palette.FG if on else palette.DIM)
        text.append("  ")
        text.append("[x]" if on else "[ ]", style=palette.ACCENT if on else palette.DIM)
        return Option(text, id=f"{kind}::{value}")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        opt_id = event.option.id or ""
        if "::" not in opt_id:
            return
        kind, _, raw_value = opt_id.partition("::")
        value = raw_value or None
        self.post_message(self.SelectionChanged(BucketSelection(kind=kind, value=value)))


def _progress_bar(done: int, total: int, width: int = 6) -> str:
    """Block-character progress bar, e.g. ``████░░`` for 4/6."""
    if total <= 0:
        return "─" * width
    filled = round((done / total) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)
