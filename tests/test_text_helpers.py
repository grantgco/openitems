from __future__ import annotations

from openitems.domain.tag_palette import TAG_PALETTE, color_for
from openitems.domain.text import clean_text, join_labels, parse_labels


def test_clean_text_strips_control_and_collapses_whitespace():
    assert clean_text("hello\r\n\tworld\x07!") == "hello world !"


def test_clean_text_handles_none_and_empty():
    assert clean_text(None) == ""
    assert clean_text("") == ""


def test_parse_labels_handles_mixed_separators():
    assert parse_labels("api, sec; ops|docs") == ["api", "sec", "ops", "docs"]
    assert parse_labels("") == []
    assert parse_labels(None) == []


def test_join_labels_trims_and_drops_empties():
    assert join_labels(["api ", " sec", "", "  "]) == "api, sec"


def test_color_for_is_deterministic_and_in_palette():
    a = color_for("api")
    b = color_for("api")
    assert a == b
    assert a in TAG_PALETTE
    assert color_for("") == "dim"
