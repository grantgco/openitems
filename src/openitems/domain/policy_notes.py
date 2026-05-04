"""Append-only policy notes.

Mirrors ``domain.notes`` for the policy parent type — same shape, same kinds,
same immutability story. Notes are timestamped, classified by ``kind``, and
displayed newest-first.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from openitems.db.models import Policy, PolicyNote
from openitems.domain.notes import DEFAULT_KIND, NOTE_KINDS


def add(
    session: Session,
    policy: Policy,
    body: str,
    *,
    kind: str = DEFAULT_KIND,
) -> PolicyNote:
    body = body.strip()
    if not body:
        raise ValueError("Note body cannot be empty")
    if kind not in NOTE_KINDS:
        raise ValueError(f"Note kind must be one of {NOTE_KINDS}, got {kind!r}")
    note = PolicyNote(body=body, kind=kind, policy=policy)
    session.add(note)
    session.flush()
    return note


def list_for(policy: Policy) -> list[PolicyNote]:
    return sorted(policy.notes, key=lambda n: n.created_at, reverse=True)
