"""Bucket domain logic.

Buckets are workflow stages — tasks move between them as they progress.
A bucket flagged ``is_done_state`` means tasks in it are completed: they
disappear from the open-items view and from the .xlsx export. The default
seed for a new engagement is Backlog → In Progress → In Review → Done.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from openitems.db.models import Bucket, Engagement

# Default workflow seeded into every new engagement. The user can rename,
# reorder, or add stages later — these are just sensible starting points.
DEFAULT_WORKFLOW: Final[tuple[tuple[str, bool], ...]] = (
    ("Backlog", False),
    ("In Progress", False),
    ("In Review", False),
    ("Done", True),
)


def list_for(session: Session, engagement: Engagement) -> list[Bucket]:
    stmt = (
        select(Bucket)
        .where(Bucket.engagement_id == engagement.id)
        .order_by(Bucket.sort_order.asc(), Bucket.name.asc())
    )
    return list(session.scalars(stmt))


def get_or_create(session: Session, engagement: Engagement, name: str) -> Bucket:
    name = name.strip()
    if not name:
        raise ValueError("Bucket name cannot be empty")
    existing = session.scalars(
        select(Bucket).where(Bucket.engagement_id == engagement.id, Bucket.name == name)
    ).first()
    if existing is not None:
        return existing
    next_order = (
        max((b.sort_order for b in list_for(session, engagement)), default=-1) + 1
    )
    bucket = Bucket(engagement_id=engagement.id, name=name, sort_order=next_order)
    session.add(bucket)
    session.flush()
    return bucket


def seed_default_workflow(session: Session, engagement: Engagement) -> list[Bucket]:
    """Create the default workflow buckets if the engagement has none."""
    if list_for(session, engagement):
        return []
    out: list[Bucket] = []
    for idx, (name, is_done) in enumerate(DEFAULT_WORKFLOW):
        bucket = Bucket(
            engagement_id=engagement.id,
            name=name,
            sort_order=idx,
            is_done_state=is_done,
        )
        session.add(bucket)
        out.append(bucket)
    session.flush()
    return out


def next_in_workflow(
    session: Session, engagement: Engagement, current: Bucket | None
) -> Bucket | None:
    """Return the next bucket after ``current`` in workflow order, or None."""
    ordered = list_for(session, engagement)
    if not ordered:
        return None
    if current is None:
        return ordered[0]
    try:
        idx = next(i for i, b in enumerate(ordered) if b.id == current.id)
    except StopIteration:
        return ordered[0]
    if idx + 1 < len(ordered):
        return ordered[idx + 1]
    return ordered[idx]  # already at the end


def names_for(session: Session, engagement: Engagement) -> list[str]:
    """Names in workflow order, for autocomplete suggesters."""
    return [b.name for b in list_for(session, engagement)]
