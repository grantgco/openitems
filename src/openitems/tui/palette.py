"""Design tokens — Panic-inspired neon theme on midnight purple."""

from __future__ import annotations

from typing import Final

BG: Final[str] = "#1b1729"
PANEL: Final[str] = "#251f38"
FG: Final[str] = "#e8e2f0"
DIM: Final[str] = "#8a7fa8"
RULE: Final[str] = "#3d3155"
RULE_FOCUS: Final[str] = "#ff8a3a"
ACCENT: Final[str] = "#ff8a3a"
BLUE: Final[str] = "#5cc4ff"
GREEN: Final[str] = "#7fffa9"
RED: Final[str] = "#ff5277"
MAGENTA: Final[str] = "#ff7edb"
CYAN: Final[str] = "#5ee5e5"
HI_ROW: Final[str] = "#2e1f4a"
FOCUS_TINT: Final[str] = "#2a1f3d"

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
