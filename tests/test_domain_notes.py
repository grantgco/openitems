from __future__ import annotations

import pytest

from openitems.domain import engagements, notes, tasks
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


def test_notes_cascade_delete_with_task(session):
    t = _task(session)
    notes.add(session, t, "a")
    notes.add(session, t, "b")
    session.delete(t)
    session.flush()
    from openitems.db.models import TaskNote

    assert session.query(TaskNote).count() == 0
