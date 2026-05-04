from __future__ import annotations

from datetime import date, timedelta

from openitems.domain import buckets, engagements, tasks, triage
from openitems.domain.tasks import TaskInput


def _make(session, eng, name, *, due=None, bucket="Intake"):
    return tasks.create(
        session,
        eng,
        TaskInput(name=name, due_date=due, bucket_name=bucket),
    )


def test_list_open_across_engagements_spans_engagements_and_inbox(session):
    acme = engagements.create(session, "Acme")
    globex = engagements.create(session, "Globex")
    inbox = engagements.ensure_inbox(session)

    a1 = _make(session, acme, "Acme open", bucket="In Progress")
    g1 = _make(session, globex, "Globex open", bucket="Intake")
    i1 = _make(session, inbox, "Inbox open", bucket="Intake")
    # Closed (done-state) — must be excluded.
    _make(session, acme, "Acme closed", bucket="Closed")
    # Dropped (also done-state).
    _make(session, globex, "Globex dropped", bucket="Dropped")
    # Soft-deleted — must be excluded even if open.
    deleted = _make(session, acme, "Acme deleted", bucket="In Progress")
    tasks.soft_delete(session, deleted)
    session.flush()

    rows = triage.list_open_across_engagements(session)
    ids = {t.id for t in rows}
    assert ids == {a1.id, g1.id, i1.id}


def test_list_open_excludes_archived_engagement(session):
    acme = engagements.create(session, "Acme")
    keep = _make(session, acme, "Keep", bucket="In Progress")

    archived = engagements.create(session, "Old Project")
    _make(session, archived, "Hidden", bucket="In Progress")
    engagements.archive(session, archived)
    session.flush()

    rows = triage.list_open_across_engagements(session)
    assert [t.id for t in rows] == [keep.id]


def test_bucket_by_due_partitions_correctly(session):
    acme = engagements.create(session, "Acme")
    today = date(2026, 5, 4)  # Monday
    overdue = _make(session, acme, "od", due=today - timedelta(days=2))
    todo_today = _make(session, acme, "td", due=today)
    midweek = _make(session, acme, "mw", due=today + timedelta(days=3))
    next_week = _make(session, acme, "nw", due=today + timedelta(days=10))
    no_due = _make(session, acme, "nd", due=None)

    bands = triage.bucket_by_due(
        triage.list_open_across_engagements(session), today=today
    )
    assert [t.id for t in bands["overdue"]] == [overdue.id]
    assert [t.id for t in bands["today"]] == [todo_today.id]
    assert [t.id for t in bands["this_week"]] == [midweek.id]
    assert [t.id for t in bands["later"]] == [next_week.id]
    assert [t.id for t in bands["no_due"]] == [no_due.id]


def test_bucket_by_due_preserves_band_order_when_empty(session):
    acme = engagements.create(session, "Acme")
    _make(session, acme, "x", due=date(2026, 5, 4))
    bands = triage.bucket_by_due(
        triage.list_open_across_engagements(session),
        today=date(2026, 5, 4),
    )
    assert list(bands.keys()) == list(triage.BAND_ORDER)


def test_done_bucket_for_returns_last_done_state(session):
    acme = engagements.create(session, "Acme")
    # Default seed: Intake, In Progress, Deferred, Dropped, Resolved, Closed.
    # The terminal done-state is Closed (highest sort_order, is_done_state=True).
    bucket = triage.done_bucket_for(session, acme)
    assert bucket is not None
    assert bucket.name == "Closed"


def test_done_bucket_for_none_when_no_done_state(session):
    acme = engagements.create(session, "Acme")
    # Strip done-state flags so the function has nothing to pick.
    for b in buckets.list_for(session, acme):
        b.is_done_state = False
    session.flush()
    assert triage.done_bucket_for(session, acme) is None
