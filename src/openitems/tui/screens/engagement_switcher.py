from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from openitems.config import Config
from openitems.db.engine import session_scope
from openitems.domain import engagements


class EngagementSwitcher(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("enter", "submit", "select", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._option_list = OptionList(id="engagement-options")
        self._new_input = Input(placeholder="…or type a name and press Enter to create", id="new-engagement-input")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]engagements[/b]", classes="modal-title")
            yield self._option_list
            yield Label("[dim]press enter to switch · type to create new[/dim]", classes="dim")
            yield self._new_input

    def on_mount(self) -> None:
        with session_scope() as s:
            rows = engagements.list_active(s)
        opts: list[Option] = []
        for e in rows:
            text = Text()
            text.append(e.name, style="bold")
            text.append(f"   {e.slug}", style="dim")
            opts.append(Option(text, id=e.slug))
        if not opts:
            opts.append(Option(Text("(no engagements yet — type below to create)", style="dim"), disabled=True))
        self._option_list.add_options(opts)
        self._option_list.focus()

    @on(OptionList.OptionSelected)
    def _on_select(self, event: OptionList.OptionSelected) -> None:
        slug = event.option.id
        if slug:
            self._activate(slug)

    @on(Input.Submitted, "#new-engagement-input")
    def _on_create(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if not name:
            return
        with session_scope() as s:
            e = engagements.create(s, name)
            slug = e.slug
        self._activate(slug)

    def _activate(self, slug: str) -> None:
        cfg = Config.load()
        cfg.active_engagement = slug
        cfg.save()
        self.dismiss(slug)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        if self._new_input.has_focus:
            self._on_create(Input.Submitted(self._new_input, self._new_input.value))
        else:
            highlighted = self._option_list.highlighted
            if highlighted is not None:
                option = self._option_list.get_option_at_index(highlighted)
                if option.id:
                    self._activate(option.id)
