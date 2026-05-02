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
from openitems.domain.text import normalize_url


class EngagementSwitcher(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("enter", "submit", "select", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._option_list = OptionList(id="engagement-options")
        self._new_input = Input(
            placeholder="…or type a name and press Enter to create",
            id="new-engagement-input",
        )
        self._url_input = Input(
            placeholder="↗ URL for highlighted engagement (Tab to edit, Enter to save)",
            id="engagement-url-input",
        )
        # Tracks which engagement slug the URL input currently corresponds to,
        # so we know which row to update when Enter is pressed.
        self._url_for_slug: str | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]engagements[/b]", classes="modal-title")
            yield self._option_list
            yield Label(
                "[dim]press enter to switch · type below to create new[/dim]",
                classes="dim",
            )
            yield self._new_input
            yield self._url_input

    def on_mount(self) -> None:
        self._refresh_options()
        self._option_list.focus()
        # Force-prime the highlighted row so the URL field knows which
        # engagement it's editing without requiring the user to press j/k
        # first. (OptionList doesn't fire OptionHighlighted on initial
        # mount — only on user navigation.)
        if self._option_list.option_count > 0:
            for idx in range(self._option_list.option_count):
                opt = self._option_list.get_option_at_index(idx)
                if opt.id and not opt.disabled:
                    self._option_list.highlighted = idx
                    self._sync_url_field_to(opt.id)
                    break

    def _sync_url_field_to(self, slug: str) -> None:
        self._url_for_slug = slug
        with session_scope() as s:
            e = engagements.get_by_slug(s, slug)
            self._url_input.value = (e.homepage_url or "") if e else ""

    def _refresh_options(self, *, select_slug: str | None = None) -> None:
        with session_scope() as s:
            rows = engagements.list_active(s)
        opts: list[Option] = []
        for e in rows:
            text = Text()
            badge = "📥 " if e.is_inbox else ""
            text.append(badge, style="dim")
            text.append(e.name, style="bold")
            text.append(f"   {e.slug}", style="dim")
            if e.homepage_url:
                text.append("   ↗", style="dim")
            opts.append(Option(text, id=e.slug))
        if not opts:
            opts.append(
                Option(
                    Text("(no engagements yet — type below to create)", style="dim"),
                    disabled=True,
                )
            )
        self._option_list.clear_options()
        self._option_list.add_options(opts)
        if select_slug is not None:
            for idx, opt in enumerate(opts):
                if opt.id == select_slug:
                    self._option_list.highlighted = idx
                    break

    @on(OptionList.OptionHighlighted)
    def _on_highlight(self, event: OptionList.OptionHighlighted) -> None:
        slug = event.option.id if event.option else None
        if not slug:
            self._url_for_slug = None
            self._url_input.value = ""
            return
        self._sync_url_field_to(slug)

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

    @on(Input.Submitted, "#engagement-url-input")
    def _on_url_save(self, event: Input.Submitted) -> None:
        if not self._url_for_slug:
            self.app.notify("Highlight an engagement first.", severity="warning")
            return
        url = normalize_url(event.value)
        with session_scope() as s:
            e = engagements.get_by_slug(s, self._url_for_slug)
            if e is None:
                self.app.notify("Engagement gone.", severity="error")
                return
            e.homepage_url = url
        self._refresh_options(select_slug=self._url_for_slug)
        # Reflect any prepended scheme back into the field so the user
        # sees what was actually saved.
        self._url_input.value = url or ""
        self.app.notify("↗ saved" if url else "↗ cleared")
        self._option_list.focus()

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
        elif self._url_input.has_focus:
            self._on_url_save(Input.Submitted(self._url_input, self._url_input.value))
        else:
            highlighted = self._option_list.highlighted
            if highlighted is not None:
                option = self._option_list.get_option_at_index(highlighted)
                if option.id:
                    self._activate(option.id)
