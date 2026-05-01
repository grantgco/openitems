"""Date parsing/formatting helpers.

Per project conventions: use Dateparser for user input, Humanize for
relative display, Babel for locale-aware formatting.
"""

from __future__ import annotations

from datetime import date, datetime

import dateparser
import humanize
from babel.dates import format_date


_EMPTY_TOKENS: set[str] = {"-", "—", "none", "null"}


def parse(value: str | None) -> date | None:
    if not value:
        return None
    value = value.strip()
    if not value or value in _EMPTY_TOKENS:
        return None
    parsed = dateparser.parse(value, settings={"PREFER_DATES_FROM": "future"})
    if parsed is None:
        return None
    return parsed.date() if isinstance(parsed, datetime) else parsed


class DateParseError(ValueError):
    """Raised when a non-empty user-entered date string can't be parsed."""

    def __init__(self, field: str, raw: str) -> None:
        super().__init__(f"Couldn't parse {field}: '{raw}'")
        self.field = field
        self.raw = raw


def parse_strict(value: str | None, *, field: str) -> date | None:
    """Like ``parse``, but raises ``DateParseError`` on a non-empty bad input.

    Use this from form save handlers so the user gets feedback when their
    input is unparseable — silently dropping it (the previous behavior) is
    what made the bug invisible.
    """
    if not value:
        return None
    raw = value.strip()
    if not raw or raw in _EMPTY_TOKENS:
        return None
    parsed = dateparser.parse(raw, settings={"PREFER_DATES_FROM": "future"})
    if parsed is None:
        raise DateParseError(field, raw)
    return parsed.date() if isinstance(parsed, datetime) else parsed


def format_iso(value: date | None) -> str:
    return value.strftime("%m-%d-%Y") if value else ""


def format_short(value: date | None) -> str:
    return value.strftime("%m-%d") if value else "─"


def format_locale(value: date | None, locale: str = "en_US") -> str:
    if value is None:
        return ""
    return format_date(value, format="medium", locale=locale)


def relative(value: date | None, today: date | None = None) -> str:
    if value is None:
        return ""
    today = today or date.today()
    delta_days = (value - today).days
    if delta_days == 0:
        return "today"
    return humanize.naturaldelta(value - today, months=False) + (
        " ago" if delta_days < 0 else ""
    )
