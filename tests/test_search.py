from __future__ import annotations

from datetime import date, timedelta

from openitems.domain import engagements, tasks
from openitems.domain.search import TaskFilter, apply
from openitems.domain.tasks import TaskInput


def _seed(session):
    e = engagements.create(session, "Acme")
    t1 = tasks.create(
        session,
        e,
        TaskInput(name="Migrate auth flow", labels=["api", "sec"], priority="Urgent"),
    )
    t2 = tasks.create(
        session,
        e,
        TaskInput(name="Refactor exporter sheet", labels=["api"], priority="Medium"),
    )
    t3 = tasks.create(
        session, e, TaskInput(name="Audit Planner permissions", labels=["sec"])
    )
    return e, [t1, t2, t3]


def test_filter_by_tag(session):
    _e, [_t1, t2, _t3] = _seed(session)
    out = apply(TaskFilter(tags=("api",)), [_t1, t2, _t3])
    assert {t.name for t in out} == {_t1.name, t2.name}


def test_filter_fuzzy_text(session):
    _e, all_tasks = _seed(session)
    out = apply(TaskFilter(text="exportr"), all_tasks)  # typo on purpose
    assert any("Refactor" in t.name for t in out)


def test_filter_priorities(session):
    _e, all_tasks = _seed(session)
    out = apply(TaskFilter(priorities=("Urgent",)), all_tasks)
    assert len(out) == 1 and out[0].priority == "Urgent"


def test_overdue_only(session):
    e = engagements.create(session, "Other")
    today = date(2026, 5, 1)
    t = tasks.create(
        session, e, TaskInput(name="late one", due_date=today - timedelta(days=3))
    )
    fresh = tasks.create(
        session, e, TaskInput(name="future", due_date=today + timedelta(days=3))
    )
    out = apply(TaskFilter(overdue_only=True, today=today), [t, fresh])
    assert out == [t]
