from __future__ import annotations

from openitems.domain.tag_palette import TAG_PALETTE, color_for
from openitems.domain.text import clean_text, join_labels, normalize_url, parse_labels


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


def test_normalize_url_prepends_https_when_missing_scheme():
    """Schemeless URLs typed by humans should round-trip as http(s).

    Without the prefix, ``webbrowser.open`` treats the value as a local
    file path on macOS and silently fails — the bug we're guarding here.
    """
    assert normalize_url("github.com/foo") == "https://github.com/foo"
    assert normalize_url("clientbase.com/123") == "https://clientbase.com/123"


def test_normalize_url_preserves_existing_scheme():
    assert normalize_url("https://example.com") == "https://example.com"
    assert normalize_url("http://example.com") == "http://example.com"
    assert normalize_url("mailto:a@b.com") == "mailto:a@b.com"
    assert normalize_url("ftp://files.example.com") == "ftp://files.example.com"


def test_normalize_url_blank_returns_none():
    assert normalize_url("") is None
    assert normalize_url("  ") is None
    assert normalize_url(None) is None


def test_normalize_url_strips_surrounding_whitespace():
    assert normalize_url("  https://example.com  ") == "https://example.com"


def test_normalize_url_does_not_get_fooled_by_path_colon():
    # A colon in the path part shouldn't be mistaken for a scheme.
    assert normalize_url("example.com/page:edit") == "https://example.com/page:edit"


def test_color_for_is_deterministic_and_in_palette():
    a = color_for("api")
    b = color_for("api")
    assert a == b
    assert a in TAG_PALETTE
    assert color_for("") == "dim"
