"""Lightweight schema bootstrap.

We use SQLAlchemy's ``Base.metadata.create_all`` for v1 — Alembic is overkill
for a brand-new schema. When we make our first breaking change we'll add
``alembic init`` proper. Until then, additive column changes go in
``_apply_lightweight_migrations`` below as ``ALTER TABLE … ADD COLUMN``.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from openitems.db.engine import get_engine
from openitems.db.models import Base


def init_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    engine = get_engine()
    insp = inspect(engine)
    table_names = set(insp.get_table_names())

    if "bucket" in table_names:
        cols = {c["name"] for c in insp.get_columns("bucket")}
        if "is_done_state" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE bucket ADD COLUMN is_done_state "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )

    if "task_note" in table_names:
        cols = {c["name"] for c in insp.get_columns("task_note")}
        if "kind" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE task_note ADD COLUMN kind "
                        "TEXT NOT NULL DEFAULT 'update'"
                    )
                )

    if "engagement" in table_names:
        cols = {c["name"] for c in insp.get_columns("engagement")}
        if "is_inbox" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE engagement ADD COLUMN is_inbox "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
        if "homepage_url" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE engagement ADD COLUMN homepage_url TEXT")
                )

    if "bucket" in table_names:
        cols = {c["name"] for c in insp.get_columns("bucket")}
        if "auto_close_after_days" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE bucket ADD COLUMN auto_close_after_days INTEGER"
                    )
                )

    if "task" in table_names:
        cols = {c["name"] for c in insp.get_columns("task")}
        if "external_url" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE task ADD COLUMN external_url TEXT")
                )
        if "focus_week" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE task ADD COLUMN focus_week DATE")
                )
        if "resolved_at" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE task ADD COLUMN resolved_at DATETIME")
                )
        # One-shot remap of legacy status strings into the new vocabulary.
        # Gated by an existence probe so the UPDATEs only fire on a DB
        # that actually predates the rename — every subsequent launch is
        # a single SELECT, not two writes.
        with engine.begin() as conn:
            has_legacy = conn.execute(
                text(
                    "SELECT 1 FROM task "
                    "WHERE status IN ('Not Started', 'Completed') LIMIT 1"
                )
            ).first()
            if has_legacy:
                conn.execute(
                    text(
                        "UPDATE task SET status='Intake' "
                        "WHERE status='Not Started'"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE task SET status='Closed' "
                        "WHERE status='Completed'"
                    )
                )
