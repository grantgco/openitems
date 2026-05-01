from __future__ import annotations

from datetime import date

from rich.text import Text

from openitems.domain.tag_palette import color_for
from openitems.domain.text import parse_labels
from openitems.tui import palette


def format_tags(labels: str) -> Text:
    text = Text()
    for i, label in enumerate(parse_labels(labels)):
        if i:
            text.append(" ")
        color = palette.TAG_COLORS.get(color_for(label), palette.FG)
        text.append(label, style=color)
    return text


def format_priority(priority: str) -> Text:
    if priority in {"Urgent", "Important"}:
        return Text(priority.upper()[:4], style=f"bold {palette.RED}")
    if priority == "Low":
        return Text("low", style=palette.DIM)
    return Text("med", style=palette.FG)


def format_due(due: date | None, late: bool) -> Text:
    if due is None:
        return Text("─", style=palette.DIM)
    label = due.strftime("%m-%d")
    if late:
        return Text(f"{label} ◆", style=f"bold {palette.RED}")
    return Text(label, style=palette.FG)


def format_date(d: date | None) -> Text:
    return Text(d.strftime("%m-%d-%Y") if d else "─", style=palette.FG if d else palette.DIM)
