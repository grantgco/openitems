"""Engagement-level activity log: every note across every task, newest first.

When a client asks "what happened on Acme this week?" the answer used to be
"open every task and read its notes." This screen flattens those into a
single chronological feed grouped by day.

Selecting a row pushes the `TaskDetailScreen` for that note's parent task,
so you can read the full context and add a follow-up.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import humanize
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from openitems.db.engine import session_scope
from openitems.db.models import TaskNote
from openitems.domain import engagements as engagements_mod
from openitems.domain import notes as notes_mod

_NOTE_PREVIEW_CHARS = 60


class ActivityLogScreen(ModalScreen[str | None]):
    """Cross-task chronological note feed for one engagement.

    Returns the ``task_id`` of the selected note (so the parent screen can
    push a TaskDetailScreen), or ``None`` if dismissed without selection.
    """

    # Wider than the default modal; uncap the OptionList because the log
    # IS the dominant content here (the global `.modal OptionList` rule
    # caps at 10 rows, which is too small for a multi-week activity feed).
    DEFAULT_CSS = """
    ActivityLogScreen .modal {
        width: 100;
        max-width: 95%;
        max-height: 90%;
    }
    ActivityLogScreen #activity-options {
        height: auto;
        max-height: 30;
        min-height: 5;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_no_pick", "close", show=False),
        Binding("enter", "pick", "open task", show=False),
    ]

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        self._engagement_name = ""
        self._option_list = OptionList(id="activity-options")
        # task_id lookup keyed by note_id, populated in _refresh()
        self._note_to_task: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]activity log[/b]", classes="modal-title", id="activity-title")
            yield Label("[dim]press Enter to open the task · Esc to close[/dim]", classes="dim")
            yield self._option_list

    def on_mount(self) -> None:
        self._refresh()
        self._option_list.focus()

    def _refresh(self) -> None:
        with session_scope() as s:
            engagement = engagements_mod.get_by_slug(s, self.engagement_slug)
            if engagement is None:
                self.app.notify("Engagement gone.", severity="error")
                self.dismiss(None)
                return
            self._engagement_name = engagement.name
            rows = notes_mod.list_for_engagement(s, engagement)
            options = self._build_options(rows)
            self._note_to_task = {n.id: n.task_id for n in rows}

        title_widget = self.query_one("#activity-title", Label)
        title_widget.update(
            f"[b]activity log[/b]  ·  {self._engagement_name}  ·  {len(self._note_to_task)} notes"
        )
        self._option_list.clear_options()
        if options:
            self._option_list.add_options(options)
        else:
            self._option_list.add_option(
                Option(Text("no notes yet — press n on a task to add one", style="dim"), disabled=True)
            )

    def _build_options(self, rows: list[TaskNote]) -> list[Option]:
        """Group notes by day with disabled section headers between groups."""
        if not rows:
            return []
        now = datetime.now(UTC).replace(tzinfo=None)
        today = now.date()
        out: list[Option] = []
        current_group: date | None = None
        for n in rows:
            day = n.created_at.date()
            if day != current_group:
                out.append(_section_header(day, today))
                current_group = day
            out.append(_note_option(n, now))
        return out

    def action_dismiss_no_pick(self) -> None:
        self.dismiss(None)

    def action_pick(self) -> None:
        self._pick_highlighted()

    @on(OptionList.OptionSelected, "#activity-options")
    def _on_select(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id
        if not oid:
            return
        task_id = self._note_to_task.get(oid)
        if task_id is None:
            return
        self.dismiss(task_id)

    def _pick_highlighted(self) -> None:
        idx = self._option_list.highlighted
        if idx is None:
            return
        option = self._option_list.get_option_at_index(idx)
        if option.id is None:
            return
        task_id = self._note_to_task.get(option.id)
        if task_id is None:
            return
        self.dismiss(task_id)


def _section_header(day: date, today: date) -> Option:
    delta = (today - day).days
    if delta == 0:
        label = "Today"
    elif delta == 1:
        label = "Yesterday"
    elif 0 < delta < 7:
        label = day.strftime("%A")
    else:
        label = day.strftime("%a, %b %-d")
    return Option(Text(f"─ {label} ─", style="dim"), disabled=True)


def _note_option(n: TaskNote, now: datetime) -> Option:
    relative = humanize.naturaltime(now - n.created_at)
    glyph = notes_mod.glyph_for(n.kind)
    body = n.body.replace("\n", " | ")
    if len(body) > _NOTE_PREVIEW_CHARS:
        body = body[: _NOTE_PREVIEW_CHARS - 1] + "…"
    task_name = n.task.name if n.task is not None else "(unknown task)"
    if len(task_name) > 24:
        task_name = task_name[:23] + "…"
    text = Text()
    text.append(f"{glyph} ")
    text.append(relative.ljust(14), style="dim")
    text.append("  ")
    text.append(task_name.ljust(25), style="bold")
    text.append("  ")
    text.append(body)
    return Option(text, id=n.id)
