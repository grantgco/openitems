"""Cross-engagement triage queries.

Powers the "All engagements" TUI screen — *what's on my plate across
clients so I can plan*. The single-engagement views in MainScreen scope
everything by ``engagement_id``; this module deliberately does not.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from openitems.db.models import Bucket, Engagement, Policy, Task
from openitems.domain.dates import start_of_week
from openitems.domain.tasks import is_late

DueBand = Literal["overdue", "today", "this_week", "later", "no_due"]

# Render order for `bucket_by_due` output. Bands not present in a result
# still appear (as empty lists) so the UI can show a stable layout.
BAND_ORDER: tuple[DueBand, ...] = ("overdue", "today", "this_week", "later", "no_due")

BAND_LABELS: dict[DueBand, str] = {
    "overdue": "Overdue",
    "today": "Today",
    "this_week": "This week",
    "later": "Later",
    "no_due": "No due date",
}


def list_open_across_engagements(session: Session) -> list[Task]:
    """Return live, non-done tasks across every active engagement.

    Joins to ``Bucket`` and filters ``Bucket.is_done_state == False`` —
    meaning Resolved/Closed/Dropped tasks (and any user-defined
    done-state bucket) are excluded. Tasks without a bucket are included
    (they're new and unworked, so they should appear on the plate).

    Excludes archived engagements. The Inbox is included because it's an
    active engagement; if the caller wants to omit it they should filter
    on ``task.engagement.is_inbox`` afterwards.
    """
    stmt = (
        select(Task)
        .outerjoin(Bucket, Task.bucket_id == Bucket.id)
        .join(Engagement, Task.engagement_id == Engagement.id)
        .where(Task.deleted_at.is_(None))
        .where(Engagement.archived_at.is_(None))
        # Either no bucket assigned, or bucket isn't a done-state.
        .where((Bucket.id.is_(None)) | (Bucket.is_done_state.is_(False)))
        .options(
            selectinload(Task.bucket),
            selectinload(Task.notes),
            joinedload(Task.engagement),
        )
        .order_by(Task.due_date.asc().nulls_last(), Task.name.asc())
    )
    return list(session.scalars(stmt))


def bucket_by_due(
    tasks: list[Task], today: date | None = None
) -> OrderedDict[DueBand, list[Task]]:
    """Partition ``tasks`` into the five render bands.

    "This week" is everything strictly after today and on or before the
    Sunday that ends the current ISO week. Anything beyond that Sunday
    falls into "later"; anything earlier than today with a due date
    falls into "overdue" (mirrors ``is_late``).
    """
    today = today or date.today()
    week_end = start_of_week(today) + timedelta(days=6)

    out: OrderedDict[DueBand, list[Task]] = OrderedDict(
        (band, []) for band in BAND_ORDER
    )
    for t in tasks:
        if t.due_date is None:
            out["no_due"].append(t)
        elif is_late(t, today):
            out["overdue"].append(t)
        elif t.due_date == today:
            out["today"].append(t)
        elif t.due_date <= week_end:
            out["this_week"].append(t)
        else:
            out["later"].append(t)
    return out


@dataclass
class PolicyRow:
    """A policy plus the engagement it belongs to and its renewal countdown.

    Used by the cross-engagement renewal radar so callers don't have to
    re-walk the relationship for each row.
    """

    policy: Policy
    engagement: Engagement
    days_to_renewal: int | None

    @property
    def is_lapsed(self) -> bool:
        d = self.days_to_renewal
        return d is not None and d < 0


def list_policies_across_engagements(
    session: Session,
    *,
    today: date | None = None,
    horizon_days: int | None = 120,
) -> list[PolicyRow]:
    """Return live policies across every active engagement, expiration ascending.

    ``horizon_days`` caps how far into the future to surface — a 120-day
    window keeps the radar focused on the next quarter's renewals plus
    anything already lapsed. Pass ``None`` to disable the cap. Policies
    without an ``expiration_date`` are excluded (no renewal signal).
    """
    today = today or date.today()
    stmt = (
        select(Policy)
        .join(Engagement, Policy.engagement_id == Engagement.id)
        .where(Policy.deleted_at.is_(None))
        .where(Policy.archived_at.is_(None))
        .where(Engagement.archived_at.is_(None))
        .where(Engagement.is_inbox.is_(False))
        .where(Policy.expiration_date.is_not(None))
        .options(joinedload(Policy.engagement))
        .order_by(Policy.expiration_date.asc(), Policy.carrier.asc())
    )
    rows: list[PolicyRow] = []
    for p in session.scalars(stmt):
        if p.expiration_date is None:
            continue
        delta = (p.expiration_date - today).days
        if horizon_days is not None and delta > horizon_days:
            continue
        rows.append(
            PolicyRow(policy=p, engagement=p.engagement, days_to_renewal=delta)
        )
    return rows


def done_bucket_for(session: Session, engagement: Engagement) -> Bucket | None:
    """Return the workflow-final done-state bucket for ``engagement``, if any.

    Picks the *highest* ``sort_order`` done-state bucket — under the
    default workflow that's "Closed" (not "Dropped" or "Resolved"), which
    matches the user's intuition of "mark this done" as the most
    terminal, neutral resolution.
    """
    stmt = (
        select(Bucket)
        .where(Bucket.engagement_id == engagement.id)
        .where(Bucket.is_done_state.is_(True))
        .order_by(Bucket.sort_order.desc(), Bucket.name.asc())
    )
    return session.scalars(stmt).first()
