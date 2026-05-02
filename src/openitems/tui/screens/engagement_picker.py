"""Pick an engagement from a list — used by the move-to-engagement action.

Returns the chosen slug, or ``None`` if dismissed without picking.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from openitems.db.engine import session_scope
from openitems.domain import engagements as engagements_mod


class EngagementPickerScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("enter", "pick", "select", show=False),
    ]

    def __init__(self, *, prompt: str = "move to engagement", exclude_slug: str | None = None) -> None:
        super().__init__()
        self._prompt = prompt
        self._exclude_slug = exclude_slug
        self._option_list = OptionList(id="engagement-picker-options")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label(f"[b]{self._prompt}[/b]", classes="modal-title")
            yield Label("[dim]press Enter to pick · Esc to cancel[/dim]", classes="dim")
            yield self._option_list

    def on_mount(self) -> None:
        with session_scope() as s:
            rows = engagements_mod.list_active(s)
        opts: list[Option] = []
        for e in rows:
            if e.slug == self._exclude_slug:
                continue
            text = Text()
            badge = "📥 " if e.is_inbox else ""
            text.append(badge, style="dim")
            text.append(e.name, style="bold")
            text.append(f"   {e.slug}", style="dim")
            opts.append(Option(text, id=e.slug))
        if not opts:
            opts.append(
                Option(
                    Text("(no other engagements — create one first with E)", style="dim"),
                    disabled=True,
                )
            )
        self._option_list.add_options(opts)
        self._option_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_pick(self) -> None:
        idx = self._option_list.highlighted
        if idx is None:
            return
        option = self._option_list.get_option_at_index(idx)
        if option.id is None or option.disabled:
            return
        self.dismiss(option.id)

    @on(OptionList.OptionSelected, "#engagement-picker-options")
    def _on_select(self, event: OptionList.OptionSelected) -> None:
        if event.option.id is None or event.option.disabled:
            return
        self.dismiss(event.option.id)
