from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openitems.db.models import Engagement

_SLUG_RE = re.compile(r"[^a-z0-9]+")

INBOX_SLUG = "inbox"
INBOX_NAME = "Inbox"


def slugify(name: str) -> str:
    s = _SLUG_RE.sub("-", name.lower()).strip("-")
    return s or "engagement"


def _unique_slug(session: Session, base: str) -> str:
    existing = {
        s
        for (s,) in session.execute(
            select(Engagement.slug).where(Engagement.slug.like(f"{base}%"))
        )
    }
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def create(session: Session, name: str) -> Engagement:
    from openitems.domain import buckets as buckets_mod

    name = name.strip()
    if not name:
        raise ValueError("Engagement name cannot be empty")
    slug = _unique_slug(session, slugify(name))
    e = Engagement(name=name, slug=slug)
    session.add(e)
    session.flush()
    buckets_mod.seed_default_workflow(session, e)
    return e


def list_active(session: Session) -> list[Engagement]:
    stmt = (
        select(Engagement)
        .where(Engagement.archived_at.is_(None))
        .order_by(Engagement.name.asc())
    )
    return list(session.scalars(stmt))


def get_by_slug(session: Session, slug: str) -> Engagement | None:
    return session.scalars(select(Engagement).where(Engagement.slug == slug)).first()


def archive(session: Session, engagement: Engagement) -> None:
    engagement.archived_at = datetime.now(UTC).replace(tzinfo=None)


def ensure_inbox(session: Session) -> Engagement:
    """Return the inbox engagement, creating it on demand.

    The inbox is the catch-all for brain-dumped tasks that don't have a
    client home yet. It's marked with ``is_inbox=True`` so client-facing
    tooling (digest exports, etc.) can opt out of including it. Idempotent:
    subsequent calls return the same engagement without recreating workflow.
    """
    existing = session.scalars(
        select(Engagement).where(Engagement.is_inbox.is_(True))
    ).first()
    if existing is not None:
        return existing
    e = create(session, INBOX_NAME)
    e.is_inbox = True
    session.flush()
    return e


def list_clients(session: Session) -> list[Engagement]:
    """Active engagements excluding the inbox.

    Use this where the surface is client-facing (digest pickers, etc.).
    """
    stmt = (
        select(Engagement)
        .where(Engagement.archived_at.is_(None))
        .where(Engagement.is_inbox.is_(False))
        .order_by(Engagement.name.asc())
    )
    return list(session.scalars(stmt))
