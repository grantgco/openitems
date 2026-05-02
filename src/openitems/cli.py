from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from openitems import paths
from openitems.config import Config
from openitems.db.engine import session_scope
from openitems.db.schema import init_schema
from openitems.domain import engagements as engagements_mod
from openitems.domain import notes as notes_mod
from openitems.domain import tasks as tasks_mod
from openitems.domain.dates import parse_since
from openitems.export.digest import render_digest
from openitems.export.workbook import export_engagement
from openitems.paths import exports_dir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="Open Items List — keyboard-driven task tracker that exports to a Planner-style .xlsx.",
)
engagements_app = typer.Typer(help="Manage engagements (top-level workspaces).")
app.add_typer(engagements_app, name="engagements")
console = Console()


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        # Default action: launch the TUI
        init_schema()
        from openitems.tui.app import OpenItemsApp

        OpenItemsApp().run()


@app.command()
def migrate() -> None:
    """Create or update the local SQLite schema."""
    init_schema()
    console.print(f"[green]✓[/] schema ready at [cyan]{paths.db_path()}[/]")


@app.command()
def doctor() -> None:
    """Show resolved file paths — DB, config, exports — and which override won.

    Resolution order for the DB: ``OPENITEMS_DB`` env var → ``db_path`` in
    config.toml → default ``~/openitems/openitems.db``.
    """
    db = paths.db_path()
    cfg_path = paths.config_path()
    exp = paths.exports_dir()

    env_override = os.environ.get("OPENITEMS_DB")
    cfg = Config.load() if cfg_path.exists() else Config()
    if env_override:
        source = "OPENITEMS_DB env var"
    elif cfg.db_path:
        source = f"config.toml ({cfg_path})"
    else:
        source = "default (~/openitems/)"

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("DB", f"[cyan]{db}[/]")
    table.add_row("DB source", source)
    table.add_row("DB exists", "[green]yes[/]" if db.exists() else "[yellow]no (will be created on first run)[/]")
    table.add_row("config", f"[cyan]{cfg_path}[/]")
    table.add_row("config exists", "[green]yes[/]" if cfg_path.exists() else "[dim]no[/]")
    table.add_row("exports dir", f"[cyan]{exp}[/]")
    table.add_row("active engagement", cfg.active_engagement or "[dim](none)[/]")
    console.print(table)


@engagements_app.command("new")
def engagements_new(
    name: Annotated[str, typer.Argument(help="Display name (e.g. 'Acme Co').")],
) -> None:
    """Create a new engagement."""
    init_schema()
    with session_scope() as s:
        e = engagements_mod.create(s, name)
        console.print(f"[green]✓[/] created [bold]{e.name}[/] (slug: [cyan]{e.slug}[/])")


@engagements_app.command("list")
def engagements_list() -> None:
    """List all active engagements."""
    init_schema()
    with session_scope() as s:
        rows = engagements_mod.list_active(s)
        if not rows:
            console.print("[dim]no engagements yet — create one with[/] [cyan]openitems engagements new \"Acme\"[/]")
            return
        table = Table(show_header=True, header_style="bold")
        table.add_column("slug", style="cyan")
        table.add_column("name")
        table.add_column("created", style="dim")
        for e in rows:
            table.add_row(e.slug, e.name, e.created_at.strftime("%Y-%m-%d"))
        console.print(table)


