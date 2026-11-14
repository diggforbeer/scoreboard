"""What the NFL idle screens show, as plain data (#424 onward).

Pure functions from the cached feed data and the clock to a small frozen view: no drawing, no
fetching. ``idle_screens.py`` registers them; ``display/football_idle.py`` draws them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .teams import is_team, team

if TYPE_CHECKING:
    from .idle import CalendarEntry
    from .idle_screens import IdleContext
    from .models import FbGame

#: Primetime is a network's idea; the league's is Eastern time.
EASTERN = ZoneInfo("America/New_York")
#: A game starting at or after this Eastern hour on a Thursday or Monday is a night game.
NIGHT_HOUR = 19

#: The feed's short postseason labels, in the board's wording.
ROUND_LABELS = {
    "Wild Card": "WILD CARD",
    "Div Rd": "DIVISIONAL",
    "Conf Champ": "CONF CHAMP",
    "Super Bowl": "SUPER BOWL",
}
PRESEASON, REGULAR, POSTSEASON = 1, 2, 3


def is_thanksgiving(day: date) -> bool:
    """The fourth Thursday of November."""
    return day.month == 11 and day.weekday() == 3 and 22 <= day.day <= 28


def game_tag(start_utc: datetime | None, season_type: int | None = None) -> str:
    """``THANKSGIVING``, ``CHRISTMAS``, ``THU NIGHT``, ``MON NIGHT`` or ``''``, by the game's
    Eastern date and hour. Preseason games carry none."""
    if start_utc is None or season_type == PRESEASON:
        return ""
    local = start_utc.astimezone(EASTERN)
    day = local.date()
    if is_thanksgiving(day):
        return "THANKSGIVING"
    if day.month == 12 and day.day == 25:
        return "CHRISTMAS"
    if local.hour >= NIGHT_HOUR:
        return {3: "THU NIGHT", 0: "MON NIGHT"}.get(day.weekday(), "")
    return ""


def week_label(
    season_type: int | None,
    week: int | None,
    start_utc: datetime | None,
    calendar: tuple[CalendarEntry, ...] = (),
) -> str:
    """``WEEK 11``, ``PRESEASON WK 2``, or the playoff round (``WILD CARD``, ``DIVISIONAL``,
    ``CONF CHAMP``, ``SUPER BOWL``) read from the calendar entry the game's date falls in."""
    if season_type == POSTSEASON:
        for entry in calendar:
            if (
                entry.season_type == POSTSEASON
                and start_utc is not None
                and entry.start is not None
                and entry.end is not None
                and entry.start <= start_utc < entry.end
            ):
                return ROUND_LABELS.get(entry.short_label, entry.short_label.upper())
        return "PLAYOFFS"
    if week is None:
        return ""
    return f"PRESEASON WK {week}" if season_type == PRESEASON else f"WEEK {week}"


@dataclass(frozen=True, slots=True)
class PreviewView:
    """The favourite's next game."""

    away: str
    home: str
    start_utc: datetime
    #: ``''`` or ``THU NIGHT`` / ``MON NIGHT`` / ``THANKSGIVING`` / ``CHRISTMAS``.
    tag: str
    #: ``WEEK 11``, ``WILD CARD``... may be empty.
    week: str
    #: ``5-3-1``; empty when the game is not in a scoreboard the board has.
    away_record: str = ""
    home_record: str = ""


def _known(abbrev: str) -> bool:
    return is_team(abbrev)


def _find_event(ctx: IdleContext, away: str, home: str, start: datetime) -> FbGame | None:
    """The scoreboard's own event for this game (it has the records), if the board has one."""
    pools = [ctx.games]
    week = ctx.idle.week(ctx.now)
    if week is not None:
        pools.append(week.games)
    for pool in pools:
        for game in pool:
            if (
                game.away.abbrev == away
                and game.home.abbrev == home
                and game.start_utc is not None
                and abs(game.start_utc - start) < timedelta(days=1)
            ):
                return game
    return None


def build_preview(ctx: IdleContext) -> PreviewView | None:
    """The favourite's next game, or None (no favourite, nothing scheduled, a game not yet set).

    Candidates are the favourite's not-yet-started game on the scoreboard (the only place a
    preseason or playoff game appears) and the next unplayed game of its season schedule; the
    earlier wins. A ``TBD @ TBD`` playoff game is skipped until its teams are known. Records come
    from the scoreboard event when the board has one, and are left out otherwise.
    """
    favourite = ctx.config.favourite_team
    if not favourite or not _known(favourite):
        return None
    now = ctx.utc
    found: list[tuple[datetime, str, str, int | None, int | None]] = []
    for g in ctx.games:
        playable = (
            g.involves(favourite)
            and g.is_pregame
            and g.start_utc is not None
            and g.start_utc >= now
        )
        if playable and _known(g.away.abbrev) and _known(g.home.abbrev):
            found.append((g.start_utc, g.away.abbrev, g.home.abbrev, g.season_type, g.week))
    schedule = ctx.idle.schedule(team(favourite).espn_id, ctx.now)
    upcoming = schedule.next_game(now) if schedule is not None else None
    if upcoming is not None and upcoming.start_utc is not None:
        found.append(
            (upcoming.start_utc, upcoming.away, upcoming.home, upcoming.season_type, upcoming.week)
        )
    if not found:
        return None
    # Earliest first; on a tie the scoreboard's entry (listed first) wins.
    start, away, home, season_type, week = min(found, key=lambda f: f[0])
    event = _find_event(ctx, away, home, start)
    calendar = ctx.idle.scoreboard.calendar if ctx.idle.scoreboard is not None else ()
    if event is not None:
        season_type = event.season_type if event.season_type is not None else season_type
        week = event.week if event.week is not None else week
    return PreviewView(
        away=away,
        home=home,
        start_utc=start,
        tag=game_tag(start, season_type),
        week=week_label(season_type, week, start, calendar),
        away_record=event.away.record if event is not None else "",
        home_record=event.home.record if event is not None else "",
    )


@dataclass(frozen=True, slots=True)
class ByeView:
    """The favourite's bye week and, when the schedule knows it, the game after."""

    team: str
    #: ``None`` when the board has no schedule (or no next game) yet.
    next_game: PreviewView | None = None


def build_bye(ctx: IdleContext) -> ByeView | None:
    """The bye screen: only when the scoreboard lists the favourite among the week's teams on a
    bye. Nothing for a team that plays, with no favourite, or before the scoreboard has answered."""
    favourite = ctx.config.favourite_team
    board = ctx.idle.scoreboard
    if not favourite or not _known(favourite) or board is None or not board.on_bye(favourite):
        return None
    return ByeView(favourite.strip().upper(), build_preview(ctx))
