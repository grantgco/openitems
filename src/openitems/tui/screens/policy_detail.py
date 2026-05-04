from __future__ import annotations

from datetime import UTC, datetime

import humanize
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, OptionList, Select, TextArea
from textual.widgets.option_list import Option

from openitems.db.engine import session_scope
from openitems.db.models import Policy
from openitems.domain import notes, policies, policy_notes
from openitems.domain.dates import DateParseError
from openitems.domain.dates import parse_strict as parse_date_strict
from openitems.domain.policies import PolicyDateError


class PolicyDetailScreen(ModalScreen[bool]):
    """Edit an existing policy plus append-only notes."""

    BINDINGS = [
        Binding("escape", "cancel", "cancel", show=False),
        Binding("ctrl+s", "save", "save", show=False),
    ]

    def __init__(self, policy_id: str) -> None:
        super().__init__()
        self.policy_id = policy_id
        with session_scope() as s:
            policy = s.get(Policy, policy_id)
            self._coverages = (
                policies.coverage_suggestions(s, engagement=policy.engagement)
                if policy
                else []
            )
        self.name_input = Input(id="policy-name")
        self.carrier_input = Input(id="policy-carrier")
        self.coverage_input = Input(
            id="policy-coverage",
            suggester=SuggestFromList(self._coverages, case_sensitive=False),
        )
        self.policy_number_input = Input(id="policy-number")
        self.effective_input = Input(id="policy-eff", placeholder="Effective — e.g. 2026-01-01")
        self.expiration_input = Input(id="policy-exp", placeholder="Expiration — e.g. 2027-01-01")
        self.location_input = Input(id="policy-loc")
        self.desc_input = TextArea("", id="policy-desc", show_line_numbers=False)
        self.desc_input.styles.height = 4
        self.note_kind_select = Select(
            [(f"{notes.glyph_for(k)}  {k}", k) for k in notes.NOTE_KINDS],
            value=notes.DEFAULT_KIND,
            id="note-kind",
            allow_blank=False,
        )
        self.note_input = Input(
            placeholder="Add note (renewal call, premium quote, …), press Enter",
            id="note-add",
        )
        self.note_options = OptionList(id="note-options")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]edit policy[/b]", classes="modal-title")
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
            yield Label("Notes  (newest first, append-only)", classes="dim")
            yield self.note_options
            yield Label("Kind", classes="dim")
            yield self.note_kind_select
            yield self.note_input
            with Horizontal():
                yield Button("Save  (^S)", id="save", classes="-primary")
                yield Button("Cancel  (Esc)", id="cancel")

    def on_mount(self) -> None:
        self._load()
        self.name_input.focus()

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
            self.effective_input.value = (
                policy.effective_date.strftime("%Y-%m-%d") if policy.effective_date else ""
            )
            self.expiration_input.value = (
                policy.expiration_date.strftime("%Y-%m-%d") if policy.expiration_date else ""
            )
            self.location_input.value = policy.location
            self.desc_input.text = policy.description
            self._refresh_notes(policy)

    def _refresh_notes(self, policy: Policy) -> None:
        self.note_options.clear_options()
        now = datetime.now(UTC).replace(tzinfo=None)
        for n in policy_notes.list_for(policy):
            relative = humanize.naturaltime(now - n.created_at)
            preview = n.body.replace("\n", " | ")
            if len(preview) > 80:
                preview = preview[:77] + "…"
            glyph = notes.glyph_for(n.kind)
            self.note_options.add_option(
                Option(f"{glyph}  {relative}  ·  {preview}", id=n.id)
            )

    @on(Input.Submitted, "#note-add")
    def _add_note(self, event: Input.Submitted) -> None:
        body = event.value.strip()
        if not body:
            return
        kind = str(self.note_kind_select.value or notes.DEFAULT_KIND)
        with session_scope() as s:
            policy = s.get(Policy, self.policy_id)
            if policy is None:
                return
            try:
                policy_notes.add(s, policy, body, kind=kind)
            except ValueError as exc:
                self.app.notify(str(exc), severity="error")
                return
            self._refresh_notes(policy)
        self.note_input.value = ""

    @on(Button.Pressed, "#save")
    def _save_btn(self, _: Button.Pressed) -> None:
        self.action_save()

    @on(Button.Pressed, "#cancel")
    def _cancel_btn(self, _: Button.Pressed) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_save(self) -> None:
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
        pending_note = self.note_input.value.strip()
        pending_note_kind = str(self.note_kind_select.value or notes.DEFAULT_KIND)
        try:
            with session_scope() as s:
                policy = s.get(Policy, self.policy_id)
                if policy is None:
                    return
                policies.update(
                    s,
                    policy,
                    name=self.name_input.value,
                    carrier=self.carrier_input.value,
                    coverage=self.coverage_input.value,
                    policy_number=self.policy_number_input.value,
                    effective_date=eff,
                    expiration_date=exp,
                    location=self.location_input.value,
                    description=self.desc_input.text,
                )
                if pending_note:
                    policy_notes.add(s, policy, pending_note, kind=pending_note_kind)
        except PolicyDateError as exc:
            self.app.notify(str(exc), severity="error")
            return
        except ValueError as exc:
            self.app.notify(str(exc), severity="error")
            return
        self.dismiss(True)