@app.command()
def export(
    slug: Annotated[str, typer.Argument(help="Engagement slug (see `engagements list`).")],
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output path (default: <exports-dir>/<slug>-YYYY-MM-DD.xlsx — see `openitems doctor`)."),
    ] = None,
    open_after: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open in Excel after writing."),
    ] = False,
) -> None:
    """Export an engagement to a Planner-style .xlsx."""
    init_schema()
    today = date.today()
    with session_scope() as s:
        engagement = engagements_mod.get_by_slug(s, slug)
        if engagement is None:
            console.print(f"[red]✗[/] no engagement with slug [bold]{slug}[/]")
            raise typer.Exit(code=1)

        target = out or (
            exports_dir() / f"{engagement.slug}-{today.strftime('%Y-%m-%d')}.xlsx"
        )
        all_tasks = tasks_mod.list_for(s, engagement, include_completed=True)
        export_engagement(engagement, all_tasks, target, today=today)
        console.print(f"[green]✓[/] exported [bold]{engagement.name}[/] → [cyan]{target}[/]")
        if open_after:
            _open_file(target)


@app.command()
def digest(
    slug: Annotated[str, typer.Argument(help="Engagement slug.")],
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help=(
                "Range start: 'today', 'yesterday', 'monday' (this Monday), "
                "'last-week', 'last-7-days', '7 days ago', or YYYY-MM-DD. "
                "Defaults to this Monday."
            ),
        ),
    ] = "monday",
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Output path (default: <exports>/<slug>-digest-YYYY-MM-DD.md)."),
    ] = None,
    open_after: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the file after writing."),
    ] = False,
) -> None:
    """Generate a Markdown handoff digest for a client engagement.

    Produces a status summary intended for pasting into a client email
    or Slack message: counts, completed-in-range, overdue, in-progress,
    and a chronological activity feed of every note in the window.
    """
    init_schema()
    today = date.today()
    try:
        since_date = parse_since(since, today=today)
    except ValueError as exc:
        console.print(f"[red]✗[/] {exc}")
        raise typer.Exit(code=1) from None

    with session_scope() as s:
        engagement = engagements_mod.get_by_slug(s, slug)
        if engagement is None:
            console.print(f"[red]✗[/] no engagement with slug [bold]{slug}[/]")
            raise typer.Exit(code=1)
        all_tasks = tasks_mod.list_for(s, engagement, include_completed=True)
        all_notes = notes_mod.list_for_engagement(s, engagement)
        body = render_digest(
            engagement,
            all_tasks,
            all_notes,
            since=since_date,
            until=today,
            today=today,
        )

    target = out or (
        exports_dir() / f"{slug}-digest-{today.strftime('%Y-%m-%d')}.md"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    console.print(
        f"[green]✓[/] digest [bold]{slug}[/] [{since_date} → {today}] "
        f"→ [cyan]{target}[/]"
    )
    if open_after:
        _open_file(target)


@app.command()
def quick_export() -> None:
    """Export the active engagement using the last-used settings (mirrors `X` in the TUI)."""
    init_schema()
    cfg = Config.load()
    if not cfg.active_engagement:
        console.print("[red]✗[/] no active engagement set; run [cyan]openitems[/] and pick one.")
        raise typer.Exit(code=1)
    today = date.today()
    with session_scope() as s:
        engagement = engagements_mod.get_by_slug(s, cfg.active_engagement)
        if engagement is None:
            console.print(f"[red]✗[/] active engagement [bold]{cfg.active_engagement}[/] not found.")
            raise typer.Exit(code=1)
        prefs = cfg.prefs_for(engagement.slug)
        target = (
            Path(prefs.last_path)
            if prefs.last_path
            else exports_dir() / f"{engagement.slug}-{today.strftime('%Y-%m-%d')}.xlsx"
        )
        all_tasks = tasks_mod.list_for(s, engagement, include_completed=True)
        export_engagement(engagement, all_tasks, target, today=today)
        prefs.last_path = str(target)
        cfg.export_prefs[engagement.slug] = prefs
        cfg.save()
        console.print(f"[green]✓[/] quick-exported → [cyan]{target}[/]")
        if prefs.open_after_save:
            _open_file(target)


def _open_file(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform == "win32":  # pragma: no cover
        subprocess.run(["start", "", str(path)], shell=True, check=False)
    else:  # pragma: no cover
        subprocess.run(["xdg-open", str(path)], check=False)
