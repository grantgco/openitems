from __future__ import annotations

import asyncio

import pytest

from openitems.tui.widgets.tag_suggester import TagSuggester


def _suggest(suggester: TagSuggester, value: str) -> str | None:
    # Suggesters receive casefolded input when case_sensitive=False (the
    # widget normalizes before calling), so simulate that here.
    return asyncio.run(suggester.get_suggestion(value.casefold()))


@pytest.fixture
def suggester() -> TagSuggester:
    return TagSuggester(["api", "audit", "Security", "docs"])


def test_completes_first_token(suggester: TagSuggester) -> None:
    # Single token, no comma — completes the whole thing.
    assert _suggest(suggester, "ap") == "api"
    assert _suggest(suggester, "Sec") == "Security"


def test_completes_trailing_token_after_comma(suggester: TagSuggester) -> None:
    # The committed prefix is preserved (in casefolded form — Input renders
    # the user's original casing back in via length-based slicing).
    assert _suggest(suggester, "api, Sec") == "api, Security"
    assert _suggest(suggester, "docs,au") == "docs,audit"


def test_no_suggestion_when_token_empty(suggester: TagSuggester) -> None:
    assert _suggest(suggester, "") is None
    assert _suggest(suggester, "api,") is None
    assert _suggest(suggester, "api, ") is None


def test_no_suggestion_when_already_complete(suggester: TagSuggester) -> None:
    # Exact (casefolded) match — nothing to add.
    assert _suggest(suggester, "api") is None
    assert _suggest(suggester, "docs, Security") is None


def test_no_suggestion_when_no_match(suggester: TagSuggester) -> None:
    assert _suggest(suggester, "xyz") is None
    assert _suggest(suggester, "api, xyz") is None


def test_dedupes_input_tags() -> None:
    # Same casefolded tag passed twice → only one appears, latest casing wins.
    s = TagSuggester(["api", "API"])
    assert _suggest(s, "ap") == "API"
