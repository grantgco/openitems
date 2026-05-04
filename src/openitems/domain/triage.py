"""Cross-engagement triage queries.

Powers the "All engagements" TUI screen — *what's on my plate across
clients so I can plan*. The single-engagement views in MainScreen scope
everything by ``engagement_id``; this module deliberately does not.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from openitems.db.models import Bucket, Engagement, Task
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
