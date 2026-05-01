"""Design tokens (mapped 1:1 from `Open Items TUI.html` :10-36)."""

from __future__ import annotations

from typing import Final

BG: Final[str] = "#1a1d22"
PANEL: Final[str] = "#1f2329"
FG: Final[str] = "#d6d2c8"
DIM: Final[str] = "#7a7468"
RULE: Final[str] = "#3a3f47"
RULE_FOCUS: Final[str] = "#d6b35a"
ACCENT: Final[str] = "#d6b35a"
BLUE: Final[str] = "#6fa8c7"
GREEN: Final[str] = "#88b070"
RED: Final[str] = "#d57367"
MAGENTA: Final[str] = "#b58fc2"
CYAN: Final[str] = "#70b0a8"
HI_ROW: Final[str] = "#2a2820"  # approximated from rgba(214,179,90,0.14) on bg
FOCUS_TINT: Final[str] = "#1f1d18"  # approximated from rgba(214,179,90,0.06) on bg

# Map domain `tag_palette.color_for` keys → hex
TAG_COLORS: Final[dict[str, str]] = {
    "blue": BLUE,
    "magenta": MAGENTA,
    "green": GREEN,
    "cyan": CYAN,
    "accent": ACCENT,
    "dim": DIM,
}

PRIORITY_COLORS: Final[dict[str, str]] = {
    "Low": DIM,
    "Medium": FG,
    "Important": RED,
    "Urgent": RED,
}
