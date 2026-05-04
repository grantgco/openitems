from __future__ import annotations

from datetime import date, timedelta

import pytest

from openitems.db.models import Policy
from openitems.domain import engagements, policies, policy_notes, triage
from openitems.domain.policies import PolicyDateError, PolicyInput


def _engagement(session, name: str = "Acme"):
    return engagements.create(session, name)


def _policy(session, e, **overrides):
    today = overrides.pop("today", date(2026, 5, 1))
    defaults = dict(
        name="Main GL 2026",
        carrier="Travelers",
        coverage="GL",
        policy_number="GL-9001",
        effective_date=today - timedelta(days=120),
        expiration_date=today + timedelta(days=240),
        location="HQ",
        description="General liability — primary",
    )
    defaults.update(overrides)
    return policies.create(session, e, PolicyInput(**defaults))


def test_create_policy_persists_fields(session):
    e = _engagement(session)
    p = _policy(session, e)
    assert p.id
    assert p.engagement_id == e.id
    assert p.name == "Main GL 2026"
    assert p.carrier == "Travelers"
    assert p.coverage == "GL"
    assert p.deleted_at is None


def test_create_strips_whitespace(session):
    e = _engagement(session)
    p = _policy(
        session,
        e,
        name="  Main GL 2026  ",
        carrier=" Travelers ",
        coverage=" GL ",
    )
    assert p.name == "Main GL 2026"
    assert p.carrier == "Travelers"
    assert p.coverage == "GL"


def test_empty_name_rejected(session):
    e = _engagement(session)
    with pytest.raises(ValueError):
        _policy(session, e, name="   ")


