"""3-step CSV import wizard for policies, scoped to the active engagement.

Step 1 — pick the source path (with a "Save template…" affordance that copies
the bundled `examples/policies-import-template.csv` to a user-chosen path).
Step 2 — preview every row classified as new / duplicate / error.
Step 3 — confirm and import; results are surfaced via ``app.notify`` and the
modal dismisses with ``True`` if at least one row was inserted (so the caller
can refresh).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from openitems.config import Config
from openitems.db.engine import session_scope
from openitems.domain import engagements, policy_import
from openitems.domain.policy_import import ImportFileError, ImportPreview, RowOutcome
from openitems.tui import palette


class ImportPoliciesScreen(ModalScreen[bool]):
    """Bulk-import policies into the active engagement from a CSV file."""

    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("enter", "next", "next", show=False),
        Binding("b", "back", "back", show=False),
    ]

    DEFAULT_CSS = """
    ImportPoliciesScreen #wizard-summary {
        padding: 0 1;
    }
    ImportPoliciesScreen #preview-table {
        height: 18;
        border: round #ff8a3a;
        margin: 1 0;
    }
    ImportPoliciesScreen #template-row {
        height: auto;
        padding: 1 0 0 0;
    }
    ImportPoliciesScreen .field-label {
        color: #8a7fa8;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, engagement_slug: str) -> None:
        super().__init__()
        self.engagement_slug = engagement_slug
        self.step = 1
        self.cfg = Config.load()
        self._engagement_name = ""
        self._preview: ImportPreview | None = None

        self.body = Static("", id="wizard-body")
        self.summary = Static("", id="wizard-summary")
        self.path_input = Input(
            value=self.cfg.last_import_path or "",
            placeholder="~/openitems/imports/policies.csv",
            id="csv-path",
        )
        self.template_input = Input(
            placeholder="~/openitems/imports/policies-template.csv",
            id="template-path",
        )
        self.template_input.display = False
        self.template_btn = Button("Save template…", id="save-template")
        self.preview_table = DataTable(
            zebra_stripes=False,
            header_height=1,
            cursor_type="row",
            id="preview-table",
        )
        self.next_btn = Button("Next  (Enter)", id="next", classes="-primary")
        self.back_btn = Button("Back  (Esc)", id="back")

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="modal"):
            yield Label("[b]import policies → CSV[/b]", classes="modal-title")
            yield self.body
            yield Label("CSV path", classes="field-label")
            yield self.path_input
            with Vertical(id="template-row"):
                with Horizontal():
                    yield self.template_btn
                yield self.template_input
            yield self.preview_table
            yield self.summary
            with Horizontal():
                yield self.back_btn
                yield self.next_btn

    def on_mount(self) -> None:
        with session_scope() as s:
            e = engagements.get_by_slug(s, self.engagement_slug)
            self._engagement_name = e.name if e else self.engagement_slug
        self.preview_table.display = False
        self._render_step()

    # --- step rendering ---------------------------------------------------

    def _render_step(self) -> None:
        if self.step == 1:
            self._render_step_1()
        elif self.step == 2:
            self._render_step_2()
        else:
            self._render_step_3()

    def _render_step_1(self) -> None:
        self.body.update(
            "[dim]step 1/3 · point at a CSV. The header row must include "
            "[b]name[/b]; the other columns (carrier, coverage, policy_number, "
            "effective_date, expiration_date, location, description) are "
            "optional. Use the template if you'd like a starting point.[/dim]"
        )
        self.path_input.display = True
        self.template_btn.display = True
        self.template_input.display = False
        self.preview_table.display = False
        self.summary.update("")
        self.path_input.focus()

    def _render_step_2(self) -> None:
        assert self._preview is not None
        pre = self._preview
        notes: list[str] = []
        if pre.unknown_columns:
            notes.append(f"Ignored unknown columns: {', '.join(pre.unknown_columns)}")
        if pre.skipped_blank_rows:
            notes.append(f"Skipped {pre.skipped_blank_rows} blank row(s)")
        suffix = "\n" + "\n".join(f"[dim]{note}[/dim]" for note in notes) if notes else ""
        self.body.update(
            "[dim]step 2/3 · review what will happen. [b]new[/b] rows are "
            "inserted, [b]update[/b] rows (matched by id) overwrite the existing "
            "policy in place; duplicates and errors are skipped.[/dim]"
            + suffix
        )
        self.path_input.display = False
        self.template_btn.display = False
        self.template_input.display = False
        self.preview_table.display = True
        self._populate_preview_table(pre)
        self.summary.update(self._summary_line(pre))
        if pre.applies_count == 0:
            self.next_btn.disabled = True
            self.next_btn.label = "Nothing to import"
        else:
            self.next_btn.disabled = False
            self.next_btn.label = "Next  (Enter)"
        # Focus the Next button rather than the preview DataTable: Textual's
        # DataTable swallows the Enter key for its own select_cursor binding,
        # so a focused table would silently absorb the wizard's advance key.
        self.next_btn.focus()

    def _render_step_3(self) -> None:
        assert self._preview is not None
        pre = self._preview
        write_bits: list[str] = []
        if pre.new_count:
            write_bits.append(
                f"insert [b]{pre.new_count}[/b] "
                f"polic{'y' if pre.new_count == 1 else 'ies'}"
            )
        if pre.update_count:
            write_bits.append(
                f"update [b]{pre.update_count}[/b] "
                f"polic{'y' if pre.update_count == 1 else 'ies'}"
            )
        action = " and ".join(write_bits) or "do nothing"
        self.body.update(
            f"[dim]step 3/3 · confirm.[/dim]\n\n"
            f"{action.capitalize()} in [b]{self._engagement_name}[/b]? "
            f"{pre.duplicate_count} duplicate(s) and "
            f"{pre.error_count} error(s) will be skipped."
        )
        self.path_input.display = False
        self.template_btn.display = False
        self.template_input.display = False
        self.preview_table.display = False
        self.summary.update("")
        self.next_btn.disabled = False
        self.next_btn.label = "Import  (Enter)"
        self.next_btn.focus()

    def _summary_line(self, pre: ImportPreview) -> str:
        return (
            f"[b green]{pre.new_count} new[/b green]  ·  "
            f"[b cyan]{pre.update_count} update[/b cyan]  ·  "
            f"[b yellow]{pre.duplicate_count} duplicate[/b yellow]  ·  "
            f"[b red]{pre.error_count} error[/b red]"
        )

    def _populate_preview_table(self, pre: ImportPreview) -> None:
        self.preview_table.clear(columns=True)
        self.preview_table.add_columns(
            "Line", "Status", "Name", "Carrier", "Policy #",
            "Effective", "Expiration", "Note",
        )
        for r in pre.rows:
            self.preview_table.add_row(
                str(r.line),
                _status_cell(r.status),
                _value(r, "name"),
                _value(r, "carrier"),
                _value(r, "policy_number"),
                _date_value(r, "effective_date"),
                _date_value(r, "expiration_date"),
                Text(r.message, style=palette.DIM),
            )

    # --- actions ----------------------------------------------------------

    @on(Button.Pressed, "#next")
    def _next_btn(self, _: Button.Pressed) -> None:
        self.action_next()

    @on(Button.Pressed, "#back")
    def _back_btn(self, _: Button.Pressed) -> None:
        self.action_back()

    @on(Button.Pressed, "#save-template")
    def _save_template_btn(self, _: Button.Pressed) -> None:
        self.template_input.display = True
        if not self.template_input.value:
            self.template_input.value = str(
                Path("~/openitems/imports/policies-import-template.csv").expanduser()
            )
        self.template_input.focus()

    @on(Input.Submitted, "#template-path")
    def _template_submitted(self, event: Input.Submitted) -> None:
        self._save_template(event.value)

    def _save_template(self, raw: str) -> None:
        target = raw.strip()
        if not target:
            self.app.notify("Template path is empty.", severity="warning")
            return
        dest = Path(target).expanduser()
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(policy_import.template_path(), dest)
        except (OSError, PermissionError) as exc:
            self.app.notify(f"Couldn't write {dest}: {exc}", severity="error")
            return
        self.template_input.display = False
        if not self.path_input.value:
            self.path_input.value = str(dest)
        self.app.notify(f"Template saved → {dest}")
        self.path_input.focus()

    def action_back(self) -> None:
        if self.step == 1:
            self.dismiss(False)
        else:
            self.step -= 1
            self._render_step()

    def action_next(self) -> None:
        if self.step == 1:
            if self._build_preview():
                self.step = 2
                self._render_step()
        elif self.step == 2:
            assert self._preview is not None
            if self._preview.applies_count == 0:
                return
            self.step = 3
            self._render_step()
        else:
            self._finish()

    def _build_preview(self) -> bool:
        raw = self.path_input.value.strip()
        if not raw:
            self.app.notify("CSV path is empty.", severity="warning")
            return False
        path = Path(raw).expanduser()
        if not path.exists():
            self.app.notify(f"File not found: {path}", severity="error")
            return False
        try:
            with session_scope() as s:
                e = engagements.get_by_slug(s, self.engagement_slug)
                if e is None:
                    self.app.notify("Engagement disappeared.", severity="error")
                    return False
                self._preview = policy_import.preview(s, e, path)
        except ImportFileError as exc:
            self.app.notify(str(exc), severity="error")
            return False

        self.cfg.last_import_path = str(path)
        self.cfg.save()
        return True

    def _finish(self) -> None:
        assert self._preview is not None
        try:
            with session_scope() as s:
                e = engagements.get_by_slug(s, self.engagement_slug)
                if e is None:
                    self.app.notify("Engagement disappeared.", severity="error")
                    self.dismiss(False)
                    return
                result = policy_import.commit(s, e, self._preview)
        except Exception as exc:
            self.app.notify(f"Import failed: {exc}", severity="error")
            self.dismiss(False)
            return

        bits = [f"{result.imported} imported"]
        if result.updated:
            bits.append(f"{result.updated} updated")
        if result.skipped_duplicates:
            bits.append(f"{result.skipped_duplicates} skipped")
        if result.errors:
            bits.append(f"{result.errors} error(s)")
        self.app.notify("Policies: " + ", ".join(bits))
        self.dismiss(result.imported + result.updated > 0)


def _status_cell(status: str) -> Text:
    if status == "new":
        return Text("NEW", style=f"bold {palette.GREEN}")
    if status == "update":
        return Text("UPDATE", style=f"bold {palette.CYAN}")
    if status == "duplicate":
        return Text("DUPLICATE", style=f"bold {palette.ACCENT}")
    return Text("ERROR", style=f"bold {palette.RED}")


def _value(row: RowOutcome, field: str) -> Text:
    if row.input is not None:
        raw = getattr(row.input, field, "") or ""
    else:
        raw = row.raw.get(field, "") or row.raw.get(field.replace("_", " "), "")
    if not raw:
        return Text("—", style=palette.DIM)
    return Text(str(raw), style=palette.FG)


def _date_value(row: RowOutcome, field: str) -> Text:
    if row.input is not None:
        d = getattr(row.input, field, None)
        if d is None:
            return Text("—", style=palette.DIM)
        return Text(d.isoformat(), style=palette.FG)
    raw = row.raw.get(field, "")
    if not raw:
        return Text("—", style=palette.DIM)
    return Text(raw, style=palette.DIM)
