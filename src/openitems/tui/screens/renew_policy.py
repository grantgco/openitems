"""Renew an existing policy.

Prefills a new-policy form from the predecessor (carrier, coverage, etc.) with
suggested dates one term forward. Saving creates a successor linked back via
``renewed_from_id`` and archives the predecessor by default — toggleable via
the "archive predecessor" checkbox if the user wants both rows live (e.g.
overlap during a transition).
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Checkbox, Input, Label, TextArea

from openitems.db.engine import session_scope
from openitems.db.models import Policy
from openitems.domain import policies
from openitems.domain.dates import DateParseError
from openitems.domain.dates import parse_strict as parse_date_strict
from openitems.domain.policies import PolicyDateError, PolicyInput


class RenewPolicyScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, policy_id: str) -> None:
        super().__init__()
        self.policy_id = policy_id
        with session_scope() as s:
            self._coverages = policies.coverage_suggestions(s)
        self.name_input = Input(id="policy-name")
        self.carrier_input = Input(id="policy-carrier")
        self.coverage_input = Input(
            id="policy-coverage",
            suggester=SuggestFromList(self._coverages, case_sensitive=False),
        )
        self.policy_number_input = Input(id="policy-number")
        self.effective_input = Input(id="policy-eff", placeholder="Effective — e.g. 2027-01-01")
        self.expiration_input = Input(id="policy-exp", placeholder="Expiration — e.g. 2028-01-01")
        self.location_input = Input(id="policy-loc")
        self.desc_input = TextArea("", id="policy-desc", show_line_numbers=False)
        self.desc_input.styles.height = 4
        self.archive_checkbox = Checkbox(
            "Archive expiring policy",
            value=True,
            id="archive-predecessor",
        )
        self.title_label = Label("[b]renew policy[/b]", classes="modal-title")
        self.context_label = Label("", classes="dim", id="renew-context")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield self.title_label
            yield self.context_label
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
                    yield Label("New effective", classes="dim")
                    yield self.effective_input
                with Vertical():
                    yield Label("New expiration", classes="dim")
                    yield self.expiration_input
            yield Label("Location / project", classes="dim")
            yield self.location_input
            yield Label("Description", classes="dim")
            yield self.desc_input
            yield self.archive_checkbox
            with Horizontal():
                yield Button("Renew  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self._load()
        self.effective_input.focus()

    def _load(self) -> None:
        with session_scope() as s:
            policy = s.get(Policy, self.policy_id)
            if policy is None:
                self.app.notify("Policy not found.", severity="error")
                self.dismiss(False)
                return
            self.name_input.value = policy.name
            self.carrier_input.value = policy.carrier
            self.coverage_input.value = policy.coverage
            self.policy_number_input.value = policy.policy_number
            self.location_input.value = policy.location
            self.desc_input.text = policy.description
            new_eff, new_exp = policies.suggest_renewal_dates(policy)
            self.effective_input.value = new_eff.strftime("%Y-%m-%d") if new_eff else ""
            self.expiration_input.value = new_exp.strftime("%Y-%m-%d") if new_exp else ""
            old_exp = (
                policy.expiration_date.strftime("%Y-%m-%d")
                if policy.expiration_date
                else "no expiration"
            )
            self.context_label.update(
                f"renewing [b]{policy.name}[/b]  ·  expires {old_exp}"
            )

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
            eff = parse_date_strict(
                self.effective_input.value, field="Effective", prefer="current_period"
            )
            exp = parse_date_strict(
                self.expiration_input.value, field="Expiration", prefer="current_period"
            )
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
                predecessor = s.get(Policy, self.policy_id)
                if predecessor is None:
                    self.app.notify("Policy disappeared.", severity="error")
                    return
                policies.renew(
                    s,
                    predecessor,
                    input_,
                    archive_predecessor=bool(self.archive_checkbox.value),
                )
        except PolicyDateError as exc:
            self.app.notify(str(exc), severity="error")
            return
        except ValueError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.dismiss(True)
