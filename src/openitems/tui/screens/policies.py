"""Engagement-scoped policy list.

Reachable from MainScreen via ``P``. Lists every live policy on the active
engagement, sorted by expiration ascending so the soonest renewal sits on
top. ``a`` adds, ``e`` / Enter edits, ``d`` soft-deletes.
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
from openitems.domain import engagements, policies, tag_palette
from openitems.tui import palette


class PoliciesScreen(Screen):
    """Engagement-scoped policy list (live, sorted by expiration ascending)."""

    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("a", "new_policy", "add"),
        Binding("e", "edit_policy", "edit"),
        Binding("r", "renew_policy", "renew"),
        Binding("A", "archive_policy", "archive"),
        Binding("d", "delete_policy", "delete"),
        Binding("u", "restore_policy", "restore", show=False),
        Binding("H", "toggle_history", "history"),
        Binding("i", "import_csv", "import csv"),
        Binding("x", "export_csv", "export csv"),
        Binding("j", "move_down", "down", show=False),
        Binding("k", "move_up", "up", show=False),
        Binding("g", "top", "top", show=False),
        Binding("G", "bottom", "bottom", show=False),
        Binding("R", "all_policies", "all engagements"),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
    ]

    DEFAULT_CSS = """
    PoliciesScreen #policies-titlebar {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    PoliciesScreen #policies-titlebar .heading {
        color: #5ee5e5;
        text-style: bold;
    }
    PoliciesScreen #policies-table-wrap {
        height: 1fr;
        background: #251f38;
        border: round #ff8a3a;
        padding: 0 1;
    }
    PoliciesScreen #policies-status {
        height: 1;
        background: #14111e;
        color: #8a7fa8;
        padding: 0 1;
    }
    """

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        self.heading = Static("[b]policies[/b]", classes="heading")
        self.table = DataTable(zebra_stripes=False, header_height=1, cursor_type="row")
        self.status = Static(_status_keys(history=False), id="policies-status")
        self._row_policy_ids: list[str] = []
        self._engagement_name = ""
        self._show_history = False

    def compose(self) -> ComposeResult:
        yield Static(id="policies-titlebar")
        yield self.heading
        with Vertical(id="policies-table-wrap"):
            yield self.table
        yield self.status

    def on_mount(self) -> None:
        self.table.add_columns("policy", "carrier", "coverage", "policy #", "effective", "expires", "in")
        self.reload()
        self.table.focus()

    def reload(self) -> None:
        today = date.today()
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, self.engagement_slug)
            if engagement is None:
                self.app.notify("Engagement gone.", severity="error")
                self.app.pop_screen()
                return
            self._engagement_name = engagement.name
            rows = policies.list_for(
                s,
                engagement,
                include_archived=self._show_history,
                include_deleted=self._show_history,
            )
            archived = policies.count_archived_for(s, engagement)
            self._populate_table(rows, today=today, archived_count=archived)
        self.status.update(_status_keys(history=self._show_history))

    def _populate_table(
        self, rows: list[Policy], *, today: date, archived_count: int = 0
    ) -> None:
        self.table.clear()
        self._row_policy_ids = []
        lapsed_count = 0
        renewing_soon = 0
        live_count = 0
        for p in rows:
            self._row_policy_ids.append(p.id)
            inactive = p.deleted_at is not None or p.archived_at is not None
            d = policies.days_to_renewal(p, today)
            if not inactive:
                live_count += 1
                if d is not None and d < 0:
                    lapsed_count += 1
                elif d is not None and d <= 30:
                    renewing_soon += 1
            self.table.add_row(
                _name_cell(p),
                Text(p.carrier or "—", style=palette.DIM if not p.carrier or inactive else palette.FG),
                _coverage_cell(p.coverage, dim=inactive),
                Text(
                    p.policy_number or "—",
                    style=palette.DIM if not p.policy_number or inactive else palette.FG,
                ),
                _date_cell(p.effective_date, dim=inactive),
                _expiration_cell(p.expiration_date, d, dim=inactive),
                _renewal_cell(d, dim=inactive),
            )
        if self._row_policy_ids:
            self.table.move_cursor(row=0)
        parts = [f"{live_count} polic{'y' if live_count == 1 else 'ies'}"]
        if lapsed_count:
            parts.append(f"{lapsed_count} lapsed")
        if renewing_soon:
            parts.append(f"{renewing_soon} renewing ≤30d")
        if archived_count:
            parts.append(f"{archived_count} archived")
        if self._show_history:
            parts.append("history on")
        self.heading.update(
            f"[b]policies[/b]  ·  {self._engagement_name}  ·  {' · '.join(parts)}"
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

    def action_new_policy(self) -> None:
        from openitems.tui.screens.new_policy import NewPolicyScreen

        def _after(result: bool) -> None:
            if result:
                self.reload()

        self.app.push_screen(NewPolicyScreen(self.engagement_slug), _after)

    def action_edit_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        from openitems.tui.screens.policy_detail import PolicyDetailScreen

        def _after(result: bool) -> None:
            if result:
                self.reload()

        self.app.push_screen(PolicyDetailScreen(policy_id), _after)

    def action_renew_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        from openitems.tui.screens.renew_policy import RenewPolicyScreen

        def _after(result: bool) -> None:
            if result:
                self.app.notify("Policy renewed.")
                self.reload()

        self.app.push_screen(RenewPolicyScreen(policy_id), _after)

    def action_delete_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        with session_scope() as s:
            policy = s.get(Policy, policy_id)
            if policy is None:
                return
            if policy.deleted_at is not None:
                self.app.notify("Already deleted.", severity="warning")
                return
            policies.soft_delete(s, policy)
        self.app.notify("Policy deleted (press H then u to restore).")
        self.reload()

    def action_archive_policy(self) -> None:
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        with session_scope() as s:
            policy = s.get(Policy, policy_id)
            if policy is None:
                return
            if policy.archived_at is not None:
                self.app.notify("Already archived.", severity="warning")
                return
            policies.archive(s, policy)
        self.app.notify("Policy archived.")
        self.reload()

    def action_restore_policy(self) -> None:
        if not self._show_history:
            self.app.notify("Press H to enter history mode first.", severity="warning")
            return
        policy_id = self._selected_policy_id()
        if not policy_id:
            return
        with session_scope() as s:
            policy = s.get(Policy, policy_id)
            if policy is None:
                return
            if policy.deleted_at is not None:
                policies.restore(s, policy)
                msg = "Policy restored."
            elif policy.archived_at is not None:
                policies.unarchive(s, policy)
                msg = "Policy unarchived."
            else:
                self.app.notify("Already live.", severity="warning")
                return
        self.app.notify(msg)
        self.reload()

    def action_toggle_history(self) -> None:
        self._show_history = not self._show_history
        self.app.notify(
            "Showing archived & deleted." if self._show_history else "Live policies only."
        )
        self.reload()

    def action_import_csv(self) -> None:
        from openitems.tui.screens.import_policies import ImportPoliciesScreen

        def _after(result: bool) -> None:
            if result:
                self.reload()

        self.app.push_screen(ImportPoliciesScreen(self.engagement_slug), _after)

    def action_export_csv(self) -> None:
        from datetime import datetime

        from openitems import paths
        from openitems.domain import policy_export

        with session_scope() as s:
            engagement = engagements.get_by_slug(s, self.engagement_slug)
            if engagement is None:
                self.app.notify("Engagement gone.", severity="error")
                return
            rows = policies.list_for(s, engagement)
            if not rows:
                self.app.notify("No live policies to export.", severity="warning")
                return
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = paths.exports_dir() / f"policies-{engagement.slug}-{stamp}.csv"
            try:
                policy_export.write_to(path, rows)
            except OSError as exc:
                self.app.notify(f"Export failed: {exc}", severity="error")
                return
        self.app.notify(f"Exported {len(rows)} polic{'y' if len(rows) == 1 else 'ies'} → {path}")

    def action_all_policies(self) -> None:
        from openitems.tui.screens.all_policies import AllPoliciesScreen

        def _after(_: object) -> None:
            self.reload()

        self.app.push_screen(AllPoliciesScreen(), _after)

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


def _name_cell(p: Policy) -> Text:
    if p.deleted_at is not None:
        return Text(f"[deleted] {p.name}", style=f"strike {palette.DIM}")
    if p.archived_at is not None:
        return Text(f"[archived] {p.name}", style=palette.DIM)
    return Text(p.name, style=palette.FG)


def _date_cell(d: date | None, *, dim: bool = False) -> Text:
    if d is None:
        return Text("—", style=palette.DIM)
    return Text(d.strftime("%Y-%m-%d"), style=palette.DIM if dim else palette.FG)


def _expiration_cell(d: date | None, days: int | None, *, dim: bool = False) -> Text:
    if d is None:
        return Text("—", style=palette.DIM)
    text = Text(d.strftime("%Y-%m-%d"))
    if dim:
        text.style = palette.DIM
    elif days is None:
        text.style = palette.FG
    elif days < 0:
        text.style = f"bold {palette.RED}"
    elif days <= 30:
        text.style = f"bold {palette.ACCENT}"
    else:
        text.style = palette.FG
    return text


def _renewal_cell(days: int | None, *, dim: bool = False) -> Text:
    if days is None:
        return Text("—", style=palette.DIM)
    if dim:
        return Text(f"{days}d" if days >= 0 else f"lapsed {-days}d", style=palette.DIM)
    if days < 0:
        return Text(f"lapsed {-days}d", style=f"bold {palette.RED}")
    if days == 0:
        return Text("today", style=f"bold {palette.ACCENT}")
    if days <= 30:
        return Text(f"{days}d", style=f"bold {palette.ACCENT}")
    return Text(f"{days}d", style=palette.DIM)


def _coverage_cell(coverage: str, *, dim: bool = False) -> Text:
    if not coverage:
        return Text("—", style=palette.DIM)
    if dim:
        return Text(coverage, style=palette.DIM)
    color_key = tag_palette.color_for(coverage)
    hex_ = palette.TAG_COLORS.get(color_key, palette.FG)
    return Text(coverage, style=hex_)


def _status_keys(*, history: bool) -> str:
    base = [
        "[b]a[/b] add",
        "[b]e[/b]/Enter edit",
        "[b]r[/b] renew",
        "[b]A[/b] archive",
        "[b]d[/b] delete",
        "[b]i[/b] import",
        "[b]x[/b] export",
        "[b]H[/b] " + ("hide history" if history else "history"),
    ]
    if history:
        base.append("[b]u[/b] restore")
    base.extend(["[b]R[/b] all engagements", "[b]Esc[/b] back"])
    return "  ".join(base)
