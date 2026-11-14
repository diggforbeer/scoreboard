"""What the NFL idle screens show, as plain data (#424 onward).

Pure functions from the cached feed data and the clock to a small frozen view: no drawing, no
fetching. ``idle_screens.py`` registers them; ``display/football_idle.py`` draws them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .teams import is_team, team, team_by_id

if TYPE_CHECKING:
    from .idle import CalendarEntry, StandingsRow
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


def game_holiday(start_utc: datetime | None, tz: tzinfo) -> str | None:
    """``thanksgiving`` or ``christmas`` for a game on that day in the board's own zone, else
    ``None``: the only two days a game screen gets a holiday decoration."""
    if start_utc is None:
        return None
    day = start_utc.astimezone(tz).date()
    if is_thanksgiving(day):
        return "thanksgiving"
    return "christmas" if day.month == 12 and day.day == 25 else None


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


#: Suffixes that are not a surname: ``Odell Beckham Jr.`` is BECKHAM.
_SUFFIXES = {"JR", "JR.", "SR", "SR.", "II", "III", "IV", "V"}
#: The recap's order: the game's top passer, rusher, then receiver.
RECAP_CATEGORIES = ("passingYards", "rushingYards", "receivingYards")


def surname(name: str) -> str:
    """``J.J. McCarthy`` -> ``MCCARTHY``; a trailing ``Jr.`` or ``III`` is skipped."""
    parts = [p for p in name.split() if p.upper() not in _SUFFIXES]
    return (parts[-1] if parts else name).upper()


@dataclass(frozen=True, slots=True)
class RecapLine:
    """One of the game's leaders: ``MCCARTHY 293 YD`` in his team's colour."""

    team: str
    surname: str
    yards: int
    category: str


@dataclass(frozen=True, slots=True)
class FinalView:
    """The favourite's final and what to say under the score."""

    game: FbGame
    #: ``FINAL`` or ``FINAL/OT``.
    status: str
    #: The leaders (passing, rushing, receiving), best first; empty when the feed gave none.
    recap: tuple[RecapLine, ...]
    #: The fallback line when there is no recap: ``NYG WIN BY 3`` or ``TIE GAME``.
    margin: str


def margin_line(game: FbGame) -> str:
    gap = game.home.score - game.away.score
    if gap == 0:
        return "TIE GAME"
    winner = game.home if gap > 0 else game.away
    return f"{winner.abbrev} WIN BY {abs(gap)}"


def recap_lines(game: FbGame) -> tuple[RecapLine, ...]:
    """The game's leaders with a yard count, in the recap's order, one per category. A leader
    without a readable yard count, or with a team that is not on this game, is dropped."""
    out: list[RecapLine] = []
    for category in RECAP_CATEGORIES:
        leader = next((lead for lead in game.leaders if lead.category == category), None)
        if leader is None or leader.team_id is None:
            continue
        match = re.search(r"(\d+)\s*YDS?", leader.display.upper())
        try:
            abbrev = team_by_id(leader.team_id).abbrev
        except KeyError:
            continue
        if match is None or abbrev not in (game.home.abbrev, game.away.abbrev):
            continue
        out.append(RecapLine(abbrev, surname(leader.name), int(match.group(1)), category))
    return tuple(out)


def build_final(ctx: IdleContext) -> FinalView | None:
    """The favourite's game if it is over; ``None`` otherwise. (How long it stays up is
    ``NflMode``'s hold, not this builder's.)"""
    favourite = ctx.config.favourite_team
    game = next((g for g in ctx.games if favourite and g.involves(favourite) and g.is_final), None)
    if game is None:
        return None
    overtime = game.period > 4 or "OT" in (game.short_detail or "").upper()
    return FinalView(
        game=game,
        status="FINAL/OT" if overtime else "FINAL",
        recap=recap_lines(game),
        margin=margin_line(game),
    )


#: Seeds 1 to this are in the playoffs; the cut line is drawn under it.
PLAYOFF_SEEDS = 7


