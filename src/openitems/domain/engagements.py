from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openitems.db.models import Engagement

_SLUG_RE = re.compile(r"[^a-z0-9]+")


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
