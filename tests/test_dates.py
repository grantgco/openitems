from __future__ import annotations

from datetime import date

import pytest

from openitems.domain.dates import DateParseError, parse, parse_since, parse_strict


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


def test_parse_since_today():
    today = date(2026, 5, 6)  # Wednesday
    assert parse_since("today", today=today) == today


def test_parse_since_yesterday():
    today = date(2026, 5, 6)
    assert parse_since("yesterday", today=today) == date(2026, 5, 5)


def test_parse_since_monday_returns_start_of_week():
    today = date(2026, 5, 6)  # Wed → Monday is 2026-05-04
    assert parse_since("monday", today=today) == date(2026, 5, 4)


def test_parse_since_aliases_for_this_week():
    today = date(2026, 5, 6)
    monday = date(2026, 5, 4)
    for alias in ("this-week", "this_week", "thisweek", "week"):
        assert parse_since(alias, today=today) == monday


def test_parse_since_last_week():
    today = date(2026, 5, 6)
    assert parse_since("last-week", today=today) == date(2026, 4, 27)


def test_parse_since_last_7_days():
    today = date(2026, 5, 6)
    assert parse_since("last-7-days", today=today) == date(2026, 4, 29)


def test_parse_since_iso_date():
    today = date(2026, 5, 6)
    assert parse_since("2026-04-15", today=today) == date(2026, 4, 15)


def test_parse_since_relative():
    today = date(2026, 5, 6)
    out = parse_since("3 days ago", today=today)
    assert out == date(2026, 5, 3)


def test_parse_since_default_is_this_monday():
    today = date(2026, 5, 6)
    assert parse_since(None, today=today) == date(2026, 5, 4)
    assert parse_since("", today=today) == date(2026, 5, 4)


def test_parse_since_garbage_raises():
    with pytest.raises(ValueError):
        parse_since("not a date at all", today=date(2026, 5, 6))


def test_parse_strict_distinguishes_empty_from_unparseable():
    assert parse_strict("", field="Due") is None
    assert parse_strict("  ", field="Due") is None
    with pytest.raises(DateParseError) as exc_info:
        parse_strict("sometime maybe", field="Due")
    err = exc_info.value
    assert err.field == "Due"
    assert "sometime maybe" in str(err)


def test_parse_strict_current_period_does_not_shift_to_future():
    """Without ``prefer='current_period'``, ``"Jan 1"`` would silently bump
    to next year — pushing policy effective dates past their expiration and
    breaking the eff ≤ exp invariant. Calendar-literal parsing keeps the
    natural year."""
    eff = parse_strict("Jan 1", field="Effective", prefer="current_period")
    assert eff is not None
    assert eff.month == 1 and eff.day == 1
    # Two-digit years parse to the current century, not the next one.
    parsed_short = parse_strict("1/1/26", field="Effective", prefer="current_period")
    assert parsed_short is not None
    assert parsed_short.year < 2100
