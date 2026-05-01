"""Text sanitation, ported from `modOpenItemsList.bas:821-852` (CleanText).

Strips line breaks, tabs, control characters; collapses whitespace.
"""

from __future__ import annotations

import re

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
