"""Date parsing/formatting helpers.

Per project conventions: use Dateparser for user input, Humanize for
relative display, Babel for locale-aware formatting.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import dateparser
import humanize
from babel.dates import format_date


_EMPTY_TOKENS: set[str] = {"-", "—", "none", "null"}

# Recognised tokens for digest range starts. Maps to a function that
# returns the `since` date relative to today.
_SINCE_KEYWORDS: dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "monday": "monday",
    "this-week": "monday",
    "this_week": "monday",
    "thisweek": "monday",
    "week": "monday",
    "last-week": "last-week",
    "last_week": "last-week",
    "lastweek": "last-week",
    "last7": "last-7-days",
    "last-7": "last-7-days",
    "last-7-days": "last-7-days",
    "30days": "last-30-days",
    "last-30-days": "last-30-days",
}


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


def parse_since(value: str | None, *, today: date | None = None) -> date:
    """Resolve a digest "since" string to a concrete ``date``.

    Accepts:
      - ``"today"`` / ``"yesterday"``
      - ``"monday"`` / ``"this-week"`` — start of the current ISO week (Mon)
      - ``"last-week"`` — Monday of the previous week
      - ``"last-7-days"`` / ``"last7"`` — exactly 7 days ago
      - ``"last-30-days"`` / ``"30days"`` — 30 days ago
      - any string ``dateparser`` understands (``"3 days ago"``, ISO date, …)

    Defaults to the most recent Monday (start of the current week) when
    ``value`` is empty or ``None``.
    """
    today = today or date.today()
    if value is None:
        return _start_of_week(today)
    raw = value.strip().lower()
    if not raw:
        return _start_of_week(today)
    keyword = _SINCE_KEYWORDS.get(raw)
    if keyword == "today":
        return today
    if keyword == "yesterday":
        return today - timedelta(days=1)
    if keyword == "monday":
        return _start_of_week(today)
    if keyword == "last-week":
        return _start_of_week(today) - timedelta(days=7)
    if keyword == "last-7-days":
        return today - timedelta(days=7)
    if keyword == "last-30-days":
        return today - timedelta(days=30)
    parsed = dateparser.parse(
        raw,
        settings={"PREFER_DATES_FROM": "past", "RELATIVE_BASE": datetime.combine(today, datetime.min.time())},
    )
    if parsed is None:
        raise ValueError(f"Couldn't parse since={value!r}")
    return parsed.date() if isinstance(parsed, datetime) else parsed


def start_of_week(d: date) -> date:
    """Monday of the ISO week containing ``d``."""
    return d - timedelta(days=d.weekday())


# Backwards-compatible private alias for the few internal call sites that
# already imported the underscore-prefixed name.
_start_of_week = start_of_week


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
