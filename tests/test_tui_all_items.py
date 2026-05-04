from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from openitems.config import Config
from openitems.db import engine as engine_mod
from openitems.db.engine import session_scope
from openitems.db.models import Base, Engagement, Task
from openitems.domain import engagements, tasks
from openitems.domain.tasks import TaskInput


@pytest.fixture
def multi_engagement_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Two clients + Inbox, with tasks across all five due-date bands."""
    db_file = tmp_path / "openitems.db"
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr("openitems.paths.db_path", lambda: db_file)
    monkeypatch.setattr("openitems.paths.config_path", lambda: cfg_file)
    monkeypatch.setattr("openitems.paths.exports_dir", lambda: tmp_path / "exports")

    eng = engine_mod.reset_for_tests(db_file)
    Base.metadata.create_all(eng)

    today = date(2026, 5, 4)  # Monday
    SessionLocal = engine_mod.get_sessionmaker()
    s = SessionLocal()
    acme = engagements.create(s, "Acme Co")
    globex = engagements.create(s, "Globex")
    inbox = engagements.ensure_inbox(s)

    tasks.create(
        s, acme,
        TaskInput(name="Acme overdue", bucket_name="In Progress",
                  due_date=today - timedelta(days=2)),
    )
    tasks.create(
        s, globex,
        TaskInput(name="Globex today", bucket_name="Intake", due_date=today),
    )
    tasks.create(
        s, acme,
        TaskInput(name="Acme later", bucket_name="In Progress",
                  due_date=today + timedelta(days=20)),
    )
    tasks.create(
        s, inbox,
        TaskInput(name="Inbox no-due", bucket_name="Intake"),
    )
    # Already-closed task — must not appear.
    tasks.create(
        s, acme,
        TaskInput(name="Acme already done", bucket_name="Closed",
                  due_date=today - timedelta(days=1)),
    )
    s.commit()
    s.close()

    Config(active_engagement=acme.slug).save(cfg_file)
    return {"acme_slug": acme.slug, "today": today}


@pytest.mark.asyncio
async def test_A_opens_all_items_with_cross_engagement_rows(multi_engagement_env):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "AllItemsScreen"
        screen = app.screen
        # Four open tasks across three engagements; closed one is hidden.
        assert screen.table.row_count == 4
        # Row task IDs should include tasks from at least two distinct engagements.
        with session_scope() as s:
            engagement_ids = {
                s.get(Task, tid).engagement_id for tid in screen._row_task_ids
            }
        assert len(engagement_ids) >= 2

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "MainScreen"


@pytest.mark.asyncio
async def test_c_marks_task_done_in_its_engagement(multi_engagement_env):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        screen = app.screen
        first_id = screen._row_task_ids[0]  # cursor starts at row 0
        await pilot.press("c")
        await pilot.pause()
        # Row count drops by one (closed tasks are hidden).
        assert screen.table.row_count == 3
        assert first_id not in screen._row_task_ids

    with session_scope() as s:
        task = s.get(Task, first_id)
        assert task.bucket is not None
        assert task.bucket.is_done_state is True
        # done_bucket_for picks the highest sort_order done-state — "Closed" by default.
        assert task.bucket.name == "Closed"


@pytest.mark.asyncio
async def test_filter_bar_narrows_rows_across_engagements(multi_engagement_env):
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        screen = app.screen
        assert screen.table.row_count == 4

        # Set filter text directly — Input.Changed fires on the screen handler.
        screen.filter_bar.value = "globex"
        await pilot.pause()
        assert screen.table.row_count == 1

        screen.filter_bar.value = ""
        await pilot.pause()
        assert screen.table.row_count == 4


@pytest.mark.asyncio
async def test_enter_opens_detail_modal_for_cross_engagement_task(multi_engagement_env):
    """Enter on an Inbox task (not the active engagement) should still open
    the existing TaskDetailScreen and edits should persist."""
    from openitems.tui.app import OpenItemsApp

    app = OpenItemsApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("A")
        await pilot.pause()
        screen = app.screen
        # Find the Inbox task ("Inbox no-due") — it's in the no_due band.
        with session_scope() as s:
            inbox_task = s.scalars(
                select(Task).join(Engagement).where(Engagement.is_inbox.is_(True))
            ).one()
            inbox_task_id = inbox_task.id
        target_row = screen._row_task_ids.index(inbox_task_id)
        screen.table.move_cursor(row=target_row)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TaskDetailScreen"
        app.screen.name_input.value = "Inbox renamed via plate"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "AllItemsScreen"

    with session_scope() as s:
        task = s.get(Task, inbox_task_id)
        assert task.name == "Inbox renamed via plate"
