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


def _seed_legacy_engagement(eng, eng_id: str = "e1", slug: str = "acme") -> None:
    """Insert an engagement with the pre-rename default workflow buckets."""
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO engagement (id, slug, name, created_at, is_inbox) "
                "VALUES (:id, :slug, :name, '2026-01-01', 0)"
            ),
            {"id": eng_id, "slug": slug, "name": slug.title()},
        )
        for idx, name in enumerate(("Backlog", "In Progress", "In Review", "Done")):
            conn.execute(
                text(
                    "INSERT INTO bucket "
                    "(id, engagement_id, name, sort_order, is_done_state, "
                    "auto_close_after_days) "
                    "VALUES (:id, :eid, :name, :sort, :done, NULL)"
                ),
                {
                    "id": f"b{eng_id}{idx}",
                    "eid": eng_id,
                    "name": name,
                    "sort": idx,
                    "done": 1 if name == "Done" else 0,
                },
            )


def test_legacy_default_workflow_renamed_in_place(tmp_path: Path) -> None:
    """An engagement with the pre-rename default workflow gets renamed to
    the new six-stage vocabulary on the next bootstrap."""
    db = tmp_path / "legacy.db"
    eng = engine_mod.reset_for_tests(db)
    init_schema()
    _seed_legacy_engagement(eng)

    # Drop tasks across the four legacy buckets so we can verify task.status
    # reconciliation as well as the bucket rename.
    with eng.begin() as conn:
        for bucket_idx, status in enumerate(
            ("Not Started", "Not Started", "Not Started", "Completed")
        ):
            conn.execute(
                text(
                    "INSERT INTO task (id, engagement_id, bucket_id, name, "
                    "description, priority, status, assigned_to, labels, "
                    "created_at, updated_at) VALUES "
                    "(:tid, :eid, :bid, :name, '', 'Medium', :status, '', '', "
                    "'2026-01-01', '2026-01-01')"
                ),
                {
                    "tid": f"t{bucket_idx}",
                    "eid": "e1",
                    "bid": f"be1{bucket_idx}",
                    "name": f"task in bucket {bucket_idx}",
                    "status": status,
                },
            )

    init_schema()

    with eng.begin() as conn:
        buckets = conn.execute(
            text(
                "SELECT name, sort_order, is_done_state, auto_close_after_days "
                "FROM bucket WHERE engagement_id='e1' ORDER BY sort_order"
            )
        ).all()
        tasks = dict(
            conn.execute(
                text("SELECT id, status FROM task WHERE engagement_id='e1'")
            ).all()
        )

    assert buckets == [
        ("Intake", 0, 0, None),
        ("In Progress", 1, 0, None),
        ("Deferred", 2, 0, None),
        ("Dropped", 3, 1, None),
        ("Resolved", 4, 1, 14),
        ("Closed", 5, 1, None),
    ]
    # Task statuses now match their bucket names, not the legacy "Intake"/
    # "Closed" remap that was done before the bucket migration ran.
    assert tasks == {
        "t0": "Intake",
        "t1": "In Progress",
        "t2": "Deferred",
        "t3": "Closed",
    }


def test_customized_workflow_left_alone(tmp_path: Path) -> None:
    """Engagements whose buckets have already been customized must not be
    rewritten — only the exact legacy default set is migrated."""
    db = tmp_path / "custom.db"
    eng = engine_mod.reset_for_tests(db)
    init_schema()
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO engagement (id, slug, name, created_at, is_inbox) "
                "VALUES ('e1', 'acme', 'Acme', '2026-01-01', 0)"
            )
        )
        # Same as legacy default plus one custom bucket — not eligible for
        # migration.
        names = ("Backlog", "In Progress", "In Review", "Done", "Waiting on Client")
        for idx, name in enumerate(names):
            conn.execute(
                text(
                    "INSERT INTO bucket "
                    "(id, engagement_id, name, sort_order, is_done_state, "
                    "auto_close_after_days) "
                    "VALUES (:id, 'e1', :name, :sort, 0, NULL)"
                ),
                {"id": f"b{idx}", "name": name, "sort": idx},
            )

    init_schema()

    with eng.begin() as conn:
        bucket_names = sorted(
            row[0] for row in conn.execute(
                text("SELECT name FROM bucket WHERE engagement_id='e1'")
            ).all()
        )
    assert bucket_names == sorted(names)


def test_workflow_migration_idempotent(tmp_path: Path) -> None:
    """Running the bootstrap twice must not duplicate Dropped/Resolved or
    perturb the renamed buckets."""
    db = tmp_path / "idempotent.db"
    eng = engine_mod.reset_for_tests(db)
    init_schema()
    _seed_legacy_engagement(eng)

    init_schema()
    init_schema()  # second run — must be a no-op

    with eng.begin() as conn:
        names = sorted(
            row[0] for row in conn.execute(
                text("SELECT name FROM bucket WHERE engagement_id='e1'")
            ).all()
        )
    assert names == sorted(
        ["Intake", "In Progress", "Deferred", "Dropped", "Resolved", "Closed"]
    )
