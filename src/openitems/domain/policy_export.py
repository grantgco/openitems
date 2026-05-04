"""CSV export for policies — the inverse of ``policy_import``.

Designed for round-trip: the file written here can be edited in Excel and
fed back through the import wizard, which uses the leading ``id`` column to
update existing rows in place. Live-only by default (skips archived/deleted)
since the round-trip target is the working set.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from pathlib import Path

from openitems.db.models import Policy
from openitems.domain.policy_import import CANONICAL_HEADERS

# ``id`` first so the round-trip key is visually distinct in Excel; the
# remaining columns mirror the import template's order one-for-one.
EXPORT_HEADERS: tuple[str, ...] = ("id", *CANONICAL_HEADERS)


def to_csv_text(policies: Iterable[Policy]) -> str:
    """Render ``policies`` as a UTF-8 CSV string.

    Empty cells stand in for ``None`` dates and blank free-text fields. The
    description column passes through unchanged — ``csv.writer`` handles
    quoting embedded commas, quotes, and newlines without further help.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADERS)
    for p in policies:
        writer.writerow(
            [
                p.id,
                p.name,
                p.carrier,
                p.coverage,
                p.policy_number,
                p.effective_date.isoformat() if p.effective_date else "",
                p.expiration_date.isoformat() if p.expiration_date else "",
                p.location,
                p.description,
            ]
        )
    return buf.getvalue()


def write_to(path: Path, policies: Iterable[Policy]) -> Path:
    """Write a CSV of ``policies`` to ``path`` (parents auto-created).

    Uses ``utf-8-sig`` so Excel on Windows reads it without re-encoding —
    the BOM is harmless for the importer (it strips it via the same
    ``utf-8-sig`` decode path).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = to_csv_text(policies)
    path.write_text(text, encoding="utf-8-sig")
    return path
