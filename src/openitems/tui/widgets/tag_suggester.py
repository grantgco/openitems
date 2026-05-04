"""Autocomplete suggester for comma-separated tag inputs.

`SuggestFromList` matches the whole input value against the suggestions list,
which is wrong for fields like ``"api, sec"`` where only the trailing token
should be completed. This suggester splits on the last comma and offers a
completion for the current (last) tag while preserving everything the user
already typed.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.suggester import Suggester


class TagSuggester(Suggester):
    """Complete the trailing tag in a comma-separated tag list."""

    def __init__(self, tags: Iterable[str]) -> None:
        super().__init__(case_sensitive=False, use_cache=False)
        # Last casing wins — mirrors `domain.tasks.distinct_labels` so the
        # suggested casing matches what's already in the engagement.
        seen: dict[str, str] = {}
        for tag in tags:
            cf = tag.casefold()
            if cf:
                seen[cf] = tag
        self._tags: list[str] = sorted(seen.values(), key=lambda s: s.casefold())

    async def get_suggestion(self, value: str) -> str | None:
        # ``value`` arrives casefolded (case_sensitive=False).
        if not value:
            return None
        head, sep, tail = value.rpartition(",")
        prefix = head + sep
        stripped = tail.lstrip()
        leading_ws = tail[: len(tail) - len(stripped)]
        rest = stripped
        if not rest:
            return None
        for tag in self._tags:
            tag_cf = tag.casefold()
            if tag_cf == rest:
                continue  # exact match — nothing to complete
            if tag_cf.startswith(rest):
                return prefix + leading_ws + tag
        return None
