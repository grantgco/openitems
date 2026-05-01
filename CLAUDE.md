# CLAUDE.md — openitems

A Textual TUI on top of SQLite that replaces a Microsoft Planner workflow and re-emits the same client-facing `.xlsx` the existing VBA macro produces. See `README.md` for install/usage; this file captures the load-bearing decisions and pitfalls that aren't obvious from reading the code.

## Mental model

- **Bucket = workflow stage.** Tasks move between buckets (Backlog → In Progress → In Review → Done) as they progress. The bucket *is* the progress signal. Bucket names stay free-text; what a bucket *means* is determined by `Bucket.is_done_state` and `sort_order`.
- **`Bucket.is_done_state`** is the source of truth for "this task is done." Tasks in a done-state bucket are excluded from open-items views and the `.xlsx` export. The default seed for every new engagement marks `Done` as the only done-state.
- **`Task.status` is derived, not user-edited.** It auto-syncs from the bucket via `_sync_status_with_bucket` in `domain/tasks.py`. The column exists for `.xlsx` export legibility (the VBA macro filters on `status == "Completed"`); don't expose it as a separate UI control.
- **`is_late` is computed at read time**, never persisted. Mirrors `modOpenItemsList.bas:180-184`.
- **Engagement = workspace.** All engagements live in one SQLite DB; the active one is remembered in `~/.config/openitems/config.toml` and shown in the titlebar. New engagements get the default workflow seeded automatically (`buckets.seed_default_workflow`).

## Reference docs (outside this repo)

- `~/Downloads/modOpenItemsList.bas` — authoritative spec for the `.xlsx` output. The Python exporter (`src/openitems/export/workbook.py`) is a direct port of `BuildReport()` (`:369-793`). Reference line ranges in commit messages when you change exporter behavior.
- `/tmp/openitems-design/open-items-tui/project/Open Items TUI.html` — the Claude Design wireframe bundle. Palette tokens at `:10-36`, three-pane layout at `:439-537`, export wizard at `:823-924`.
- `/Users/grantgreeson/.claude/plans/i-would-like-to-luminous-sifakis.md` — original implementation plan.

## Conventions

### Libraries (per global `~/.claude/CLAUDE.md`)
Parsing/formatting must use these — don't roll your own:
- **Dateparser** — user-facing date input
- **Humanize** — relative dates ("in 3 days")
- **RapidFuzz** — fuzzy matching (`/` filter)
- **Babel** — locale-aware formatting

### Date parsing in form handlers
Always use `domain.dates.parse_strict(value, field=...)` in save handlers, not `parse()`. `parse_strict` raises `DateParseError` on non-empty unparseable input so the form can show a notify; `parse()` returns `None` indistinguishably for empty and bad input, which once shipped a silent-data-loss bug.

### Imports for testability
Modules that consume runtime paths import the **module**, not the function:
```python
from openitems import paths           # ✓
target = paths.db_path()
```
not
```python
from openitems.paths import db_path   # ✗ — breaks monkeypatch.setattr in tests
```
Same rule for `openitems.config` ↔ `openitems.paths`. Tests in `conftest.py` rely on this.

### Schema changes
We use `Base.metadata.create_all` plus a tiny additive migration block in `db/schema.py::_apply_lightweight_migrations`. For a new column, add an `ALTER TABLE … ADD COLUMN` there guarded by an `inspect()` check. Reach for Alembic only when we hit a non-additive change (rename, drop, type change).

### Bucket / status invariants
- Never write to `task.status` directly from UI code. Pass `bucket_id` (or set the relationship) and call `tasks.update` — `_sync_status_with_bucket` handles the rest.
- New buckets created via `buckets.get_or_create` get the next available `sort_order`. They're **not** done-states unless explicitly seeded.

## Textual pitfalls (from incidents)

- **Don't name an instance attribute `_task`** on a `Widget`/`MessagePump` subclass — Textual stores its asyncio task at `self._task` and you'll clobber it, crashing the message loop with a baffling `TypeError: An asyncio.Future, a coroutine or an awaitable is required` from `gather(...)`. We use `_current_task` etc.
- **Don't define a custom `Changed` message on an `Input` subclass.** Shadowing `Input.Changed` breaks the parent's auto-post (wrong `__init__` signature). Instead, listen for `Input.Changed` directly with a CSS selector: `@on(Input.Changed, "#filter-bar")`.
- **DataTable columns must be set up idempotently.** Mount-order issues bit us once. The pattern in `widgets/items_pane.py::_ensure_columns` is the reference.
- **`screen._option_list.focus()`** — pane focus is implemented manually because Textual's tab focus order doesn't map cleanly onto our three-pane layout. See `MainScreen._focus_pane`.

## Workflows

### Run / develop
- `uv run pytest` — full suite (~30 tests, ~1.5s)
- `uv run ruff check src tests` — lint must pass; project ignores `E501`, `N806` (SQLAlchemy `SessionLocal` convention), `RUF002/003/012`
- `uv run openitems` — launch TUI against the real DB (`~/Library/Application Support/openitems/openitems.db`)
- `uv run textual run --dev openitems.tui.app:OpenItemsApp` — TUI with the dev console

### Typical change patterns
- **New domain rule**: write the test in `tests/test_domain_*.py` first, then implement in `src/openitems/domain/`. Domain layer is pure SQLAlchemy + dataclasses; no Textual imports.
- **New TUI screen / widget**: composition lives in `src/openitems/tui/screens/` (modals) or `src/openitems/tui/widgets/` (reused). Style tokens belong in `tui/palette.py` and the global TCSS at `tui/app.tcss`. Don't inline hex codes in widget files.
- **Exporter change**: update `export/workbook.py`, then update `tests/test_export_workbook.py` snapshot assertions. When in doubt, render the `.xlsx` and eyeball it against a reference workbook from the original VBA macro.

### Don't
- Don't add `status` controls to UIs — see "Bucket / status invariants" above.
- Don't sort export buckets alphabetically; sort by `Bucket.sort_order` (workflow order). The VBA macro sorted alphabetically; we deliberately diverge.
- Don't use `datetime.utcnow()` (Python 3.13 deprecation). Use `datetime.now(UTC).replace(tzinfo=None)` to keep the existing naive-UTC convention.
- Don't add Alembic, Pydantic, or click — Typer covers the CLI surface and SQLAlchemy 2.x DSL covers the rest. The dependency list in `pyproject.toml` is intentionally tight.
