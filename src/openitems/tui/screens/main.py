from __future__ import annotations

from collections import Counter
from datetime import date

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input

from openitems.db.engine import session_scope
from openitems.db.models import Task
from openitems.domain import audit, buckets as buckets_mod, checklists, engagements, tasks
from openitems.domain.constants import cycle_priority
from openitems.domain.search import TaskFilter, apply
from openitems.domain.tasks import (
    high_priority_count,
    is_completed,
    overdue_count,
    progress_summary,
)
from openitems.domain.text import parse_labels
from openitems.tui.widgets.bucket_pane import BucketPane, BucketStat
from openitems.tui.widgets.detail_pane import DetailPane
from openitems.tui.widgets.filter_bar import FilterBar
from openitems.tui.widgets.items_pane import ItemsPane
from openitems.tui.widgets.status_bar import StatusBar
from openitems.tui.widgets.titlebar import Titlebar


class MainScreen(Screen):
    BINDINGS = [
        Binding("tab", "cycle_pane(1)", "next pane", show=False),
        Binding("shift+tab", "cycle_pane(-1)", "prev pane", show=False),
        Binding("j", "move_down", "down", show=False),
        Binding("k", "move_up", "up", show=False),
        Binding("g", "top", "top", show=False),
        Binding("G", "bottom", "bottom", show=False),
        Binding("a", "new_task", "add"),
        Binding("e,enter", "edit_task", "edit"),
        Binding("n", "add_note", "note"),
        Binding("d", "delete_task", "delete"),
        Binding("s", "advance_bucket", "advance"),
        Binding("p", "cycle_priority", "priority"),
        Binding("space", "toggle_check", "check"),
        Binding("slash", "focus_filter", "filter"),
        Binding("escape", "blur_filter", "leave filter", show=False, priority=True),
        Binding("u", "undo", "undo"),
        Binding("x", "export", "export"),
        Binding("X", "quick_export", "quick-export"),
        Binding("E", "switch_engagement", "engagement"),
        Binding("question_mark", "help", "help"),
        Binding("q", "quit", "quit"),
        *[Binding(str(n), f"jump_bucket({n})", show=False) for n in range(1, 10)],
    ]

    PANE_ORDER = ("bucket-pane", "items-pane", "detail-pane")

    def __init__(self) -> None:
        super().__init__()
        self.titlebar = Titlebar()
        self.bucket_pane = BucketPane()
        self.items_pane = ItemsPane()
        self.detail_pane = DetailPane()
        self.status_bar = StatusBar()
        self.filter_bar = FilterBar()
        self._undo_stack = audit.UndoStack()
        self._filter = TaskFilter()
        self._engagement_slug: str | None = None
        self._bucket_names: list[str] = []

    def compose(self) -> ComposeResult:
        yield self.titlebar
        yield self.filter_bar
        with Horizontal(id="main-stage"):
            yield self.bucket_pane
            yield self.items_pane
            yield self.detail_pane
        yield self.status_bar

    def on_mount(self) -> None:
        self._reload_active_engagement()
        self._focus_pane("items-pane")

    # ── data loading ──────────────────────────────────────────────────

    def set_engagement(self, slug: str | None) -> None:
        self._engagement_slug = slug
        self._reload_active_engagement()

    def _reload_active_engagement(self) -> None:
        if not self._engagement_slug:
            self.titlebar.set_engagement(None)
            self.titlebar.set_counts(open_count=0, overdue=0, high=0, done=0, total=0)
            self.bucket_pane.populate(total=0, done=0, buckets=[], tags=[])
            self.items_pane.populate([])
            self.detail_pane.show_empty()
            return
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, self._engagement_slug)
            if engagement is None:
                self.set_engagement(None)
                return
            all_tasks = tasks.list_for(s, engagement, include_completed=True)
            open_tasks = [t for t in all_tasks if not is_completed(t)]
            today = date.today()

            workflow = buckets_mod.list_for(s, engagement)
            self._bucket_names = [b.name for b in workflow]
            stats: list[BucketStat] = []
            for b in workflow:
                bucket_tasks = [t for t in all_tasks if t.bucket_id == b.id]
                stats.append(
                    BucketStat(
                        name=b.name,
                        total=len(bucket_tasks),
                        done=sum(1 for t in bucket_tasks if is_completed(t)),
                        is_done_state=b.is_done_state,
                    )
                )

            tag_counts: Counter[str] = Counter()
            for t in open_tasks:
                for label in parse_labels(t.labels):
                    tag_counts[label] += 1

            done, total = progress_summary(all_tasks)
            self.titlebar.set_engagement(engagement.name)
            self.titlebar.set_counts(
                open_count=len(open_tasks),
                overdue=overdue_count(open_tasks, today),
                high=high_priority_count(open_tasks),
                done=done,
                total=total,
            )
            self.bucket_pane.populate(
                total=total,
                done=done,
                buckets=stats,
                tags=sorted(tag_counts.items()),
                filter_states={
                    "overdue_only": self._filter.overdue_only,
                    "unassigned": self._filter.unassigned_only,
                },
            )
            # Default visible set: hide done-state buckets unless the user
            # explicitly filtered to one. Otherwise the open-items view stays
            # focused on what actually needs attention.
            base = (
                all_tasks
                if self._filter.bucket_name
                and any(b.name == self._filter.bucket_name and b.is_done_state for b in workflow)
                else open_tasks
            )
            visible = apply(self._filter, base)
            self.items_pane.populate(visible, today=today)
            self.detail_pane.show_task(self.items_pane.selected_task, today=today)

    # ── pane focus model ──────────────────────────────────────────────

    def _focus_pane(self, pane_id: str) -> None:
        for pid in self.PANE_ORDER:
            try:
                pane = self.query_one(f"#{pid}")
            except Exception:
                continue
            pane.set_class(pid == pane_id, "-focused")
        if pane_id == "bucket-pane":
            self.bucket_pane.focus_list()
        elif pane_id == "items-pane":
            self.items_pane.table.focus()
        elif pane_id == "detail-pane":
            self.detail_pane.focus()

    def action_cycle_pane(self, direction: int) -> None:
        focused = next(
            (pid for pid in self.PANE_ORDER if self.query_one(f"#{pid}").has_class("-focused")),
            self.PANE_ORDER[1],
        )
        idx = (self.PANE_ORDER.index(focused) + direction) % len(self.PANE_ORDER)
        self._focus_pane(self.PANE_ORDER[idx])

    # ── messages from child panes ─────────────────────────────────────

    @on(BucketPane.SelectionChanged)
    def _on_bucket_selection(self, event: BucketPane.SelectionChanged) -> None:
        sel = event.selection
        if sel.kind == "all":
            self._filter = TaskFilter(
                overdue_only=self._filter.overdue_only,
                unassigned_only=self._filter.unassigned_only,
            )
        elif sel.kind == "bucket":
            self._filter = TaskFilter(
                bucket_name=sel.value,
                overdue_only=self._filter.overdue_only,
                unassigned_only=self._filter.unassigned_only,
            )
        elif sel.kind == "tag":
            self._filter = TaskFilter(
                tags=(sel.value,) if sel.value else (),
                overdue_only=self._filter.overdue_only,
                unassigned_only=self._filter.unassigned_only,
            )
        elif sel.kind == "filter":
            if sel.value == "overdue_only":
                self._filter = TaskFilter(
                    bucket_name=self._filter.bucket_name,
                    tags=self._filter.tags,
                    overdue_only=not self._filter.overdue_only,
                    unassigned_only=self._filter.unassigned_only,
                )
            elif sel.value == "unassigned":
                self._filter = TaskFilter(
                    bucket_name=self._filter.bucket_name,
                    tags=self._filter.tags,
                    overdue_only=self._filter.overdue_only,
                    unassigned_only=not self._filter.unassigned_only,
                )
        self._reload_active_engagement()

    @on(ItemsPane.TaskFocused)
    def _on_task_focused(self, event: ItemsPane.TaskFocused) -> None:
        if event.task_id is None:
            self.detail_pane.show_empty()
            return
        with session_scope() as s:
            task = s.get(Task, event.task_id)
            self.detail_pane.show_task(task)

    # ── actions ───────────────────────────────────────────────────────

    def _selected_task_id(self) -> str | None:
        t = self.items_pane.selected_task
        return t.id if t else None

    def action_move_down(self) -> None:
        self._send_to_focused("down")

    def action_move_up(self) -> None:
        self._send_to_focused("up")

    def action_top(self) -> None:
        self._send_to_focused("home")

    def action_bottom(self) -> None:
        self._send_to_focused("end")

    def _send_to_focused(self, key: str) -> None:
        # Forward to the focused widget — Textual's bindings on lists already
        # handle home/end/up/down.
        focused = self.app.focused
        if focused is None:
            return
        from textual.events import Key

        focused.post_message(Key(key=key, character=None))

    def action_new_task(self) -> None:
        if not self._engagement_slug:
            self.app.notify("Pick an engagement first (E).", severity="warning")
            return
        from openitems.tui.screens.new_task import NewTaskScreen

        def _after(result: bool) -> None:
            if result:
                self._reload_active_engagement()

        self.app.push_screen(NewTaskScreen(self._engagement_slug), _after)

    def action_edit_task(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        from openitems.tui.screens.task_detail import TaskDetailScreen

        def _after(result: bool) -> None:
            if result:
                self._reload_active_engagement()

        self.app.push_screen(TaskDetailScreen(task_id), _after)

    def action_add_note(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        from openitems.tui.screens.quick_note import QuickNoteScreen

        def _after(result: bool) -> None:
            if result:
                self._reload_active_engagement()

        self.app.push_screen(QuickNoteScreen(task_id), _after)

    def action_delete_task(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            tasks.soft_delete(s, task)
            self._undo_stack.push(audit.make_restore_task(task.id, task.name))
        self.app.notify("Deleted (press u to undo).")
        self._reload_active_engagement()

    def action_undo(self) -> None:
        action = self._undo_stack.pop()
        if action is None:
            self.app.notify("Nothing to undo.", severity="warning")
            return
        with session_scope() as s:
            action.apply(s)
        self.app.notify(action.description)
        self._reload_active_engagement()

    def action_advance_bucket(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            tasks.advance_bucket(s, task)
            new_bucket = task.bucket.name if task.bucket else "(no bucket)"
        self.app.notify(f"→ {new_bucket}")
        self._reload_active_engagement()

    def action_cycle_priority(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            tasks.update(s, task, priority=cycle_priority(task.priority))
        self._reload_active_engagement()

    def action_toggle_check(self) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            for c in task.checklist_items:
                if c.deleted_at is None and not c.completed:
                    checklists.toggle(s, c)
                    break
        self._reload_active_engagement()

    def action_export(self) -> None:
        if not self._engagement_slug:
            self.app.notify("Pick an engagement first (E).", severity="warning")
            return
        from openitems.tui.screens.export_wizard import ExportWizardScreen

        self.app.push_screen(ExportWizardScreen(self._engagement_slug))

    def action_quick_export(self) -> None:
        if not self._engagement_slug:
            return
        from openitems.tui.screens.export_wizard import quick_export

        out = quick_export(self._engagement_slug)
        if out is not None:
            self.app.notify(f"Exported → {out}")

    def action_switch_engagement(self) -> None:
        from openitems.tui.screens.engagement_switcher import EngagementSwitcher

        def _after(slug: str | None) -> None:
            if slug:
                self.set_engagement(slug)

        self.app.push_screen(EngagementSwitcher(), _after)

    def action_help(self) -> None:
        from openitems.tui.screens.help import HelpScreen

        self.app.push_screen(HelpScreen())

    def action_focus_filter(self) -> None:
        self.filter_bar.focus()

    def action_blur_filter(self) -> None:
        if self.focused is self.filter_bar:
            self._focus_pane("items-pane")

    def action_jump_bucket(self, idx: int) -> None:
        if not self._bucket_names:
            return
        if 1 <= idx <= len(self._bucket_names):
            target = self._bucket_names[idx - 1]
            self._filter = TaskFilter(
                bucket_name=target,
                overdue_only=self._filter.overdue_only,
                unassigned_only=self._filter.unassigned_only,
            )
            self._reload_active_engagement()
            self._focus_pane("items-pane")

    @on(Input.Changed, "#filter-bar")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._filter = TaskFilter(
            bucket_name=self._filter.bucket_name,
            tags=self._filter.tags,
            overdue_only=self._filter.overdue_only,
            unassigned_only=self._filter.unassigned_only,
            text=event.value,
        )
        self._reload_active_engagement()
