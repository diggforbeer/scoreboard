"""Important dates (#524): birthdays, anniversaries and other days the owner counts down to.

The ``[[dates]]`` list is entered on the admin page; the ``dates`` rotation screen shows each one
inside its own window (``days_before``) and celebrates on the day. Everything here is pure: the
config loader, the admin page's validation and the renderer all use the same rules, so the text can
never be something the panel can't draw.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

log = logging.getLogger(__name__)

#: How many dates the list holds.
DATES_MAX = 10
#: The longest label. 14 of the 6x10 font is 84px, which fits beside the icon on a 128px panel.
DATE_TEXT_MAX = 14
#: What a label may contain: the capitals and digits every font has, a space and a little
#: punctuation. Lower case is turned into capitals rather than refused.
DATE_TEXT_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,'!&-?")
DATE_ICONS = ("cake", "balloon", "heart", "gift", "star")
DEFAULT_ICON = "star"
#: ``days_before``: how many days ahead the screen starts showing a date.
DAYS_BEFORE_DEFAULT = 30
DAYS_BEFORE_MIN = 1
DAYS_BEFORE_MAX = 365
#: The icons that mean a birthday: their countdown says ``TURNS 8``, the others ``8 YEARS``.
BIRTHDAY_ICONS = ("cake", "balloon")

#: What the big line says on the day itself, by icon.
DAY_OF_TEXT = {
    "cake": "BIRTHDAY!",
    "balloon": "CELEBRATE!",
    "heart": "ANNIVERSARY!",
    "gift": "TODAY!",
    "star": "TODAY!",
}


@dataclass(frozen=True, slots=True)
class ImportantDate:
    """One ``[[dates]]`` row. ``date`` carries the year it began (a birth year, a wedding year)."""

    date: date
    text: str
    icon: str = DEFAULT_ICON
    #: Every year (birthdays, anniversaries) or once, on exactly ``date``.
    repeat: bool = True
    #: Say how many years it has been (``TURNS 8`` / ``8 YEARS``); only for a repeating date.
    show_years: bool = False
    days_before: int = DAYS_BEFORE_DEFAULT


@dataclass(frozen=True, slots=True)
class DateView:
    """What the screen draws for one date that is inside its window."""

    text: str
    icon: str
    #: Whole days from today to the day; 0 is the day itself.
    days: int
    #: How many years it will be on the day, or ``None`` to say nothing.
    years: int | None = None


def clean_text(raw: object) -> str:
    """The label as the panel wants it: capitals, single spaces, trimmed."""
    return " ".join(str(raw).upper().split())


def text_problem(text: str) -> str | None:
    """Why ``text`` (already ``clean_text``-ed) can't be a label, or ``None`` if it can."""
    if not text:
        return "enter some text"
    if len(text) > DATE_TEXT_MAX:
        return f"at most {DATE_TEXT_MAX} characters"
    bad = sorted({ch for ch in text if ch not in DATE_TEXT_CHARS})
    if bad:
        return f"can't use {' '.join(bad)} (letters, digits and . , ' ! & - ? only)"
    return None


