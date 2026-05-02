from __future__ import annotations

import pytest

from openitems.domain import engagements, notes, tasks
from openitems.domain.notes import DEFAULT_KIND, NOTE_KINDS, cycle_kind, glyph_for
from openitems.domain.tasks import TaskInput


def _task(session, name: str = "Migrate auth"):
    e = engagements.create(session, "Acme")
    return tasks.create(session, e, TaskInput(name=name))


def test_add_note_strips_and_persists(session):
    t = _task(session)
    n = notes.add(session, t, "  spoke with Jess re: cutover  ")
    assert n.body == "spoke with Jess re: cutover"
    assert n.task_id == t.id
    assert n.created_at is not None


def test_add_empty_note_raises(session):
    t = _task(session)
    with pytest.raises(ValueError):
        notes.add(session, t, "   ")


def test_list_for_returns_newest_first(session):
    t = _task(session)
    n1 = notes.add(session, t, "first")
    n2 = notes.add(session, t, "second")
    n3 = notes.add(session, t, "third")
    ordered = notes.list_for(t)
    assert [n.body for n in ordered] == ["third", "second", "first"]
    assert ordered[0].id == n3.id
    assert ordered[-1].id == n1.id


def test_default_kind_is_update(session):
    t = _task(session)
    n = notes.add(session, t, "first")
    assert n.kind == DEFAULT_KIND == "update"


def test_kind_persists(session):
    t = _task(session)
    n = notes.add(session, t, "phoned Jess", kind="call")
    assert n.kind == "call"


def test_invalid_kind_raises(session):
    t = _task(session)
    with pytest.raises(ValueError):
        notes.add(session, t, "body", kind="not-a-kind")


def test_cycle_kind_wraps():
    first = NOTE_KINDS[0]
    last = NOTE_KINDS[-1]
    assert cycle_kind(first) == NOTE_KINDS[1]
    assert cycle_kind(last) == first
    assert cycle_kind(first, direction=-1) == last
    assert cycle_kind("garbage") == DEFAULT_KIND


def test_glyph_falls_back_to_update():
    # Every defined kind has a glyph
    for k in NOTE_KINDS:
        assert glyph_for(k)
    # Unknown kinds fall back to the default glyph rather than crashing
    assert glyph_for("unknown") == glyph_for(DEFAULT_KIND)


def test_list_for_engagement_spans_tasks_newest_first(session):
    e = engagements.create(session, "Acme")
    t1 = tasks.create(session, e, TaskInput(name="A"))
    t2 = tasks.create(session, e, TaskInput(name="B"))
    n1 = notes.add(session, t1, "first on A")
    n2 = notes.add(session, t2, "first on B", kind="call")
    n3 = notes.add(session, t1, "second on A", kind="email")
    out = notes.list_for_engagement(session, e)
    # Newest first across both tasks.
    assert [n.id for n in out] == [n3.id, n2.id, n1.id]
    # Eager-loaded task name is accessible without a fresh query.
    assert {n.task.name for n in out} == {"A", "B"}


def test_list_for_engagement_excludes_deleted_tasks(session):
    e = engagements.create(session, "Acme")
    t = tasks.create(session, e, TaskInput(name="zombie"))
    notes.add(session, t, "ghost note")
    tasks.soft_delete(session, t)
    session.flush()
    assert notes.list_for_engagement(session, e) == []


def test_list_for_engagement_isolates_engagements(session):
    a = engagements.create(session, "Acme")
    b = engagements.create(session, "Beta")
    ta = tasks.create(session, a, TaskInput(name="acme task"))
    tb = tasks.create(session, b, TaskInput(name="beta task"))
    notes.add(session, ta, "acme update")
    notes.add(session, tb, "beta update")
    out_a = notes.list_for_engagement(session, a)
    assert [n.body for n in out_a] == ["acme update"]


def test_notes_cascade_delete_with_task(session):
    t = _task(session)
    notes.add(session, t, "a")
    notes.add(session, t, "b")
    session.delete(t)
    session.flush()
    from openitems.db.models import TaskNote

    assert session.query(TaskNote).count() == 0
