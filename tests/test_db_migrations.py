"""Lightweight schema migrations.

Cover the additive migrations in `db/schema.py::_apply_lightweight_migrations`.
The new migration block remaps legacy task statuses (`Not Started` → `Intake`,
`Completed` → `Closed`) so old DBs come into line with the new vocabulary.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from openitems.db import engine as engine_mod
from openitems.db.schema import init_schema


def test_legacy_status_strings_remapped(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    eng = engine_mod.reset_for_tests(db)

    # Bootstrap the schema first so the `task` table exists.
    init_schema()

    # Insert rows with the legacy vocabulary directly via SQL — bypassing the
    # ORM lets us simulate a DB that pre-dates the rename.
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO engagement (id, slug, name, created_at, is_inbox) "
                "VALUES ('e1', 'acme', 'Acme', '2026-01-01', 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO task (id, engagement_id, name, description, "
                "priority, status, assigned_to, labels, created_at, updated_at) "
                "VALUES "
                "('t1','e1','old not-started','','Medium','Not Started','','','2026-01-01','2026-01-01'),"
                "('t2','e1','old completed','','Medium','Completed','','','2026-01-01','2026-01-01'),"
                "('t3','e1','already migrated','','Medium','Intake','','','2026-01-01','2026-01-01')"
            )
        )

    # Re-run the bootstrap — the data migration is part of it and should be
    # idempotent.
    init_schema()

    with eng.begin() as conn:
        rows = dict(conn.execute(text("SELECT id, status FROM task")).all())
    assert rows == {"t1": "Intake", "t2": "Closed", "t3": "Intake"}