def test_effective_after_expiration_rejected(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    with pytest.raises(PolicyDateError):
        _policy(
            session,
            e,
            effective_date=today + timedelta(days=10),
            expiration_date=today,
        )


def test_update_validates_date_order(session):
    e = _engagement(session)
    p = _policy(session, e)
    with pytest.raises(PolicyDateError):
        policies.update(
            session,
            p,
            effective_date=date(2027, 1, 1),
            expiration_date=date(2026, 1, 1),
        )


def test_update_changes_persist(session):
    e = _engagement(session)
    p = _policy(session, e)
    policies.update(
        session,
        p,
        carrier="Liberty Mutual",
        coverage="Workers Comp",
        location="Plant 2",
    )
    refreshed = session.get(Policy, p.id)
    assert refreshed.carrier == "Liberty Mutual"
    assert refreshed.coverage == "Workers Comp"
    assert refreshed.location == "Plant 2"


def test_list_for_sorts_by_expiration(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    p_late = _policy(
        session,
        e,
        name="Umbrella",
        expiration_date=today + timedelta(days=400),
    )
    p_soon = _policy(
        session,
        e,
        name="Auto",
        expiration_date=today + timedelta(days=10),
    )
    p_no_exp = _policy(
        session,
        e,
        name="Cyber",
        effective_date=None,
        expiration_date=None,
    )
    rows = policies.list_for(session, e)
    assert [p.id for p in rows] == [p_soon.id, p_late.id, p_no_exp.id]


def test_list_for_excludes_deleted(session):
    e = _engagement(session)
    p1 = _policy(session, e)
    p2 = _policy(session, e, name="Other")
    policies.soft_delete(session, p2)
    session.flush()
    visible = policies.list_for(session, e)
    assert [p.id for p in visible] == [p1.id]
    all_ = policies.list_for(session, e, include_deleted=True)
    assert {p.id for p in all_} == {p1.id, p2.id}


def test_list_for_excludes_archived_by_default(session):
    e = _engagement(session)
    live = _policy(session, e, name="Live")
    old = _policy(session, e, name="Old")
    policies.archive(session, old)
    session.flush()
    visible = policies.list_for(session, e)
    assert [p.id for p in visible] == [live.id]
    with_archived = policies.list_for(session, e, include_archived=True)
    assert {p.id for p in with_archived} == {live.id, old.id}


def test_count_archived_for_skips_deleted(session):
    e = _engagement(session)
    a = _policy(session, e, name="A")
    b = _policy(session, e, name="B")
    c = _policy(session, e, name="C")
    policies.archive(session, a)
    policies.archive(session, b)
    policies.archive(session, c)
    policies.soft_delete(session, c)
    session.flush()
    assert policies.count_archived_for(session, e) == 2


def test_archive_unarchive_round_trip(session):
    e = _engagement(session)
    p = _policy(session, e)
    policies.archive(session, p)
    session.flush()
    assert p.archived_at is not None
    policies.unarchive(session, p)
    session.flush()
    assert p.archived_at is None


def test_days_to_renewal_basic(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    p = _policy(session, e, expiration_date=today + timedelta(days=14))
    assert policies.days_to_renewal(p, today) == 14


def test_days_to_renewal_lapsed_negative(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    p = _policy(session, e, expiration_date=today - timedelta(days=3))
    assert policies.days_to_renewal(p, today) == -3
    assert policies.is_lapsed(p, today) is True


def test_days_to_renewal_handles_missing_date(session):
    e = _engagement(session)
    p = _policy(session, e, effective_date=None, expiration_date=None)
    assert policies.days_to_renewal(p, date.today()) is None
    assert policies.is_lapsed(p) is False


def test_coverage_suggestions_distinct_and_engagement_scoped(session):
    a = _engagement(session, "Acme")
    b = _engagement(session, "Beta")
    _policy(session, a, name="P1", coverage="GL")
    _policy(session, a, name="P2", coverage="Auto")
    _policy(session, a, name="P3", coverage="gl")  # casing collision
    _policy(session, b, name="P4", coverage="Cyber")

    a_only = policies.coverage_suggestions(session, engagement=a)
    assert "Auto" in a_only
    # Only one of GL / gl should appear (latest casing wins).
    assert sum(1 for c in a_only if c.lower() == "gl") == 1
    assert "Cyber" not in a_only

    all_ = policies.coverage_suggestions(session)
    assert "Cyber" in all_


def test_renewal_horizon_filters(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    p_lapsed = _policy(session, e, name="L", expiration_date=today - timedelta(days=10))
    p_soon = _policy(session, e, name="S", expiration_date=today + timedelta(days=30))
    p_far = _policy(session, e, name="F", expiration_date=today + timedelta(days=400))
    horizon = policies.renewal_horizon(
        [p_lapsed, p_soon, p_far], today=today, days=120
    )
    assert {p.id for p in horizon} == {p_lapsed.id, p_soon.id}


def test_cross_engagement_radar_skips_archived_and_inbox(session):
    today = date(2026, 5, 1)
    a = _engagement(session, "Acme")
    b = _engagement(session, "Beta")
    inbox = engagements.ensure_inbox(session)
    archived = _engagement(session, "Old client")
    engagements.archive(session, archived)
    session.flush()

    _policy(session, a, name="A1", expiration_date=today + timedelta(days=30))
    _policy(session, b, name="B1", expiration_date=today + timedelta(days=60))
    _policy(session, inbox, name="I1", expiration_date=today + timedelta(days=20))
    _policy(session, archived, name="X1", expiration_date=today + timedelta(days=10))

    rows = triage.list_policies_across_engagements(session, today=today)
    names = [r.policy.name for r in rows]
    assert names == ["A1", "B1"]  # ascending expiration
    assert all(r.engagement.is_inbox is False for r in rows)


def test_cross_engagement_radar_horizon_cap(session):
    today = date(2026, 5, 1)
    e = _engagement(session)
    _policy(session, e, name="soon", expiration_date=today + timedelta(days=30))
    _policy(session, e, name="distant", expiration_date=today + timedelta(days=400))
    rows = triage.list_policies_across_engagements(
        session, today=today, horizon_days=120
    )
    assert [r.policy.name for r in rows] == ["soon"]
    rows_unbounded = triage.list_policies_across_engagements(
        session, today=today, horizon_days=None
    )
    assert {r.policy.name for r in rows_unbounded} == {"soon", "distant"}


def test_cross_engagement_radar_includes_lapsed(session):
    today = date(2026, 5, 1)
    e = _engagement(session)
    _policy(session, e, name="lapsed", expiration_date=today - timedelta(days=10))
    rows = triage.list_policies_across_engagements(
        session, today=today, horizon_days=120
    )
    assert len(rows) == 1
    assert rows[0].is_lapsed is True
    assert rows[0].days_to_renewal == -10


def test_cross_engagement_radar_excludes_no_expiration(session):
    today = date(2026, 5, 1)
    e = _engagement(session)
    _policy(session, e, name="no-exp", effective_date=None, expiration_date=None)
    rows = triage.list_policies_across_engagements(session, today=today)
    assert rows == []


def test_policy_notes_round_trip(session):
    e = _engagement(session)
    p = _policy(session, e)
    n1 = policy_notes.add(session, p, "Renewal call with carrier")
    n2 = policy_notes.add(session, p, "Quote received", kind="email")
    ordered = policy_notes.list_for(p)
    # newest first
    assert [n.id for n in ordered] == [n2.id, n1.id]
    assert n2.kind == "email"


def test_policy_notes_reject_empty(session):
    e = _engagement(session)
    p = _policy(session, e)
    with pytest.raises(ValueError):
        policy_notes.add(session, p, "   ")


def test_suggest_renewal_dates_chains_full_term(session):
    e = _engagement(session)
    p = _policy(
        session,
        e,
        effective_date=date(2026, 1, 1),
        expiration_date=date(2027, 1, 1),
    )
    new_eff, new_exp = policies.suggest_renewal_dates(p, today=date(2026, 12, 1))
    assert new_eff == date(2027, 1, 1)
    assert new_exp == date(2028, 1, 1)


def test_suggest_renewal_dates_handles_short_term(session):
    e = _engagement(session)
    # Six-month policy — successor should mirror the term, not snap to a year.
    p = _policy(
        session,
        e,
        effective_date=date(2026, 1, 1),
        expiration_date=date(2026, 7, 1),
    )
    new_eff, new_exp = policies.suggest_renewal_dates(p, today=date(2026, 6, 1))
    assert new_eff == date(2026, 7, 1)
    assert new_exp == date(2027, 1, 1)


def test_suggest_renewal_dates_falls_back_to_today_and_one_year(session):
    e = _engagement(session)
    p = _policy(session, e, effective_date=None, expiration_date=None)
    today = date(2026, 5, 1)
    new_eff, new_exp = policies.suggest_renewal_dates(p, today=today)
    assert new_eff == today
    assert new_exp == date(2027, 5, 1)


def test_renew_creates_successor_and_archives_predecessor(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    old = _policy(
        session,
        e,
        effective_date=date(2025, 5, 1),
        expiration_date=today,
    )
    new_input = PolicyInput(
        name="Main GL 2027",
        carrier=old.carrier,
        coverage=old.coverage,
        policy_number="GL-9002",
        effective_date=today,
        expiration_date=date(2027, 5, 1),
    )
    successor = policies.renew(session, old, new_input)
    session.flush()

    assert successor.id != old.id
    assert successor.engagement_id == e.id
    assert successor.renewed_from_id == old.id
    assert old.archived_at is not None

    # The engagement-scoped list should now show only the successor.
    rows = policies.list_for(session, e)
    assert [p.id for p in rows] == [successor.id]


def test_renew_can_skip_archive(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    old = _policy(session, e, expiration_date=today)
    new_input = PolicyInput(
        name="Successor",
        carrier=old.carrier,
        coverage=old.coverage,
        policy_number="GL-NEW",
        effective_date=today,
        expiration_date=date(2027, 5, 1),
    )
    successor = policies.renew(session, old, new_input, archive_predecessor=False)
    session.flush()
    assert old.archived_at is None
    rows = policies.list_for(session, e)
    assert {p.id for p in rows} == {old.id, successor.id}


def test_renew_validates_dates(session):
    e = _engagement(session)
    today = date(2026, 5, 1)
    old = _policy(session, e, expiration_date=today)
    bad_input = PolicyInput(
        name="Bad",
        effective_date=date(2027, 5, 1),
        expiration_date=date(2026, 5, 1),
    )
    with pytest.raises(PolicyDateError):
        policies.renew(session, old, bad_input)
    # Predecessor must remain live when validation fails: archiving runs
    # after create() succeeds, so a date-order rejection should not flip
    # ``archived_at`` on the predecessor.
    assert old.archived_at is None


def test_renewal_radar_excludes_archived_predecessor(session):
    today = date(2026, 5, 1)
    e = _engagement(session)
    old = _policy(session, e, name="Old", expiration_date=today)
    new_input = PolicyInput(
        name="New",
        carrier=old.carrier,
        coverage=old.coverage,
        policy_number="DIFFERENT-NUM",
        effective_date=today,
        expiration_date=today + timedelta(days=365),
    )
    policies.renew(session, old, new_input)
    session.flush()
    rows = triage.list_policies_across_engagements(
        session, today=today, horizon_days=400
    )
    assert [r.policy.name for r in rows] == ["New"]


def test_policy_cascade_delete(session):
    e = _engagement(session)
    p = _policy(session, e)
    policy_notes.add(session, p, "first")
    session.delete(p)
    session.flush()
    from openitems.db.models import PolicyNote

    assert session.query(PolicyNote).count() == 0
