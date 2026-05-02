from __future__ import annotations

from datetime import date, timedelta

import pytest

from openitems.domain import audit, buckets, checklists, engagements, tasks
from openitems.domain.constants import cycle_priority, cycle_status
from openitems.domain.tasks import TaskInput


def _engagement(session, name: str = "Acme"):
    return engagements.create(session, name)


def test_create_engagement_slugifies_unique(session):
    a = engagements.create(session, "Acme Co")
    b = engagements.create(session, "Acme Co")
    assert a.slug == "acme-co"
    assert b.slug == "acme-co-2"


def test_create_task_validates_priority(session):
    e = _engagement(session)
    with pytest.raises(ValueError):
        tasks.create(session, e, TaskInput(name="x", priority="VeryHigh"))


def test_create_task_with_bucket_get_or_creates(session):
    e = _engagement(session)
    t1 = tasks.create(session, e, TaskInput(name="A", bucket_name="Engineering"))
    t2 = tasks.create(session, e, TaskInput(name="B", bucket_name="Engineering"))
    assert t1.bucket_id == t2.bucket_id
    assert t1.bucket is not None and t1.bucket.name == "Engineering"


def test_engagement_create_seeds_default_workflow(session):
    e = _engagement(session)
    names = [b.name for b in buckets.list_for(session, e)]
    assert names == ["Backlog", "In Progress", "In Review", "Done"]


def test_ensure_inbox_creates_once(session):
    inbox1 = engagements.ensure_inbox(session)
    inbox2 = engagements.ensure_inbox(session)
    assert inbox1.id == inbox2.id
    assert inbox1.is_inbox is True


def test_list_clients_excludes_inbox(session):
    a = engagements.create(session, "Acme")
    inbox = engagements.ensure_inbox(session)
    clients = engagements.list_clients(session)
    assert a in clients
    assert inbox not in clients
    # But list_active still returns both.
    assert inbox in engagements.list_active(session)


def test_default_workflow_done_bucket_is_done_state(session):
    e = _engagement(session)
    done = next(b for b in buckets.list_for(session, e) if b.name == "Done")
    assert done.is_done_state is True


def test_default_bucket_assigned_when_unspecified(session):
    e = _engagement(session)  # seeds default workflow
    t = tasks.create(session, e, TaskInput(name="A"))
    assert t.bucket is not None
    assert t.bucket.name == "Backlog"


def test_advance_bucket_walks_workflow_and_marks_completed(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    assert t.bucket and t.bucket.name == "Backlog"
    tasks.advance_bucket(session, t)
    assert t.bucket and t.bucket.name == "In Progress"
    tasks.advance_bucket(session, t)
    tasks.advance_bucket(session, t)
    assert t.bucket and t.bucket.name == "Done"
    assert tasks.is_completed(t) is True
    assert t.status == "Completed"
    # Already in last bucket — stays put
    tasks.advance_bucket(session, t)
    assert t.bucket and t.bucket.name == "Done"


def test_progress_summary_counts_done(session):
    e = _engagement(session)
    a = tasks.create(session, e, TaskInput(name="a"))
    b = tasks.create(session, e, TaskInput(name="b"))
    tasks.advance_bucket(session, a)
    tasks.advance_bucket(session, a)
    tasks.advance_bucket(session, a)  # → Done
    done, total = tasks.progress_summary([a, b])
    assert (done, total) == (1, 2)


def test_is_late_only_when_overdue_and_open(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    overdue = tasks.create(
        session, e, TaskInput(name="O", due_date=today - timedelta(days=2))
    )
    future = tasks.create(
        session, e, TaskInput(name="F", due_date=today + timedelta(days=2))
    )
    completed = tasks.create(
        session,
        e,
        TaskInput(
            name="C", due_date=today - timedelta(days=2), bucket_name="Done"
        ),
    )
    assert tasks.is_late(overdue, today) is True
    assert tasks.is_late(future, today) is False
    assert tasks.is_late(completed, today) is False


def test_soft_delete_and_undo_via_audit_stack(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    tasks.soft_delete(session, t)
    session.flush()
    assert t.deleted_at is not None

    stack = audit.UndoStack()
    stack.push(audit.make_restore_task(t.id, t.name))
    action = stack.pop()
    assert action is not None
    action.apply(session)
    session.flush()
    assert t.deleted_at is None


def test_cycle_status_and_priority_wrap():
    assert cycle_status("Not Started") == "In Progress"
    assert cycle_status("In Progress") == "Completed"
    assert cycle_status("Completed") == "Not Started"
    assert cycle_priority("Urgent") == "Low"
    assert cycle_priority("Medium") == "Important"


def test_checklist_add_toggle_counts(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    a = checklists.add(session, t, "spike token issuer")
    b = checklists.add(session, t, "draft RFC")
    checklists.toggle(session, a)
    session.flush()
    assert tasks.completed_checks(t) == 1
    assert tasks.total_checks(t) == 2
    assert a.sort_order == 0 and b.sort_order == 1
