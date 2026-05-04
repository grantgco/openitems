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


def test_status_remap_skips_writes_when_no_legacy_rows(tmp_path: Path, monkeypatch) -> None:
    """Once all rows are on the new vocabulary the remap should not issue
    UPDATEs on every launch — it gates on a SELECT 1 first."""
    db = tmp_path / "fresh.db"
    engine_mod.reset_for_tests(db)
    init_schema()  # fresh DB — no legacy rows present

    captured: list[str] = []
    from openitems.db import schema as schema_mod

    real_text = schema_mod.text

    def spy_text(stmt: str):
        captured.append(stmt)
        return real_text(stmt)

    monkeypatch.setattr(schema_mod, "text", spy_text)
    init_schema()

    update_calls = [s for s in captured if s.lstrip().upper().startswith("UPDATE TASK SET STATUS=")]
    assert update_calls == []
