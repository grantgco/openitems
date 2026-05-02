from __future__ import annotations

from datetime import date
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from openitems.config import Config, ExportPrefs
from openitems.db.engine import session_scope
from openitems.domain import engagements, tasks
from openitems.export.workbook import export_engagement
from openitems.paths import exports_dir

ALL_COLUMNS: tuple[str, ...] = (
    "#",
    "Task",
    "Tags",
    "Priority",
    "Assigned To",
    "Start",
    "Due",
    "Description",
    "Bucket",
    "Progress %",
    "Checklist",
)
DEFAULT_COLUMNS: tuple[str, ...] = (
    "#",
    "Task",
    "Tags",
    "Priority",
    "Assigned To",
    "Start",
    "Due",
    "Description",
    "Checklist",
)


def _default_path(slug: str) -> Path:
    return exports_dir() / f"{slug}-{date.today().strftime('%Y-%m-%d')}.xlsx"


def quick_export(slug: str) -> Path | None:
    """Run an export immediately using the last-used prefs (fallback to defaults)."""
    cfg = Config.load()
    prefs = cfg.prefs_for(slug)
    target = Path(prefs.last_path) if prefs.last_path else _default_path(slug)
    today = date.today()
    with session_scope() as s:
        e = engagements.get_by_slug(s, slug)
        if e is None:
            return None
        all_tasks = tasks.list_for(s, e, include_completed=True)
        export_engagement(e, all_tasks, target, today=today)
    prefs.last_path = str(target)
    cfg.export_prefs[slug] = prefs
    cfg.save()
    return target


class ExportWizardScreen(ModalScreen[Path | None]):
    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("enter", "next", "next", show=False),
        Binding("r", "reset", "reset to defaults", show=False),
    ]

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        self.step = 1
        self.cfg = Config.load()
        self.prefs = self.cfg.prefs_for(engagement_slug)
        self.columns: list[str] = list(self.prefs.columns or DEFAULT_COLUMNS)

        self.body = Static("", id="wizard-body")
        self.footer = Static("", id="wizard-footer")
        self.col_options = OptionList(id="column-options")
        self.path_input = Input(value="", placeholder="Output path", id="path-input")
        self.open_after = Checkbox("Open in Excel after save", value=self.prefs.open_after_save)

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]export → .xlsx[/b]", classes="modal-title")
            yield self.body
            yield self.col_options
            yield self.path_input
            yield self.open_after
            yield self.footer
            with Horizontal():
                yield Button("Back  (Esc)", id="back")
                yield Button("Next  (Enter)", id="next", classes="-primary")

    def on_mount(self) -> None:
        self.path_input.value = str(_default_path(self.engagement_slug))
        self._render_step()

    def _render_step(self) -> None:
        if self.step == 1:
            self.body.update(self._step1_body())
            self.col_options.display = False
            self.path_input.display = False
            self.open_after.display = False
            self.footer.update("[dim]step 1/3 · filter (uses current main-view filter)[/dim]")
        elif self.step == 2:
            self.body.update("[dim]columns & order  (space toggles, J/K reorders)[/dim]")
            self.col_options.display = True
            self.path_input.display = False
            self.open_after.display = False
            self._refresh_columns()
            self.col_options.focus()
            self.footer.update("[dim]step 2/3 · columns · r resets to defaults[/dim]")
        else:
            self.body.update("[dim]choose where to save[/dim]")
            self.col_options.display = False
            self.path_input.display = True
            self.open_after.display = True
            self.path_input.focus()
            self.footer.update("[dim]step 3/3 · file[/dim]")

    def _step1_body(self) -> str:
        return (
            "[dim]filter · using current main-view filter (refine in step 2 or after).[/dim]\n"
            "[dim]press Enter to continue.[/dim]"
        )

    def _refresh_columns(self) -> None:
        self.col_options.clear_options()
        selected = set(self.columns)
        for col in ALL_COLUMNS:
            mark = "[x] " if col in selected else "[ ] "
            self.col_options.add_option(Option(mark + col, id=col))

    @on(OptionList.OptionSelected, "#column-options")
    def _toggle_column(self, event: OptionList.OptionSelected) -> None:
        col_id = event.option.id
        if not col_id:
            return
        if col_id in self.columns:
            self.columns.remove(col_id)
        else:
            self.columns.append(col_id)
        self._refresh_columns()

    @on(Button.Pressed, "#next")
    def _next_btn(self, _: Button.Pressed) -> None:
        self.action_next()

    @on(Button.Pressed, "#back")
    def _back_btn(self, _: Button.Pressed) -> None:
        self.action_back()

    def action_back(self) -> None:
        if self.step == 1:
            self.dismiss(None)
        else:
            self.step -= 1
            self._render_step()

    def action_next(self) -> None:
        if self.step < 3:
            self.step += 1
            self._render_step()
        else:
            self._finish()

    def action_reset(self) -> None:
        if self.step == 2:
            self.columns = list(DEFAULT_COLUMNS)
            self._refresh_columns()

    def _finish(self) -> None:
        raw = self.path_input.value.strip()
        if not raw:
            self.app.notify("Output path is empty.", severity="warning")
            return
        target = Path(raw).expanduser()
        if target.suffix.lower() != ".xlsx":
            target = target.with_suffix(".xlsx")
        target.parent.mkdir(parents=True, exist_ok=True)
        today = date.today()
        try:
            with session_scope() as s:
                e = engagements.get_by_slug(s, self.engagement_slug)
                if e is None:
                    self.app.notify("Engagement gone.", severity="error")
                    return
                all_tasks = tasks.list_for(s, e, include_completed=True)
                export_engagement(e, all_tasks, target, today=today)
        except (OSError, PermissionError) as exc:
            self.app.notify(f"Couldn't write {target}: {exc}", severity="error")
            return

        self.prefs = ExportPrefs(
            columns=list(self.columns),
            open_after_save=bool(self.open_after.value),
            last_path=str(target),
        )
        self.cfg.export_prefs[self.engagement_slug] = self.prefs
        self.cfg.save()
        self.app.notify(f"Exported → {target}")
        self.dismiss(target)
