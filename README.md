# openitems

Keyboard-driven open-items tracker (Textual TUI) that exports a Planner-style `.xlsx` your clients already recognize.

Built to retire a Microsoft Planner workflow in favor of a local SQLite system of record while preserving the navy/cream "Open Items List" deliverable.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone <this repo> openitems
cd openitems
uv sync --extra dev
uv tool install --editable .   # or `uv run openitems` from the project dir
```

By default the SQLite DB lives at `~/openitems/openitems.db` — visible in Finder and easy to point a SQLite browser at. Run `openitems doctor` to see all resolved paths. Override with `OPENITEMS_DB=/some/path/foo.db openitems`, or set `db_path = "..."` in `~/.config/openitems/config.toml`.

## Quick start

```sh
openitems engagements new "Acme Co"   # create your first engagement
openitems                              # launch the TUI
```

On first launch with no active engagement set, the engagement switcher opens automatically. After picking one it's remembered in `~/.config/openitems/config.toml`.

## TUI keymap

| Key | Action |
|---|---|
| `Tab` / `Shift+Tab` | Cycle pane focus (buckets → items → detail) |
| `j` / `k` | Down / up in current pane |
| `g` / `G` | Top / bottom |
| `1`–`9` | Jump to bucket N |
| `a` | New task |
| `e` / `Enter` | Edit selected task |
| `d` | Soft-delete |
| `u` | Undo last delete |
| `s` | Cycle status (Not Started → In Progress → Completed) |
| `p` | Cycle priority |
| `Space` | Toggle next checklist item |
| `/` | Focus filter / fuzzy search |
| `x` | Open export wizard |
| `X` | Quick-export with last-used settings |
| `E` | Switch engagement |
| `?` | Help |
| `q` | Quit |

## Exporting

Either from the TUI (`x` for the 3-step wizard, `X` for one-shot quick export) or from the shell:

```sh
openitems export acme-co --out ~/Desktop/acme-may.xlsx --open
openitems quick-export             # uses the active engagement + last-used settings
```

The output mirrors the legacy VBA macro (`modOpenItemsList.bas`):

- Title bar (navy / Open Items List)
- Subtitle with generation timestamp + counts
- Bucket header rows (alphabetical), alternating cream/white task rows
- Checklist sub-rows on a light-blue band, with `[x]` / `[ ]` markers
- Summary footer with totals (open / high+urgent / overdue)
- Print setup: landscape, fit-to-width, frozen title rows, 0.5"/0.4" margins
- Tasks with status `Completed` and soft-deleted tasks are excluded

## Data model

- **Engagements** — top-level workspaces. The active one shows in the titlebar.
- **Buckets** — free-text grouping per engagement.
- **Tasks** — `name, description, priority, status, assigned_to, start_date, due_date, labels, bucket`. `Late` is computed (not stored) from `due_date < today AND status ≠ Completed`.
- **Checklist items** — ordered, completed bool, soft-delete supported.

Status: `Not Started`, `In Progress`, `Completed`.
Priority: `Low`, `Medium`, `Important`, `Urgent`.

## Development

```sh
uv run pytest                      # 21 tests across domain, search, exporter, TUI smoke
uv run ruff check src tests
uv run textual run --dev openitems.tui.app:OpenItemsApp   # dev console
```

## Layout

```
src/openitems/
  cli.py                # Typer entrypoints
  config.py paths.py    # platformdirs + TOML config
  db/{engine,models,schema}.py
  domain/               # tasks, checklists, search, audit/undo, dates, text, tag_palette
  export/{theme,workbook}.py        # openpyxl writer mirroring BuildReport()
  tui/
    app.py app.tcss palette.py
    screens/{main, engagement_switcher, new_task, task_detail, export_wizard, help}.py
    widgets/{titlebar, status_bar, bucket_pane, items_pane, detail_pane, filter_bar, task_format}.py
```
