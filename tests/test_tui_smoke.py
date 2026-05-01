from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from openitems.config import Config
from openitems.db import engine as engine_mod
from openitems.db.models import Base
from openitems.domain import checklists, engagements, tasks
from openitems.domain.tasks import TaskInput


@pytest.fixture
def app_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point all paths at a tmp dir so the TUI app boots in isolation."""
    db_file = tmp_path / "openitems.db"
    cfg_file = tmp_path / "config.toml"

    monkeypatch.setattr("openitems.paths.db_path", lambda: db_file)
    monkeypatch.setattr("openitems.paths.config_path", lambda: cfg_file)
    monkeypatch.setattr("openitems.paths.exports_dir", lambda: tmp_path / "exports")

    eng = engine_mod.reset_for_tests(db_file)
    Base.metadata.create_all(eng)

    SessionLocal = engine_mod.get_sessionmaker()
    s = SessionLocal()
    e = engagements.create(s, "Acme Co")
    today = date(2026, 5, 1)
    t = tasks.create(
        s,
        e,
        TaskInput(
            name="Migrate auth flow",
            priority="Urgent",
            due_date=today - timedelta(days=3),
            labels=["api", "sec"],
            bucket_name="In Progress",
        ),
    )
    checklists.add(s, t, "spike token issuer", completed=True)
    checklists.add(s, t, "draft RFC", completed=False)
    s.commit()
    s.close()

    Config(active_engagement=e.slug).save(cfg_file)
    return {"slug": e.slug, "today": today}


@pytest.mark.asyncio
async def test_app_boots_with_active_engagement(app_environment):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        # MainScreen is on top, no engagement switcher modal
        assert app.screen.__class__.__name__ == "MainScreen"
        screen = app.screen
        assert screen._engagement_slug == app_environment["slug"]
        # Items table should have one row
        assert screen.items_pane.table.row_count == 1
        # Titlebar mentions the engagement and overdue count
        assert "Acme Co" in str(screen.titlebar._engagement_label.render())
        assert "1 overdue" in str(screen.titlebar._counts_label.render())


@pytest.mark.asyncio
async def test_advance_through_workflow_then_delete_and_undo(app_environment):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        # Seeded task starts in "In Progress" (per fixture); advancing twice
        # walks In Progress → In Review → Done. At Done it should drop out
        # of the open-items table.
        assert screen.items_pane.table.row_count == 1
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert screen.items_pane.table.row_count == 0

        # Reset back to In Progress through the API to exercise delete/undo.
        from sqlalchemy import select

        from openitems.db.engine import session_scope
        from openitems.db.models import Engagement
        from openitems.domain import buckets as buckets_mod
        from openitems.domain import tasks as tasks_mod

        with session_scope() as s:
            engagement = s.scalars(select(Engagement)).first()
            all_t = tasks_mod.list_for(s, engagement, include_completed=True)
            ip = next(b for b in buckets_mod.list_for(s, engagement) if b.name == "In Progress")
            tasks_mod.update(s, all_t[0], bucket_id=ip.id)

        screen._reload_active_engagement()
        await pilot.pause()
        assert screen.items_pane.table.row_count == 1

        # Delete then undo
        await pilot.press("d")
        await pilot.pause()
        assert screen.items_pane.table.row_count == 0
        await pilot.press("u")
        await pilot.pause()
        assert screen.items_pane.table.row_count == 1


@pytest.mark.asyncio
async def test_detail_modal_adds_note(app_environment):
    from sqlalchemy import select

    from openitems.db.engine import session_scope
    from openitems.db.models import Task, TaskNote
    from openitems.tui.app import OpenItemsApp
    from openitems.tui.screens.task_detail import TaskDetailScreen

    with session_scope() as s:
        task_id = s.scalars(select(Task.id)).first()

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(TaskDetailScreen(task_id))
        await pilot.pause()
        screen = app.screen
        screen.note_input.value = "kicked off security review"
        await screen.note_input.action_submit()
        await pilot.pause()

    with session_scope() as s:
        rows = s.scalars(select(TaskNote)).all()
        assert [n.body for n in rows] == ["kicked off security review"]

    # The items-pane name cell should now carry the note-count marker
    # and the detail-pane body should mention the note text.
    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        screen._reload_active_engagement()
        await pilot.pause()
        name_cell = screen.items_pane.table.get_row_at(0)[1]
        assert "✎1" in str(name_cell)
        body_group = screen.detail_pane._body._Static__content
        body_render = "\n".join(str(r) for r in body_group.renderables)
        assert "kicked off security review" in body_render
        assert "─ notes" in body_render


@pytest.mark.asyncio
async def test_detail_modal_saves_due_date_via_ctrl_s(app_environment):
    from datetime import date

    from sqlalchemy import select

    from openitems.db.engine import session_scope
    from openitems.db.models import Task
    from openitems.tui.app import OpenItemsApp
    from openitems.tui.screens.task_detail import TaskDetailScreen

    with session_scope() as s:
        task_id = s.scalars(select(Task.id)).first()

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(TaskDetailScreen(task_id))
        await pilot.pause()
        screen = app.screen
        screen.due_input.value = "7/1"
        await pilot.press("ctrl+s")
        await pilot.pause()

    with session_scope() as s:
        task = s.get(Task, task_id)
        assert task.due_date == date(2026, 7, 1)


@pytest.mark.asyncio
async def test_detail_modal_persists_pending_note_on_save(app_environment):
    """Regression: typing a note in the detail modal and pressing ^S without
    first pressing Enter on the note input must still persist the note."""
    from sqlalchemy import select

    from openitems.db.engine import session_scope
    from openitems.db.models import Task, TaskNote
    from openitems.tui.app import OpenItemsApp
    from openitems.tui.screens.task_detail import TaskDetailScreen

    with session_scope() as s:
        task_id = s.scalars(select(Task.id)).first()

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.push_screen(TaskDetailScreen(task_id))
        await pilot.pause()
        screen = app.screen
        screen.note_input.value = "this should still save on ^S"
        screen.checklist_input.value = "and this checklist item too"
        await pilot.press("ctrl+s")
        await pilot.pause()

    with session_scope() as s:
        rows = s.scalars(select(TaskNote)).all()
        assert [n.body for n in rows] == ["this should still save on ^S"]


@pytest.mark.asyncio
async def test_n_keybind_opens_quick_note_and_saves(app_environment):
    from sqlalchemy import select

    from openitems.db.engine import session_scope
    from openitems.db.models import TaskNote
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "QuickNoteScreen"
        app.screen.body_input.text = "captured a thought from the field"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "MainScreen"

    with session_scope() as s:
        rows = s.scalars(select(TaskNote)).all()
        assert [n.body for n in rows] == ["captured a thought from the field"]


@pytest.mark.asyncio
async def test_help_modal_opens_and_closes(app_environment):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HelpScreen"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "MainScreen"
