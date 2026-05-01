from __future__ import annotations

from datetime import date

import pytest

from openitems.domain.dates import DateParseError, parse, parse_strict


def test_parse_empty_returns_none():
    assert parse(None) is None
    assert parse("") is None
    assert parse("  ") is None
    assert parse("—") is None
    assert parse("-") is None


def test_parse_iso():
    assert parse("2026-06-01") == date(2026, 6, 1)


def test_parse_natural():
    out = parse("June 1 2026")
    assert out == date(2026, 6, 1)


def test_parse_strict_distinguishes_empty_from_unparseable():
    assert parse_strict("", field="Due") is None
    assert parse_strict("  ", field="Due") is None
    with pytest.raises(DateParseError) as exc_info:
        parse_strict("sometime maybe", field="Due")
    err = exc_info.value
    assert err.field == "Due"
    assert "sometime maybe" in str(err)
