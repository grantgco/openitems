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
    workflow = buckets.list_for(session, e)
    names = [b.name for b in workflow]
    assert names == [
        "Intake",
        "In Progress",
        "Deferred",
        "Dropped",
        "Resolved",
        "Closed",
    ]
    by_name = {b.name: b for b in workflow}
    assert by_name["Resolved"].auto_close_after_days == 14
    assert by_name["Resolved"].is_done_state is True
    assert by_name["Closed"].is_done_state is True
    assert by_name["Dropped"].is_done_state is True
    assert by_name["Intake"].is_done_state is False
    assert by_name["Deferred"].is_done_state is False


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


def test_ensure_inbox_handles_pre_existing_name_collision(session):
    """If a regular engagement called 'Inbox' exists first, ensure_inbox
    creates a separate is_inbox=True engagement (with a non-colliding slug)
    rather than promoting the existing one.

    The is_inbox flag — not the slug — is the source of truth.
    """
    pre = engagements.create(session, "Inbox")
    assert pre.slug == "inbox"
    assert pre.is_inbox is False
    inbox = engagements.ensure_inbox(session)
    assert inbox.id != pre.id
    assert inbox.slug != pre.slug  # auto-bumped (e.g. "inbox-2")
    assert inbox.is_inbox is True


def test_default_workflow_done_bucket_is_done_state(session):
    e = _engagement(session)
    closed = next(b for b in buckets.list_for(session, e) if b.name == "Closed")
    assert closed.is_done_state is True
    assert closed.auto_close_after_days is None


def test_move_to_engagement_lands_in_first_bucket(session):
    src = engagements.create(session, "Source")
    dst = engagements.create(session, "Dest")
    t = tasks.create(session, src, TaskInput(name="A", bucket_name="In Progress"))
    assert t.bucket is not None and t.bucket.name == "In Progress"
    tasks.move_to_engagement(session, t, dst)
    assert t.engagement_id == dst.id
    # Lands in dest's first workflow stage (Intake).
    assert t.bucket is not None and t.bucket.name == "Intake"
    # Source bucket reference is severed.
    assert t.bucket.engagement_id == dst.id


def test_move_to_engagement_noop_for_same_target(session):
    e = engagements.create(session, "Acme")
    t = tasks.create(session, e, TaskInput(name="A", bucket_name="In Progress"))
    same = tasks.move_to_engagement(session, t, e)
    assert same.bucket is not None and same.bucket.name == "In Progress"


def test_toggle_focus_stamps_then_clears(session):
    from datetime import date

    from openitems.domain.dates import start_of_week

    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="A"))
    today = date(2026, 5, 6)  # Wednesday
    tasks.toggle_focus(session, t, today=today)
    assert t.focus_week == start_of_week(today)
    tasks.toggle_focus(session, t, today=today)
    assert t.focus_week is None


def test_focus_only_filter_keeps_only_this_weeks_tasks(session):
    from datetime import date

    from openitems.domain.search import TaskFilter, apply

    e = _engagement(session)
    t1 = tasks.create(session, e, TaskInput(name="this week"))
    t2 = tasks.create(session, e, TaskInput(name="not focused"))
    today = date(2026, 5, 6)
    tasks.toggle_focus(session, t1, today=today)
    out = apply(TaskFilter(focus_only=True, today=today), [t1, t2])
    assert out == [t1]


def test_default_bucket_assigned_when_unspecified(session):
    e = _engagement(session)  # seeds default workflow
    t = tasks.create(session, e, TaskInput(name="A"))
    assert t.bucket is not None
    assert t.bucket.name == "Intake"


