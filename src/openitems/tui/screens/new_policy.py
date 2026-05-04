from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, TextArea

from openitems.db.engine import session_scope
from openitems.domain import engagements, policies
from openitems.domain.dates import DateParseError
from openitems.domain.dates import parse_strict as parse_date_strict
from openitems.domain.policies import PolicyDateError, PolicyInput


class NewPolicyScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, engagement_slug)
            self._coverages = (
                policies.coverage_suggestions(s, engagement=engagement)
                if engagement
                else []
            )
        self.name_input = Input(placeholder="Policy name (e.g. Main GL 2026)", id="policy-name")
        self.carrier_input = Input(placeholder="Carrier", id="policy-carrier")
        self.coverage_input = Input(
            placeholder="Coverage (GL, Auto, Workers Comp, …)",
            id="policy-coverage",
            suggester=SuggestFromList(self._coverages, case_sensitive=False),
        )
        self.policy_number_input = Input(placeholder="Policy number", id="policy-number")
        self.effective_input = Input(
            placeholder="Effective — e.g. 2026-01-01", id="policy-eff"
        )
        self.expiration_input = Input(
            placeholder="Expiration — e.g. 2027-01-01", id="policy-exp"
        )
        self.location_input = Input(
            placeholder="Location / project (optional)", id="policy-loc"
        )
        self.desc_input = TextArea("", id="policy-desc", show_line_numbers=False)
        self.desc_input.styles.height = 4

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]new policy[/b]", classes="modal-title")
            yield Label("Name", classes="dim")
            yield self.name_input
            with Horizontal():
                with Vertical():
                    yield Label("Carrier", classes="dim")
                    yield self.carrier_input
                with Vertical():
                    yield Label("Coverage", classes="dim")
                    yield self.coverage_input
            yield Label("Policy number", classes="dim")
            yield self.policy_number_input
            with Horizontal():
                with Vertical():
                    yield Label("Effective", classes="dim")
                    yield self.effective_input
                with Vertical():
                    yield Label("Expiration", classes="dim")
                    yield self.expiration_input
            yield Label("Location / project", classes="dim")
            yield self.location_input
            yield Label("Description", classes="dim")
            yield self.desc_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self.name_input.focus()

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
        name = self.name_input.value.strip()
        if not name:
            self.app.notify("Name is required.", severity="warning")
            return
        try:
            eff = parse_date_strict(self.effective_input.value, field="Effective")
            exp = parse_date_strict(self.expiration_input.value, field="Expiration")
        except DateParseError as exc:
            self.app.notify(str(exc), severity="error")
            return
        try:
            input_ = PolicyInput(
                name=name,
                carrier=self.carrier_input.value,
                coverage=self.coverage_input.value,
                policy_number=self.policy_number_input.value,
                effective_date=eff,
                expiration_date=exp,
                location=self.location_input.value,
                description=self.desc_input.text,
            )
            with session_scope() as s:
                e = engagements.get_by_slug(s, self.engagement_slug)
                if e is None:
                    self.app.notify("Engagement disappeared.", severity="error")
                    return
                policies.create(s, e, input_)
        except PolicyDateError as exc:
            self.app.notify(str(exc), severity="error")
            return
        except ValueError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.dismiss(True)
