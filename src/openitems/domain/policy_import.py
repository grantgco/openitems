"""CSV bulk-import for policies, scoped to a single engagement.

Two-phase: ``preview()`` reads + classifies every row without touching the DB,
and ``commit()`` inserts the rows the preview marked ``new`` via the regular
``policies.create`` path. Dedup is by case-insensitive ``(carrier, policy_number)``
within the engagement; rows where both halves are blank are never treated as
duplicates (insert-only).

Hardening choices (driven by real-world Excel exports):

- **Encoding**: tries ``utf-8-sig`` (handles UTF-8 with optional BOM) then
  ``cp1252`` (Excel's default on Windows). Falls back with a clear error
  rather than corrupting smart quotes / non-ASCII silently.
- **Delimiter**: sniffed via ``csv.Sniffer`` so semicolon-delimited files
  (European Excel) and tab-separated work without configuration.
- **Blank rows**: silently skipped — common at the end of a file.
- **Size cap**: hard limit of ``MAX_ROWS`` to protect against pathological
  input (a multi-million-row CSV would otherwise OOM the preview).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from openitems.db.models import Engagement, Policy
from openitems.domain import policies
from openitems.domain.dates import DateParseError, parse_strict
from openitems.domain.policies import PolicyDateError, PolicyInput

CANONICAL_HEADERS: tuple[str, ...] = (
    "name",
    "carrier",
    "coverage",
    "policy_number",
    "effective_date",
    "expiration_date",
    "location",
    "description",
)

# Order matters: try UTF-8 (with BOM tolerance) first so we don't mojibake a
# unicode file by re-decoding it as cp1252.
SUPPORTED_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252")
SNIFF_DELIMITERS: str = ",;\t|"
MAX_ROWS: int = 10_000

RowStatus = Literal["new", "update", "duplicate", "error"]


class ImportFileError(ValueError):
    """Raised when the CSV cannot be opened, decoded, or has no header row."""


@dataclass(frozen=True)
class RowOutcome:
    line: int  # 1-based, header is line 1; first data row is line 2
    raw: dict[str, str]
    status: RowStatus
    input: PolicyInput | None = None
    message: str = ""
    dedup_key: tuple[str, str] | None = None
    existing_id: str | None = None  # set on ``update`` rows: the policy id to patch


@dataclass(frozen=True)
class ImportPreview:
    rows: list[RowOutcome]
    unknown_columns: list[str] = field(default_factory=list)
    skipped_blank_rows: int = 0

    @property
    def new_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "new")

    @property
    def update_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "update")

    @property
    def duplicate_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "duplicate")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.rows if r.status == "error")

    @property
    def applies_count(self) -> int:
        """Rows the importer will write — inserts plus in-place updates."""
        return self.new_count + self.update_count


@dataclass(frozen=True)
class ImportResult:
    imported: int
    updated: int
    skipped_duplicates: int
    errors: int
    error_messages: list[str]


def template_path() -> Path:
    """Filesystem path to the bundled template CSV.

    Works from a source checkout and from an installed wheel — uses
    ``importlib.resources`` against the ``openitems.examples`` package.
    """
    return Path(str(resources.files("openitems.examples").joinpath("policies-import-template.csv")))


def preview(
    session: Session,
    engagement: Engagement,
    path: Path,
) -> ImportPreview:
    """Read ``path``, validate every row, classify against existing dedup keys.

    Pure read — does not insert or flush. The returned ``ImportPreview`` is
    handed back to ``commit()`` to perform the actual inserts.
    """
    try:
        text = _decode_file(path)
    except OSError as exc:
        raise ImportFileError(f"Couldn't open {path}: {exc}") from exc
    return _preview_from_text(session, engagement, text)


def _decode_file(path: Path) -> str:
    """Read ``path`` trying UTF-8 (with BOM tolerance) then Windows-1252.

    Excel on Windows still defaults CSV exports to cp1252, so a hard utf-8
    requirement would reject perfectly normal broker-delivered files.
    """
    last_exc: UnicodeDecodeError | None = None
    for enc in SUPPORTED_ENCODINGS:
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError as exc:
            last_exc = exc
    raise ImportFileError(
        f"Couldn't decode {path} as "
        f"{' or '.join(SUPPORTED_ENCODINGS)}. "
        "Re-save the file as UTF-8 (Excel: 'CSV UTF-8') and try again."
    ) from last_exc


def _sniff_dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    """Detect the CSV dialect from the first few KB.

    Returns ``csv.excel`` (comma-default) when the sniffer can't decide —
    that's the right shape for the bundled template and the most common
    user input.
    """
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=SNIFF_DELIMITERS)
    except csv.Error:
        return csv.excel


def _preview_from_text(
    session: Session,
    engagement: Engagement,
    text: str,
) -> ImportPreview:
    dialect = _sniff_dialect(text)
    reader = csv.reader(io.StringIO(text), dialect)
    return _preview_from_reader(session, engagement, reader)


def _preview_from_reader(
    session: Session,
    engagement: Engagement,
    reader,  # csv.reader instance — runtime-only type
) -> ImportPreview:
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise ImportFileError("CSV is empty (no header row).") from exc

    normalized = [h.strip().lower() for h in header_row]
    known_indices: dict[str, int] = {}
    id_index: int | None = None
    unknown: list[str] = []
    for idx, key in enumerate(normalized):
        if not key:
            continue
        if key == "id":
            id_index = idx
            continue
        if key in CANONICAL_HEADERS:
            known_indices.setdefault(key, idx)
        else:
            unknown.append(header_row[idx])

    if "name" not in known_indices:
        raise ImportFileError(
            "CSV header is missing the required 'name' column. "
            f"Got: {', '.join(repr(h) for h in header_row) or '(empty header)'}."
        )

    existing_keys = _existing_dedup_keys(session, engagement)
    existing_ids = _existing_policy_ids(session, engagement)
    seen_in_csv: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    rows: list[RowOutcome] = []
    skipped_blanks = 0

    for raw_row in reader:
        line_offset = reader.line_num
        if not _row_has_content(raw_row):
            skipped_blanks += 1
            continue
        if len(rows) >= MAX_ROWS:
            raise ImportFileError(
                f"CSV has more than {MAX_ROWS:,} rows; split it into smaller "
                "files before importing. (This guard prevents an out-of-memory "
                "preview on a malformed file.)"
            )
        raw = _row_to_dict(normalized, raw_row)
        row_id = _cell(raw_row, id_index) if id_index is not None else ""

        try:
            input_ = _row_to_input(raw_row, known_indices)
        except (DateParseError, PolicyDateError, ValueError) as exc:
            rows.append(
                RowOutcome(line=line_offset, raw=raw, status="error", message=str(exc))
            )
            continue

        if row_id:
            if row_id in seen_ids:
                rows.append(
                    RowOutcome(
                        line=line_offset,
                        raw=raw,
                        status="error",
                        input=input_,
                        message=f"id '{row_id}' appears more than once in this CSV.",
                    )
                )
                continue
            if row_id not in existing_ids:
                # An id present in the CSV but not in this engagement is
                # almost always an editing accident — a row pasted from a
                # different engagement's export, or a stale file from before
                # the policy was deleted. Surface as an error rather than
                # silently inserting a row with a foreign id.
                rows.append(
                    RowOutcome(
                        line=line_offset,
                        raw=raw,
                        status="error",
                        input=input_,
                        message=f"id '{row_id}' is not a policy in this engagement.",
                    )
                )
                continue
            seen_ids.add(row_id)
            rows.append(
                RowOutcome(
                    line=line_offset,
                    raw=raw,
                    status="update",
                    input=input_,
                    existing_id=row_id,
                )
            )
            continue

        key = _dedup_key(input_)
        if key is None:
            rows.append(RowOutcome(line=line_offset, raw=raw, status="new", input=input_))
            continue
        if key in existing_keys or key in seen_in_csv:
            reason = (
                "Already exists in this engagement."
                if key in existing_keys
                else "Duplicate of an earlier row in this CSV."
            )
            rows.append(
                RowOutcome(
                    line=line_offset,
                    raw=raw,
                    status="duplicate",
                    input=input_,
                    message=reason,
                    dedup_key=key,
                )
            )
            continue

        seen_in_csv.add(key)
        rows.append(
            RowOutcome(
                line=line_offset,
                raw=raw,
                status="new",
                input=input_,
                dedup_key=key,
            )
        )

    return ImportPreview(
        rows=rows,
        unknown_columns=unknown,
        skipped_blank_rows=skipped_blanks,
    )


def commit(
    session: Session,
    engagement: Engagement,
    preview_obj: ImportPreview,
) -> ImportResult:
    """Apply every ``new`` and ``update`` row.

    Inserts go through ``policies.create``; updates go through ``policies.update``
    against the row identified by ``existing_id``. Defensive: if either call
    raises for a row the preview classified as writeable (shouldn't happen —
    preview validates with the same code paths), the row is counted as an
    error rather than aborting the whole import.
    """
    imported = 0
    updated = 0
    errors: list[str] = []
    for row in preview_obj.rows:
        if row.input is None:
            continue
        try:
            if row.status == "new":
                policies.create(session, engagement, row.input)
                imported += 1
            elif row.status == "update":
                target = session.get(Policy, row.existing_id) if row.existing_id else None
                if target is None or target.engagement_id != engagement.id:
                    errors.append(
                        f"Line {row.line}: id '{row.existing_id}' "
                        "no longer exists in this engagement."
                    )
                    continue
                policies.update(
                    session,
                    target,
                    name=row.input.name,
                    carrier=row.input.carrier,
                    coverage=row.input.coverage,
                    policy_number=row.input.policy_number,
                    effective_date=row.input.effective_date,
                    expiration_date=row.input.expiration_date,
                    location=row.input.location,
                    description=row.input.description,
                )
                updated += 1
        except (PolicyDateError, ValueError) as exc:
            errors.append(f"Line {row.line}: {exc}")
    return ImportResult(
        imported=imported,
        updated=updated,
        skipped_duplicates=preview_obj.duplicate_count,
        errors=preview_obj.error_count + len(errors),
        error_messages=[
            *(f"Line {r.line}: {r.message}" for r in preview_obj.rows if r.status == "error"),
            *errors,
        ],
    )


def _row_has_content(raw_row: list[str]) -> bool:
    return any(c and c.strip() for c in raw_row)


def _existing_dedup_keys(session: Session, engagement: Engagement) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for p in policies.list_for(session, engagement):
        carrier = (p.carrier or "").strip().lower()
        number = (p.policy_number or "").strip().lower()
        if not carrier and not number:
            continue
        keys.add((carrier, number))
    return keys


def _existing_policy_ids(session: Session, engagement: Engagement) -> set[str]:
    """Return ids of every live policy on ``engagement``.

    Soft-deleted policies are deliberately excluded — re-importing a row
    that points at a deleted id should fail loud rather than resurrect a
    row the user already removed. Archived policies are included so the
    round-trip still works against historical rows that happen to be in
    the export.
    """
    stmt = (
        select(Policy.id)
        .where(Policy.engagement_id == engagement.id)
        .where(Policy.deleted_at.is_(None))
    )
    return set(session.scalars(stmt))


def _row_to_dict(headers_lower: list[str], raw_row: list[str]) -> dict[str, str]:
    """Build a dict keyed by the *lowercased* header name.

    Wizard code looks up by canonical (lowercase) field name; storing keys in
    their original casing would cause "error" rows (which can't fall back to
    PolicyInput) to render every cell as "—" when the CSV used Title-Case headers.
    """
    out: dict[str, str] = {}
    for idx, header in enumerate(headers_lower):
        if not header:
            continue
        out[header] = raw_row[idx] if idx < len(raw_row) else ""
    return out


def _cell(raw_row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(raw_row):
        return ""
    return raw_row[idx].strip()


def _row_to_input(raw_row: list[str], headers: dict[str, int]) -> PolicyInput:
    name = _cell(raw_row, headers.get("name"))
    if not name:
        raise ValueError("'name' is required.")

    eff = parse_strict(
        _cell(raw_row, headers.get("effective_date")),
        field="effective_date",
        prefer="current_period",
    )
    exp = parse_strict(
        _cell(raw_row, headers.get("expiration_date")),
        field="expiration_date",
        prefer="current_period",
    )
    if eff is not None and exp is not None and eff > exp:
        raise PolicyDateError(
            f"Effective date ({eff.isoformat()}) is after expiration ({exp.isoformat()})."
        )

    return PolicyInput(
        name=name,
        carrier=_cell(raw_row, headers.get("carrier")),
        coverage=_cell(raw_row, headers.get("coverage")),
        policy_number=_cell(raw_row, headers.get("policy_number")),
        effective_date=eff,
        expiration_date=exp,
        location=_cell(raw_row, headers.get("location")),
        description=_cell(raw_row, headers.get("description")),
    )


def _dedup_key(input_: PolicyInput) -> tuple[str, str] | None:
    carrier = input_.carrier.strip().lower()
    number = input_.policy_number.strip().lower()
    if not carrier and not number:
        return None
    return (carrier, number)


def from_iterable(
    session: Session,
    engagement: Engagement,
    lines: Iterable[str],
) -> ImportPreview:
    """Test seam: build a preview from in-memory CSV lines without touching disk."""
    return _preview_from_text(session, engagement, "\n".join(lines))
