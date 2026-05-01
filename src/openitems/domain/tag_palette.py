"""Deterministic free-text tag → palette color.

Free-text labels need stable colors across sessions without configuration.
We hash the label and pick from a fixed rotation of the design palette.
"""

from __future__ import annotations

import hashlib
from typing import Final

# Order matches the design's tag-badge palette in `Open Items TUI.html`:
# blue (api), magenta (sec), green (ops), cyan (design).
TAG_PALETTE: Final[tuple[str, ...]] = (
    "blue",
    "magenta",
    "green",
    "cyan",
    "accent",
)


def color_for(tag: str) -> str:
    if not tag:
        return "dim"
    digest = hashlib.md5(tag.lower().encode("utf-8")).digest()
    return TAG_PALETTE[digest[0] % len(TAG_PALETTE)]