@dataclass(frozen=True, slots=True)
class StandingsView:
    """The favourite's division and conference. Two pages when the conference has seeds: the
    division, then the conference (``pages`` is read by the scene's page timing)."""

    team: str
    #: ``NFC EAST``.
    division_name: str
    #: The division's teams in standings order.
    division: tuple[StandingsRow, ...]
    #: ``NFC``.
    conference: str
    #: Seeds 1 to 7, in order; empty before the feed has seeded the conference.
    seeds: tuple[StandingsRow, ...]
    #: The first team out of the playoffs (seed 8, or the best unseeded team), if any.
    first_out: StandingsRow | None
    #: ``WK 10``; empty when the scoreboard has not given the week.
    week: str

    @property
    def pages(self) -> int:
        return 2 if self.seeds else 1


def build_standings(ctx: IdleContext) -> StandingsView | None:
    """The standings pages for the favourite, or None (no favourite, no table yet, or a favourite
    the table does not list)."""
    favourite = ctx.config.favourite_team.strip().upper()
    table = ctx.idle.standings(ctx.now)
    if not favourite or table is None:
        return None
    division = table.division_of(favourite)
    conference = table.conference_of(favourite)
    if division is None or conference is None:
        return None
    seeded = conference.seeds()
    out = seeded[PLAYOFF_SEEDS] if len(seeded) > PLAYOFF_SEEDS else None
    if out is None:
        rest = conference.unseeded()
        out = rest[0] if rest else None
    board = ctx.idle.scoreboard
    week = f"WK {board.week}" if board is not None and board.week is not None else ""
    return StandingsView(
        team=favourite,
        division_name=division.name.upper(),
        division=division.rows,
        conference=conference.abbreviation.upper(),
        seeds=seeded[:PLAYOFF_SEEDS],
        first_out=out,
        week=week,
    )


#: The week grid holds eight games a page, two pages at most.
WEEK_PAGE_SIZE = 8
WEEK_MAX_GAMES = 16


@dataclass(frozen=True, slots=True)
class WeekView:
    """The week's games in the order the grid shows them."""

    games: tuple[FbGame, ...]

    @property
    def pages(self) -> int:
        return max(-(-len(self.games) // WEEK_PAGE_SIZE), 1)

    def page(self, number: int) -> tuple[FbGame, ...]:
        start = number * WEEK_PAGE_SIZE
        return self.games[start : start + WEEK_PAGE_SIZE]


def week_order(games: Sequence[FbGame]) -> tuple[FbGame, ...]:
    """Live games first (the ones to watch), then those still to come by kickoff, then the finals
    by kickoff. A game with no kickoff time goes last of its group."""
    far = datetime.max.replace(tzinfo=UTC)

    def key(game: FbGame) -> tuple[int, datetime]:
        group = 0 if game.is_live else 1 if game.is_pregame else 2
        return group, game.start_utc or far

    return tuple(sorted(games, key=key)[:WEEK_MAX_GAMES])


def build_week(ctx: IdleContext) -> WeekView | None:
    """The week's slate: the whole-week fetch when the board has one, else today's scoreboard.
    ``None`` with no games (a bye for everyone, the off-season)."""
    week = ctx.idle.week(ctx.now)
    games = week.games if week is not None and week.games else tuple(ctx.games)
    return WeekView(week_order(games)) if games else None


SCHEDULE_ROWS = 3


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    week: int
    start_utc: datetime
    opponent: str
    #: True when the favourite is the home team (``VS``), else ``AT``.
    home: bool


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """The favourite's next games, soonest first."""

    team: str
    rows: tuple[ScheduleRow, ...]


def build_schedule(ctx: IdleContext) -> ScheduleView | None:
    """The next three games from the favourite's schedule. A game with no week number (the feed's
    bye) or no kickoff time, or against a team not yet known, is passed over; fewer than three left
    shows what is left; nothing left (or no schedule yet) is ``None`` so the screen is skipped."""
    favourite = ctx.config.favourite_team.strip().upper()
    if not favourite or not _known(favourite):
        return None
    schedule = ctx.idle.schedule(team(favourite).espn_id, ctx.now)
    if schedule is None:
        return None
    rows = []
    for g in schedule.upcoming(ctx.utc):
        opponent = g.opponent(favourite)
        if g.week is None or g.start_utc is None or not _known(opponent):
            continue
        rows.append(ScheduleRow(g.week, g.start_utc, opponent, g.is_home(favourite)))
        if len(rows) == SCHEDULE_ROWS:
            break
    return ScheduleView(favourite, tuple(rows)) if rows else None
