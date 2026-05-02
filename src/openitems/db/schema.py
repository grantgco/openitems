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
