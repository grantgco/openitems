from __future__ import annotations

from datetime import date, timedelta

from openitems.domain import buckets, engagements, notes, tasks
from openitems.domain.tasks import TaskInput
from openitems.export.digest import render_digest


def test_digest_renders_empty_engagement(session):
    e = engagements.create(session, "Acme")
    today = date(2026, 5, 6)
    body = render_digest(
        e, [], [], since=today - timedelta(days=7), until=today, today=today
    )
    assert body.startswith("# Acme — ")
    assert "**Status:** 0 open · 0 overdue · 0 high-priority" in body
    assert "_No activity in this range._" in body


def test_digest_status_counts_correctly(session):
    e = engagements.create(session, "Acme")
    today = date(2026, 5, 6)
    tasks.create(session, e, TaskInput(name="A", priority="Urgent"))
    tasks.create(session, e, TaskInput(name="B", priority="Low"))
    tasks.create(
        session,
        e,
        TaskInput(name="C", priority="Important", due_date=today - timedelta(days=2)),
    )
    body = render_digest(
        e,
        tasks.list_for(session, e, include_completed=True),
        notes.list_for_engagement(session, e),
        since=today - timedelta(days=7),
        until=today,
        today=today,
    )
    assert "**Status:** 3 open · 1 overdue · 2 high-priority" in body
    assert "## Overdue (1)" in body
    assert "**C**" in body


def test_digest_groups_completed_in_range(session):
    e = engagements.create(session, "Acme")
    workflow = buckets.list_for(session, e)
    done = next(b for b in workflow if b.is_done_state)
    today = date(2026, 5, 6)
    t = tasks.create(session, e, TaskInput(name="Migrate auth"))
    tasks.update(session, t, bucket_id=done.id)
    session.flush()
    body = render_digest(
        e,
        tasks.list_for(session, e, include_completed=True),
        notes.list_for_engagement(session, e),
        since=today - timedelta(days=30),
        until=today,
        today=today,
    )
    assert "## Completed (1)" in body
    assert "**Migrate auth**" in body


def test_digest_includes_activity_in_range_with_glyphs(session):
    e = engagements.create(session, "Acme")
    today = date(2026, 5, 6)
    t = tasks.create(session, e, TaskInput(name="Schedule pen-test"))
    notes.add(session, t, "phoned Jess re: cutover", kind="call")
    notes.add(session, t, "sent kickoff doc", kind="email")
    session.flush()
    body = render_digest(
        e,
        tasks.list_for(session, e, include_completed=True),
        notes.list_for_engagement(session, e),
        since=today - timedelta(days=7),
        until=today,
        today=today,
    )
    assert "## Activity (2 notes)" in body
    assert "phoned Jess" in body
    assert "sent kickoff doc" in body
    # Glyphs come from notes_mod.glyph_for; confirm at least call glyph appears
    assert "☎" in body or "call" in body


def test_digest_in_progress_attaches_last_note(session):
    e = engagements.create(session, "Acme")
    today = date(2026, 5, 6)
    t = tasks.create(session, e, TaskInput(name="Wire up CI"))
    notes.add(session, t, "weekly review w/ team", kind="meeting")
    session.flush()
    body = render_digest(
        e,
        tasks.list_for(session, e, include_completed=True),
        notes.list_for_engagement(session, e),
        since=today - timedelta(days=7),
        until=today,
        today=today,
    )
    assert "## In progress (1)" in body
    assert "weekly review w/ team" in body


def test_digest_excludes_soft_deleted_tasks(session):
    e = engagements.create(session, "Acme")
    today = date(2026, 5, 6)
    t = tasks.create(session, e, TaskInput(name="zombie"))
    tasks.soft_delete(session, t)
    session.flush()
    body = render_digest(
        e,
        tasks.list_for(session, e, include_deleted=True),
        notes.list_for_engagement(session, e),
        since=today - timedelta(days=7),
        until=today,
        today=today,
    )
    assert "zombie" not in body
