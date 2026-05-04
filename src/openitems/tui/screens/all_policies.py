"""Cross-engagement renewal radar.

Reachable from MainScreen via ``R`` (or from PoliciesScreen via ``R``).
Lists policies with an expiration date across every active engagement,
sorted by expiration ascending. Capped to a 120-day horizon plus everything
already lapsed so the table stays focused on the next quarter's renewals.
"""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Static

from openitems.db.engine import session_scope
from openitems.db.models import Policy
from openitems.domain import policies, tag_palette, triage
from openitems.tui import palette

_HORIZON_DAYS = 120
_ENGAGEMENT_WIDTH = 18


class AllPoliciesScreen(Screen):
    """Read-many / edit-in-place view of every active engagement's policies."""

    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("e", "edit_policy", "edit"),
        Binding("d", "delete_policy", "delete"),
        Binding("j", "move_down", "down", show=False),
        Binding("k", "move_up", "up", show=False),
        Binding("g", "top", "top", show=False),
        Binding("G", "bottom", "bottom", show=False),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
    ]

    DEFAULT_CSS = """
    AllPoliciesScreen #all-pol-titlebar {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    AllPoliciesScreen #all-pol-titlebar .heading {
        color: #5ee5e5;
        text-style: bold;
    }
    AllPoliciesScreen #all-pol-table-wrap {
        height: 1fr;
        background: #251f38;
        border: round #ff8a3a;
        padding: 0 1;
    }
    AllPoliciesScreen #all-pol-status {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.heading = Static("[b]renewal radar[/b]", classes="heading")
        self.table = DataTable(zebra_stripes=False, header_height=1, cursor_type="row")
        self.status = Static(_status_keys(), id="all-pol-status")
        self._row_policy_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static(id="all-pol-titlebar")
        yield self.heading
        with Vertical(id="all-pol-table-wrap"):
            yield self.table
        yield self.status

    def on_mount(self) -> None:
        self.table.add_columns(
            "expires", "in", "client", "policy", "carrier", "coverage", "policy #"
        )
        self.reload()
        self.table.focus()

    def reload(self) -> None:
        today = date.today()
        with session_scope() as s:
            rows = triage.list_policies_across_engagements(
                s, today=today, horizon_days=_HORIZON_DAYS
            )
            self._populate_table(rows)

    def _populate_table(self, rows: list[triage.PolicyRow]) -> None:
        self.table.clear()
        self._row_policy_ids = []
        lapsed = sum(1 for r in rows if r.is_lapsed)
        soon = sum(1 for r in rows if r.days_to_renewal is not None and 0 <= r.days_to_renewal <= 30)
        for row in rows:
            p = row.policy
            self._row_policy_ids.append(p.id)
            d = row.days_to_renewal
            self.table.add_row(
                _expiration_cell(p.expiration_date, d),
                _renewal_cell(d),
                _engagement_cell(row.engagement.name),
                Text(p.name, style=palette.FG),
                Text(p.carrier or "—", style=palette.DIM if not p.carrier else palette.FG),
                _coverage_cell(p.coverage),
                Text(p.policy_number or "—", style=palette.DIM if not p.policy_number else palette.FG),
            )
        if self._row_policy_ids:
            self.table.move_cursor(row=0)
        total = len(rows)
        parts = [f"{total} in window"]
        if lapsed:
            parts.append(f"{lapsed} lapsed")
        if soon:
            parts.append(f"{soon} ≤30d")
        self.heading.update(
            f"[b]renewal radar[/b]  ·  next {_HORIZON_DAYS}d  ·  {' · '.join(parts)}"
        )

    def _selected_policy_id(self) -> str | None:
        if not self._row_policy_ids:
            return None
        row = self.table.cursor_row
        if row < 0 or row >= len(self._row_policy_ids):
            return None
        return self._row_policy_ids[row]

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_edit_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        from openitems.tui.screens.policy_detail import PolicyDetailScreen

        def _after(result: bool) -> None:
            if result:
                self.reload()

        self.app.push_screen(PolicyDetailScreen(policy_id), _after)

    def action_delete_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        with session_scope() as s:
            policy = s.get(Policy, policy_id)
            if policy is None:
                return
            policies.soft_delete(s, policy)
        self.app.notify("Policy deleted.")
        self.reload()

    def action_move_down(self) -> None:
        self._forward_key("down")

    def action_move_up(self) -> None:
        self._forward_key("up")

    def action_top(self) -> None:
        self._forward_key("home")

    def action_bottom(self) -> None:
        self._forward_key("end")

    def _forward_key(self, key: str) -> None:
        focused = self.app.focused
        if focused is None:
            return
        from textual.events import Key

        focused.post_message(Key(key=key, character=None))

    def action_help(self) -> None:
        from openitems.tui.screens.help import HelpScreen

        self.app.push_screen(HelpScreen())

    @on(DataTable.RowSelected)
    def _on_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_edit_policy()


def _expiration_cell(d: date | None, days: int | None) -> Text:
    if d is None:
        return Text("—", style=palette.DIM)
    text = Text(d.strftime("%Y-%m-%d"))
    if days is None:
        text.style = palette.FG
    elif days < 0:
        text.style = f"bold {palette.RED}"
    elif days <= 30:
        text.style = f"bold {palette.ACCENT}"
    else:
        text.style = palette.FG
    return text


def _renewal_cell(days: int | None) -> Text:
    if days is None:
        return Text("—", style=palette.DIM)
    if days < 0:
        return Text(f"lapsed {-days}d", style=f"bold {palette.RED}")
    if days == 0:
        return Text("today", style=f"bold {palette.ACCENT}")
    if days <= 30:
        return Text(f"{days}d", style=f"bold {palette.ACCENT}")
    return Text(f"{days}d", style=palette.DIM)


def _engagement_cell(name: str) -> Text:
    if len(name) > _ENGAGEMENT_WIDTH:
        name = name[: _ENGAGEMENT_WIDTH - 1] + "…"
    return Text(name, style=palette.CYAN)


def _coverage_cell(coverage: str) -> Text:
    if not coverage:
        return Text("—", style=palette.DIM)
    color_key = tag_palette.color_for(coverage)
    hex_ = palette.TAG_COLORS.get(color_key, palette.FG)
    return Text(coverage, style=hex_)


def _status_keys() -> str:
    return "  ".join(
        [
            "[b]Enter[/b]/e edit",
            "[b]d[/b] delete",
            "[b]Esc[/b] back",
        ]
    )
