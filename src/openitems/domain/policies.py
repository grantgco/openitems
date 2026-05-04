"""Policy reference list per engagement.

Standalone sidecar: a per-engagement list of insurance/coverage policies with
effective and expiration dates. Renewal nudges come from a sort-by-expiration
view; policies don't auto-create tasks (the user opted for the simplest shape
during brainstorming).

Mirrors the conventions in ``domain.tasks``:
- ``is_lapsed`` / ``days_to_renewal`` are computed at read time, never persisted.
- Save handlers should call ``parse_strict`` on raw user date input and pass
  the resulting ``date`` (or ``None``) into ``create``/``update`` here.
- Free-text classification: ``coverage`` is a string column with autocomplete
  fed from prior values, colored via ``tag_palette.color_for``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from openitems.db.models import Engagement, Policy
from openitems.domain.text import clean_text


class PolicyDateError(ValueError):
    """Raised when ``effective_date`` is later than ``expiration_date``."""


@dataclass
class PolicyInput:
    name: str
    carrier: str = ""
    coverage: str = ""
    policy_number: str = ""
    effective_date: date | None = None
    expiration_date: date | None = None
    location: str = ""
    description: str = ""


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_dates(eff: date | None, exp: date | None) -> None:
    if eff is not None and exp is not None and eff > exp:
        raise PolicyDateError(
            f"Effective date ({eff.isoformat()}) is after expiration ({exp.isoformat()})."
        )


def list_for(
    session: Session,
    engagement: Engagement,
    *,
    include_deleted: bool = False,
    include_archived: bool = False,
) -> list[Policy]:
    """Return policies for ``engagement``, sorted by expiration ascending.

    Policies without an expiration date sort last, then by carrier/name to keep
    the rendering stable for the screen and the workbook tab. ``archived_at``
    flags historical predecessors superseded by a renewal — they're excluded
    by default for the same reason ``deleted_at`` is.
    """
    stmt = (
        select(Policy)
        .where(Policy.engagement_id == engagement.id)
        .options(selectinload(Policy.notes))
    )
    if not include_deleted:
        stmt = stmt.where(Policy.deleted_at.is_(None))
    if not include_archived:
        stmt = stmt.where(Policy.archived_at.is_(None))
    stmt = stmt.order_by(
        Policy.expiration_date.asc().nulls_last(),
        Policy.carrier.asc(),
        Policy.name.asc(),
    )
    return list(session.scalars(stmt))


def count_archived_for(session: Session, engagement: Engagement) -> int:
    """Return the number of archived (non-deleted) policies on ``engagement``."""
    stmt = (
        select(Policy.id)
        .where(Policy.engagement_id == engagement.id)
        .where(Policy.deleted_at.is_(None))
        .where(Policy.archived_at.is_not(None))
    )
    return len(list(session.scalars(stmt)))


def create(session: Session, engagement: Engagement, input: PolicyInput) -> Policy:
    name = input.name.strip()
    if not name:
        raise ValueError("Policy name cannot be empty")
    _validate_dates(input.effective_date, input.expiration_date)
    policy = Policy(
        engagement_id=engagement.id,
        engagement=engagement,
        name=name,
        carrier=input.carrier.strip(),
        coverage=input.coverage.strip(),
        policy_number=input.policy_number.strip(),
        effective_date=input.effective_date,
        expiration_date=input.expiration_date,
        location=input.location.strip(),
        description=clean_text(input.description),
    )
    session.add(policy)
    session.flush()
    return policy


def update(session: Session, policy: Policy, **changes: object) -> Policy:
    if "name" in changes:
        name = str(changes["name"]).strip()
        if not name:
            raise ValueError("Policy name cannot be empty")
        policy.name = name
    if "carrier" in changes:
        policy.carrier = str(changes["carrier"]).strip()
    if "coverage" in changes:
        policy.coverage = str(changes["coverage"]).strip()
    if "policy_number" in changes:
        policy.policy_number = str(changes["policy_number"]).strip()
    if "effective_date" in changes:
        policy.effective_date = changes["effective_date"]  # type: ignore[assignment]
    if "expiration_date" in changes:
        policy.expiration_date = changes["expiration_date"]  # type: ignore[assignment]
    if "location" in changes:
        policy.location = str(changes["location"]).strip()
    if "description" in changes:
        policy.description = clean_text(str(changes["description"]))
    _validate_dates(policy.effective_date, policy.expiration_date)
    session.flush()
    return policy


def soft_delete(session: Session, policy: Policy) -> None:
    policy.deleted_at = _utcnow()


def restore(session: Session, policy: Policy) -> None:
    policy.deleted_at = None


def archive(session: Session, policy: Policy) -> None:
    """Mark ``policy`` as a historical predecessor — kept for the record but
    omitted from the engagement-scoped list and the cross-engagement radar.

    Distinct from ``soft_delete``: archive means "this was real, it expired
    and was renewed"; soft-delete means "this row was a mistake."
    """
    policy.archived_at = _utcnow()


def unarchive(session: Session, policy: Policy) -> None:
    policy.archived_at = None


def suggest_renewal_dates(
    policy: Policy, today: date | None = None
) -> tuple[date | None, date | None]:
    """Default ``(effective, expiration)`` to use when renewing ``policy``.

    Picks the old expiration as the new effective (the standard "no gap"
    renewal), or today if the predecessor had no expiration on file. The
    new expiration mirrors the predecessor's term length when both old
    dates exist; otherwise it falls back to one calendar year.
    """
    today = today or date.today()
    new_eff = policy.expiration_date or today
    if policy.effective_date and policy.expiration_date:
        term = relativedelta(policy.expiration_date, policy.effective_date)
        new_exp = new_eff + term
        if new_exp <= new_eff:
            new_exp = new_eff + relativedelta(years=1)
    else:
        new_exp = new_eff + relativedelta(years=1)
    return new_eff, new_exp


def renew(
    session: Session,
    predecessor: Policy,
    input: PolicyInput,
    *,
    archive_predecessor: bool = True,
) -> Policy:
    """Create a successor policy and (optionally) archive the predecessor.

    The successor inherits the engagement and is linked back via
    ``renewed_from_id`` so the lineage survives an archive sweep. Date
    validation runs through ``create`` — callers can pass any prefilled
    ``PolicyInput``, including one built from ``suggest_renewal_dates``.
    """
    successor = create(session, predecessor.engagement, input)
    successor.renewed_from_id = predecessor.id
    if archive_predecessor:
        archive(session, predecessor)
    session.flush()
    return successor


def days_to_renewal(policy: Policy, today: date | None = None) -> int | None:
    """Days from ``today`` until ``expiration_date``. Negative when lapsed.

    Returns ``None`` when the policy has no expiration date set.
    """
    if policy.expiration_date is None:
        return None
    today = today or date.today()
    return (policy.expiration_date - today).days


def is_lapsed(policy: Policy, today: date | None = None) -> bool:
    """True when the policy has an expiration date in the past."""
    days = days_to_renewal(policy, today)
    return days is not None and days < 0


def coverage_suggestions(
    session: Session,
    *,
    engagement: Engagement | None = None,
) -> list[str]:
    """Return distinct coverage values, sorted case-insensitively.

    Scoped to ``engagement`` when given; otherwise returns coverages used
    across every live policy. The latest casing wins (matches the convention
    in ``tasks.distinct_labels``).
    """
    stmt = (
        select(Policy.coverage, Policy.updated_at)
        .where(Policy.deleted_at.is_(None))
        .where(Policy.archived_at.is_(None))
        .order_by(Policy.updated_at.asc())
    )
    if engagement is not None:
        stmt = stmt.where(Policy.engagement_id == engagement.id)

    seen: dict[str, str] = {}
    for raw, _ in session.execute(stmt):
        if not raw:
            continue
        cf = raw.casefold()
        seen[cf] = raw
    return sorted(seen.values(), key=lambda s: s.casefold())


def renewal_horizon(policies: Iterable[Policy], today: date, days: int) -> list[Policy]:
    """Return policies expiring in ``[today, today + days]`` or already lapsed.

    Convenience helper for the cross-engagement radar view.
    """
    out: list[Policy] = []
    for p in policies:
        d = days_to_renewal(p, today)
        if d is None:
            continue
        if d <= days:
            out.append(p)
    return out
