"""Lightweight schema bootstrap.

We use SQLAlchemy's ``Base.metadata.create_all`` for v1 — Alembic is overkill
for a brand-new schema. When we make our first breaking change we'll add
``alembic init`` proper. Until then, additive column changes go in
``_apply_lightweight_migrations`` below as ``ALTER TABLE … ADD COLUMN``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import inspect, text

from openitems.db.engine import get_engine
from openitems.db.models import Base

# The pre-rename default workflow. Engagements whose bucket set matches this
# exactly are migrated to the new six-stage vocabulary in
# `_migrate_legacy_default_workflow`. Anything customized is left alone.
_LEGACY_DEFAULT_BUCKETS = frozenset({"Backlog", "In Progress", "In Review", "Done"})


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
        _legacy_status_values = (
            "Not Started", "Completed", "Backlog", "In Review", "Done",
        )
        with engine.begin() as conn:
            placeholders = ",".join(f"'{v}'" for v in _legacy_status_values)
            has_legacy = conn.execute(
                text(
                    f"SELECT 1 FROM task WHERE status IN ({placeholders}) LIMIT 1"
                )
            ).first()
            if has_legacy:
                # Old "Not Started" and "Backlog" both meant "newly captured."
                conn.execute(
                    text(
                        "UPDATE task SET status='Intake' "
                        "WHERE status IN ('Not Started', 'Backlog')"
                    )
                )
                # "In Review" was the mid-pipeline holding state — closest
                # non-done analogue in the new vocabulary is "Deferred".
                conn.execute(
                    text(
                        "UPDATE task SET status='Deferred' "
                        "WHERE status='In Review'"
                    )
                )
                # "Completed" and "Done" were both terminal states.
                conn.execute(
                    text(
                        "UPDATE task SET status='Closed' "
                        "WHERE status IN ('Completed', 'Done')"
                    )
                )

    if "bucket" in table_names:
        _migrate_legacy_default_workflow()


def _migrate_legacy_default_workflow() -> None:
    """Rename pre-rename default buckets in place to the new vocabulary.

    Older engagements were seeded with ``Backlog → In Progress → In Review →
    Done``. The new vocabulary is ``Intake → In Progress → Deferred → Dropped
    → Resolved → Closed``. Without this step, the bucket pane shows the old
    names for engagements created before the rename. Only engagements whose
    bucket set matches the legacy default *exactly* are migrated — anything
    customized is left alone.
    """
    engine = get_engine()
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, engagement_id, name FROM bucket")
        ).all()
        if not rows:
            return

        per_engagement: dict[str, dict[str, str]] = {}
        for bucket_id, eng_id, name in rows:
            per_engagement.setdefault(eng_id, {})[name] = bucket_id

        for eng_id, by_name in per_engagement.items():
            if set(by_name.keys()) != _LEGACY_DEFAULT_BUCKETS:
                continue

            renames = (
                # (legacy name, new name, sort_order, is_done_state, auto_close_after_days)
                ("Backlog",     "Intake",      0, 0, None),
                ("In Progress", "In Progress", 1, 0, None),
                ("In Review",   "Deferred",    2, 0, None),
                ("Done",        "Closed",      5, 1, None),
            )
            for legacy_name, new_name, sort_order, is_done, auto_close in renames:
                conn.execute(
                    text(
                        "UPDATE bucket SET name=:name, sort_order=:sort_order, "
                        "is_done_state=:is_done, auto_close_after_days=:auto_close "
                        "WHERE id=:bid"
                    ),
                    {
                        "name": new_name,
                        "sort_order": sort_order,
                        "is_done": is_done,
                        "auto_close": auto_close,
                        "bid": by_name[legacy_name],
                    },
                )

            inserts = (
                # (name, sort_order, is_done_state, auto_close_after_days)
                ("Dropped",  3, 1, None),
                ("Resolved", 4, 1, 14),
            )
            for new_name, sort_order, is_done, auto_close in inserts:
                conn.execute(
                    text(
                        "INSERT INTO bucket "
                        "(id, engagement_id, name, sort_order, is_done_state, "
                        "auto_close_after_days) "
                        "VALUES (:id, :eid, :name, :sort_order, :is_done, :auto_close)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "eid": eng_id,
                        "name": new_name,
                        "sort_order": sort_order,
                        "is_done": is_done,
                        "auto_close": auto_close,
                    },
                )

            # Reconcile task.status with the new bucket names so the status
            # pills in the items pane match the workflow stage. The earlier
            # legacy-status remap put these on Intake/Closed; tasks in the
            # In Progress and Deferred buckets need a follow-up nudge.
            in_progress_id = by_name["In Progress"]
            deferred_id = by_name["In Review"]
            conn.execute(
                text("UPDATE task SET status='In Progress' WHERE bucket_id=:bid"),
                {"bid": in_progress_id},
            )
            conn.execute(
                text("UPDATE task SET status='Deferred' WHERE bucket_id=:bid"),
                {"bid": deferred_id},
            )
