from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from openitems.config import Config
from openitems.db.engine import session_scope
from openitems.db.schema import init_schema
from openitems.domain import engagements as engagements_mod
from openitems.domain import tasks as tasks_mod
from openitems.export.workbook import export_engagement
from openitems.paths import db_path, exports_dir

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
    console.print(f"[green]✓[/] schema ready at [cyan]{db_path()}[/]")


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
        typer.Option("--out", "-o", help="Output path (default: ~/Library/.../exports/<slug>-YYYY-MM-DD.xlsx)."),
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
