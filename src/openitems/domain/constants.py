from __future__ import annotations

from typing import Final

# Planner-equivalent fixed values.
STATUSES: Final[tuple[str, ...]] = ("Not Started", "In Progress", "Completed")
PRIORITIES: Final[tuple[str, ...]] = ("Low", "Medium", "Important", "Urgent")

PRIORITY_RANK: Final[dict[str, int]] = {p: i for i, p in enumerate(PRIORITIES)}
HIGH_PRIORITIES: Final[frozenset[str]] = frozenset({"Important", "Urgent"})


def cycle_status(current: str) -> str:
    if current not in STATUSES:
        return STATUSES[0]
    return STATUSES[(STATUSES.index(current) + 1) % len(STATUSES)]


def cycle_priority(current: str) -> str:
    if current not in PRIORITIES:
        return PRIORITIES[1]
    return PRIORITIES[(PRIORITIES.index(current) + 1) % len(PRIORITIES)]