def test_advance_bucket_walks_workflow_and_marks_done(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    assert t.bucket and t.bucket.name == "Intake"
    expected = ["In Progress", "Deferred", "Dropped", "Resolved", "Closed"]
    for name in expected:
        tasks.advance_bucket(session, t)
        assert t.bucket and t.bucket.name == name
    assert tasks.is_completed(t) is True
    assert t.status == "Closed"
    # Already in last bucket — stays put
    tasks.advance_bucket(session, t)
    assert t.bucket and t.bucket.name == "Closed"


def test_progress_summary_counts_done(session):
    e = _engagement(session)
    a = tasks.create(session, e, TaskInput(name="a"))
    b = tasks.create(session, e, TaskInput(name="b"))
    # Move a directly into the terminal Closed bucket.
    tasks.update(
        session,
        a,
        bucket_id=next(
            x.id for x in buckets.list_for(session, e) if x.name == "Closed"
        ),
    )
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
            name="C", due_date=today - timedelta(days=2), bucket_name="Closed"
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
    assert cycle_status("Intake") == "In Progress"
    assert cycle_status("Closed") == "Intake"  # wraps
    assert cycle_status("not-a-status") == "Intake"
    assert cycle_priority("Urgent") == "Low"
    assert cycle_priority("Medium") == "Important"


def _bucket_id(session, e, name: str) -> str:
    return next(b.id for b in buckets.list_for(session, e) if b.name == name)


def test_resolved_at_stamped_on_entry_and_cleared_on_reopen(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "Resolved"))
    assert t.status == "Resolved"
    assert t.resolved_at is not None
    first_stamp = t.resolved_at

    # Reopen → stamp clears.
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "In Progress"))
    assert t.status == "In Progress"
    assert t.resolved_at is None

    # Re-resolve → stamp re-applies (clock starts over).
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "Resolved"))
    assert t.resolved_at is not None
    assert t.resolved_at >= first_stamp


def test_status_mapping_for_each_default_bucket(session):
    from openitems.domain.tasks import _sync_status_with_bucket

    e = _engagement(session)
    for bucket_name, expected_status in [
        ("Intake", "Intake"),
        ("In Progress", "In Progress"),
        ("Deferred", "Deferred"),
        ("Dropped", "Dropped"),
        ("Resolved", "Resolved"),
        ("Closed", "Closed"),
    ]:
        t = tasks.create(session, e, TaskInput(name=f"t-{bucket_name}"))
        t.bucket = next(b for b in buckets.list_for(session, e) if b.name == bucket_name)
        t.bucket_id = t.bucket.id
        _sync_status_with_bucket(t)
        assert t.status == expected_status, bucket_name


def test_sweep_promotes_after_ttl(session):
    from datetime import UTC, datetime, timedelta

    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "Resolved"))
    assert t.status == "Resolved"

    # Pretend resolved_at was 15 days ago (TTL is 14).
    t.resolved_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=15)
    session.flush()

    promoted = tasks.sweep_auto_close(session, e)
    assert promoted == 1
    assert t.bucket and t.bucket.name == "Closed"
    assert t.status == "Closed"
    assert t.resolved_at is None


def test_sweep_noop_before_ttl(session):
    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "Resolved"))
    promoted = tasks.sweep_auto_close(session, e)
    assert promoted == 0
    assert t.bucket and t.bucket.name == "Resolved"


def test_sweep_skips_soft_deleted(session):
    from datetime import UTC, datetime, timedelta

    e = _engagement(session)
    t = tasks.create(session, e, TaskInput(name="X"))
    tasks.update(session, t, bucket_id=_bucket_id(session, e, "Resolved"))
    t.resolved_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    tasks.soft_delete(session, t)
    session.flush()
    promoted = tasks.sweep_auto_close(session, e)
    assert promoted == 0
    assert t.bucket and t.bucket.name == "Resolved"


def test_distinct_labels_dedupes_case_insensitively(session):
    e = _engagement(session)
    tasks.create(session, e, TaskInput(name="A", labels=["api", "Sec"]))
    tasks.create(session, e, TaskInput(name="B", labels=["API", "docs"]))
    # A soft-deleted task's labels should not show up.
    deleted = tasks.create(session, e, TaskInput(name="C", labels=["secret"]))
    tasks.soft_delete(session, deleted)
    session.flush()

    out = tasks.distinct_labels(session, e)
    cf = [t.casefold() for t in out]
    assert cf == ["api", "docs", "sec"]
    # Most-recent casing wins.
    assert "API" in out


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
