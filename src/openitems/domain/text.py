"""Text sanitation, ported from `modOpenItemsList.bas:821-852` (CleanText).

Strips line breaks, tabs, control characters; collapses whitespace.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_WS_RE = re.compile(r"\s+")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    no_ctrl = _CTRL_RE.sub(" ", value)
    return _WS_RE.sub(" ", no_ctrl).strip()


def parse_labels(raw: str | None) -> list[str]:
    """Split a Planner-style labels field on common separators."""
    if not raw:
        return []
    cleaned = raw.replace(";", ",").replace("|", ",")
    parts = [p.strip() for p in cleaned.split(",")]
    return [p for p in parts if p]


def join_labels(labels: list[str] | tuple[str, ...]) -> str:
    return ", ".join(label for label in (lbl.strip() for lbl in labels) if label)


def normalize_url(value: str | None) -> str | None:
    """Coerce a user-typed URL to something ``webbrowser.open`` will treat
    as an http(s) link.

    - Empty / whitespace → ``None`` so the caller can clear the field.
    - Already has a scheme (``https:``, ``http:``, ``mailto:``, ``ftp:``,
      ``file:``) → trim and return as-is.
    - Otherwise prepend ``https://`` so ``github.com/foo`` doesn't end up
      as a filesystem path on macOS (the silent-failure mode).

    Whitespace-only input is treated as empty. ``urllib.parse.urlsplit``
    is used to detect the scheme so we don't get fooled by colons in the
    path (e.g. ``example.com/page:edit``).
    """
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme:
        return raw
    return f"https://{raw}"