def parse_day(raw: object) -> date | None:
    """A date from a TOML date, or from ``YYYY-MM-DD`` (what the admin page's picker sends)."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None
    return None


def _repair_text(raw: object) -> str:
    """Load-time repair: capitals, bad characters dropped, cut to the limit."""
    text = clean_text(raw)
    return clean_text("".join(ch for ch in text if ch in DATE_TEXT_CHARS))[:DATE_TEXT_MAX].strip()


def _as_bool(raw: object, default: bool) -> bool:
    return raw if isinstance(raw, bool) else default


def parse_dates(raw: Any) -> list[ImportantDate]:
    """The list from ``[[dates]]``: a bad row is dropped with a warning, never fatal (a typo in a
    hand-edited file must not stop the board booting). An unknown icon becomes the star and an
    out-of-range window is clamped; a row with no usable date or text is dropped."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        log.warning("dates must be a list of [[dates]] tables, got %r; ignoring it", raw)
        return []
    out: list[ImportantDate] = []
    for index, row in enumerate(raw, start=1):
        if isinstance(row, ImportantDate):
            out.append(row)
            continue
        if not isinstance(row, Mapping):
            log.warning("Ignoring dates entry %d: not a table", index)
            continue
        day = parse_day(row.get("date"))
        if day is None:
            log.warning(
                "Ignoring dates entry %d: %r is not a date (YYYY-MM-DD)", index, row.get("date")
            )
            continue
        text = _repair_text(row.get("text", ""))
        if not text:
            log.warning("Ignoring dates entry %d: no text", index)
            continue
        icon = str(row.get("icon", DEFAULT_ICON)).strip().lower()
        if icon not in DATE_ICONS:
            log.warning(
                "dates entry %d: unknown icon %r (must be one of %s); using %s",
                index,
                row.get("icon"),
                ", ".join(DATE_ICONS),
                DEFAULT_ICON,
            )
            icon = DEFAULT_ICON
        days = row.get("days_before", DAYS_BEFORE_DEFAULT)
        if isinstance(days, bool) or not isinstance(days, (int, float)):
            days = DAYS_BEFORE_DEFAULT
        window = min(max(int(days), DAYS_BEFORE_MIN), DAYS_BEFORE_MAX)
        if window != days:
            log.warning(
                "dates entry %d: days_before %r is outside %d-%d; using %d",
                index,
                days,
                DAYS_BEFORE_MIN,
                DAYS_BEFORE_MAX,
                window,
            )
        if len(out) >= DATES_MAX:
            log.warning(
                "Ignoring dates entry %d: only the first %d dates are kept", index, DATES_MAX
            )
            continue
        out.append(
            ImportantDate(
                date=day,
                text=text,
                icon=icon,
                repeat=_as_bool(row.get("repeat"), True),
                show_years=_as_bool(row.get("show_years"), False),
                days_before=window,
            )
        )
    return out


def _in_year(day: date, year: int) -> date:
    """``day`` moved to ``year``; a Feb 29 falls on Feb 28 in a year that has no 29th."""
    try:
        return day.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def occurrence(entry: ImportantDate, today: date) -> date | None:
    """The next day (today included) the date falls on, or ``None`` for a one-off that has
    passed. A repeating date never comes before the year it began."""
    if not entry.repeat:
        return entry.date if entry.date >= today else None
    when = _in_year(entry.date, today.year)
    if when < today:
        when = _in_year(entry.date, today.year + 1)
    return max(when, entry.date)


def view_for(entry: ImportantDate, today: date) -> DateView | None:
    """The date's view if today is inside its window, else ``None``."""
    when = occurrence(entry, today)
    if when is None:
        return None
    days = (when - today).days
    if days > entry.days_before:
        return None
    years = when.year - entry.date.year if entry.repeat and entry.show_years else 0
    return DateView(entry.text, entry.icon, days, years if years > 0 else None)


def upcoming(entries: Iterable[ImportantDate], today: date) -> list[DateView]:
    """Every date inside its window, today's first, then the nearest."""
    views = [view for entry in entries if (view := view_for(entry, today)) is not None]
    return sorted(views, key=lambda v: (v.days, v.text))


def countdown_text(view: DateView) -> str:
    """The big line: ``12 DAYS``, ``TOMORROW``, or the day-of greeting."""
    if view.days <= 0:
        return DAY_OF_TEXT.get(view.icon, "TODAY!")
    return "TOMORROW" if view.days == 1 else f"{view.days} DAYS"


def years_text(view: DateView) -> str | None:
    """The small line: ``TURNS 8`` for a birthday, ``8 YEARS`` for the rest; ``None`` for none."""
    if view.years is None:
        return None
    if view.icon in BIRTHDAY_ICONS:
        return f"TURNS {view.years}"
    return f"{view.years} YEAR{'' if view.years == 1 else 'S'}"


def pick(views: Sequence[DateView], offset: float, seconds: float) -> DateView:
    """Which of ``views`` is up ``offset`` seconds into a slot of ``seconds``: the dwell is shared
    evenly, nearest first."""
    if not views:
        raise ValueError("no dates to pick from")
    index = int(offset * len(views) / seconds) if seconds > 0 else 0
    return views[min(max(index, 0), len(views) - 1)]
