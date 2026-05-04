from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import date

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Input

from openitems.config import Config
from openitems.db.engine import session_scope
from openitems.db.models import Task
from openitems.domain import audit, buckets as buckets_mod, checklists, engagements, tasks
from openitems.domain.constants import cycle_priority
from openitems.domain.dates import start_of_week
from openitems.domain.search import TaskFilter, apply
from openitems.domain.tasks import (
    high_priority_count,
    is_completed,
    is_in_auto_close,
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
        Binding("i", "jot", "jot"),
        Binding("L", "activity_log", "log"),
        Binding("M", "move_task", "move"),
        Binding("d", "delete_task", "delete"),
        Binding("s", "advance_bucket", "advance"),
        Binding("p", "cycle_priority", "priority"),
        Binding("f", "toggle_focus", "focus"),
        Binding("space", "toggle_check", "check"),
        Binding("slash", "focus_filter", "filter"),
        Binding("escape", "blur_filter", "leave filter", show=False, priority=True),
        Binding("u", "undo", "undo"),
        Binding("x", "export", "export"),
        Binding("X", "quick_export", "quick-export"),
        Binding("D", "digest", "digest"),
        Binding("E", "switch_engagement", "engagement"),
        Binding("A", "all_items", "plate"),
        Binding("o", "open_engagement_url", "open ↗"),
        Binding("O", "open_task_url", "open task ↗"),
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
        self._maybe_show_planning_banner()
        # Promote any Resolved tasks past their hold window once an hour.
        # First tick fires after the interval, not on mount — by design.
        self.set_interval(3600, self._run_auto_close_sweep)

    def _run_auto_close_sweep(self) -> None:
        if not self._engagement_slug:
            return
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, self._engagement_slug)
            if engagement is None:
                return
            promoted = tasks.sweep_auto_close(s, engagement)
        if promoted:
            self.app.notify(
                f"Auto-closed {promoted} resolved item{'s' if promoted != 1 else ''}.",
                title="Sweep",
                timeout=4,
            )
            self._reload_active_engagement()

    def _maybe_show_planning_banner(self) -> None:
        """F16: nudge the user to plan the week if it's Monday and they haven't.

        Cleared once they press `f` on any task this week (which writes
        config.last_planned_at).
        """
        today = date.today()
        if today.weekday() != 0:  # Monday only
            return
        cfg = Config.load()
        already_planned_this_week = False
        if cfg.last_planned_at:
            try:
                last = date.fromisoformat(cfg.last_planned_at)
                already_planned_this_week = last >= start_of_week(today)
            except ValueError:
                pass
        if already_planned_this_week:
            return
        self.app.notify(
            f"Week of {today.strftime('%b %-d')} — press f on tasks to mark them in focus this week.",
            title="Plan the week",
            timeout=10,
        )

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
            # Resolved tasks are technically completed but still aging out —
            # surface them in the default view so the user sees the
            # countdown chip without having to navigate to that bucket.
            visible_default = [
                t for t in all_tasks
                if not is_completed(t) or is_in_auto_close(t)
            ]
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
            self.titlebar.set_engagement(
                engagement.name, has_url=bool(engagement.homepage_url)
            )
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
                    "focus_only": self._filter.focus_only,
                },
            )
            # Default visible set: open + Resolved (auto-close) tasks. Hide
            # terminal done buckets (Closed, Dropped) unless the user
            # explicitly filtered to one.
            base = (
                all_tasks
                if self._filter.bucket_name
                and any(b.name == self._filter.bucket_name and b.is_done_state for b in workflow)
                else visible_default
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
        # Persist toggle-state across selections, but reset bucket/tag scopes
        # when picking a new scope.
        if sel.kind == "all":
            self._filter = replace(self._filter, bucket_name=None, tags=())
        elif sel.kind == "bucket":
            self._filter = replace(self._filter, bucket_name=sel.value, tags=())
        elif sel.kind == "tag":
            self._filter = replace(
                self._filter,
                bucket_name=None,
                tags=(sel.value,) if sel.value else (),
            )
        elif sel.kind == "filter":
            if sel.value == "overdue_only":
                self._filter = replace(
                    self._filter, overdue_only=not self._filter.overdue_only
                )
            elif sel.value == "unassigned":
                self._filter = replace(
                    self._filter,
                    unassigned_only=not self._filter.unassigned_only,
                )
            elif sel.value == "focus_only":
                self._filter = replace(
                    self._filter, focus_only=not self._filter.focus_only
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

    def action_move_task(self) -> None:
        """Move the selected task to a different engagement (lands in its Backlog)."""
        task_id = self._selected_task_id()
        if not task_id:
            return
        from openitems.tui.screens.engagement_picker import EngagementPickerScreen

        def _after(slug: str | None) -> None:
            if not slug:
                return
            with session_scope() as s:
                task = s.get(Task, task_id)
                target = engagements.get_by_slug(s, slug)
                if task is None or target is None:
                    return
                if task.engagement_id == target.id:
                    self.app.notify("Already in that engagement.", severity="warning")
                    return
                tasks.move_to_engagement(s, task, target)
            self.app.notify(f"→ {slug}")
            self._reload_active_engagement()

        self.app.push_screen(
            EngagementPickerScreen(
                prompt="move to engagement",
                exclude_slug=self._engagement_slug,
            ),
            _after,
        )

    def action_jot(self) -> None:
        """Brain-dump a task into the Inbox engagement without switching to it."""
        from openitems.tui.screens.jot import JotScreen

        def _after(result: bool) -> None:
            if not result:
                return
            # Always reload — cheap, and avoids fragile slug comparisons.
            # (The inbox slug isn't always literally "inbox": if the user
            # already had an engagement named Inbox, ensure_inbox lands
            # on "inbox-2" or similar, since `is_inbox` is the source of
            # truth, not slug.)
            self._reload_active_engagement()

        self.app.push_screen(JotScreen(), _after)

    def action_activity_log(self) -> None:
        if not self._engagement_slug:
            self.app.notify("Pick an engagement first (E).", severity="warning")
            return
        from openitems.tui.screens.activity_log import ActivityLogScreen
        from openitems.tui.screens.task_detail import TaskDetailScreen

        def _after(picked_task_id: str | None) -> None:
            if not picked_task_id:
                return
            # User selected a note → open its parent task. Reload after.
            def _after_detail(result: bool) -> None:
                if result:
                    self._reload_active_engagement()

            self.app.push_screen(TaskDetailScreen(picked_task_id), _after_detail)

        self.app.push_screen(ActivityLogScreen(self._engagement_slug), _after)

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

    def action_toggle_focus(self) -> None:
        """Toggle 'this week' focus on the selected task; refreshes the list."""
        task_id = self._selected_task_id()
        if not task_id:
            return
        today = date.today()
        with session_scope() as s:
            task = s.get(Task, task_id)
            if task is None:
                return
            tasks.toggle_focus(s, task, today=today)
            on = task.focus_week is not None
        # F16: stamp the planning ritual so the Monday banner clears once
        # the user has flagged anything this week.
        cfg = Config.load()
        cfg.last_planned_at = today.isoformat()
        cfg.save()
        self.app.notify("★ in focus this week" if on else "focus cleared")
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

    def action_digest(self) -> None:
        """Generate a Markdown handoff digest covering this week (Monday →
        today) and write it next to the DB. Opens via the OS default app.
        """
        if not self._engagement_slug:
            self.app.notify("Pick an engagement first (E).", severity="warning")
            return
        import subprocess
        import sys

        from openitems.domain import notes as notes_mod
        from openitems.domain.dates import parse_since
        from openitems.export.digest import render_digest
        from openitems.paths import exports_dir

        today = date.today()
        since_date = parse_since("monday", today=today)
        with session_scope() as s:
            engagement = engagements.get_by_slug(s, self._engagement_slug)
            if engagement is None:
                self.app.notify("Engagement gone.", severity="error")
                return
            all_tasks = tasks.list_for(s, engagement, include_completed=True)
            all_notes = notes_mod.list_for_engagement(s, engagement)
            body = render_digest(
                engagement,
                all_tasks,
                all_notes,
                since=since_date,
                until=today,
                today=today,
            )
        target = (
            exports_dir() / f"{self._engagement_slug}-digest-{today.strftime('%Y-%m-%d')}.md"
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
        except OSError as exc:
            self.app.notify(f"Couldn't write digest: {exc}", severity="error")
            return
        self.app.notify(f"Digest → {target}")
        # Open in the OS default app (Markdown viewer / editor).
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        elif sys.platform == "win32":  # pragma: no cover
            subprocess.run(["start", "", str(target)], shell=True, check=False)
        else:  # pragma: no cover
            subprocess.run(["xdg-open", str(target)], check=False)

    def action_open_engagement_url(self) -> None:
        """Open the active engagement's homepage_url in the system browser."""
        import webbrowser

        if not self._engagement_slug:
            self.app.notify("Pick an engagement first (E).", severity="warning")
            return
        with session_scope() as s:
            e = engagements.get_by_slug(s, self._engagement_slug)
            url = e.homepage_url if e else None
        if not url:
            self.app.notify(
                "No URL set. Press E, highlight the engagement, fill the URL field.",
                severity="warning",
            )
            return
        webbrowser.open(url)
        self.app.notify(f"↗ {url}")

    def action_open_task_url(self) -> None:
        """Open the selected task's external_url in the system browser."""
        import webbrowser

        task_id = self._selected_task_id()
        if not task_id:
            return
        with session_scope() as s:
            task = s.get(Task, task_id)
            url = task.external_url if task else None
        if not url:
            self.app.notify(
                "No URL on this task. Press e to set one.",
                severity="warning",
            )
            return
        webbrowser.open(url)
        self.app.notify(f"↗ {url}")

    def action_all_items(self) -> None:
        """Push the cross-engagement triage view."""
        from openitems.tui.screens.all_items import AllItemsScreen

        def _after(_: object) -> None:
            # Edits made on the all-items screen may have touched the active
            # engagement; reload so the main view reflects them.
            self._reload_active_engagement()

        self.app.push_screen(AllItemsScreen(), _after)

    def action_switch_engagement(self) -> None:
        from openitems.tui.screens.engagement_switcher import EngagementSwitcher

        def _after(slug: str | None) -> None:
            if slug:
                self.set_engagement(slug)
            else:
                # The switcher also edits engagement URLs in-place; even
                # without a slug change we must reload so the titlebar's
                # ↗ glyph reflects any URL the user just saved/cleared.
                self._reload_active_engagement()

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
            self._filter = replace(self._filter, bucket_name=target, tags=())
            self._reload_active_engagement()
            self._focus_pane("items-pane")

    @on(Input.Changed, "#filter-bar")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self._filter = replace(self._filter, text=event.value)
        self._reload_active_engagement()
