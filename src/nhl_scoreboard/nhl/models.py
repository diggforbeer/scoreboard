"""Typed view over the parts of the NHL API this project actually renders."""

from __future__ import annotations

import itertools
import logging
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# gameState values observed from api-web.nhle.com/v1/score/{date}
LIVE_STATES = frozenset({"LIVE", "CRIT"})
FINAL_STATES = frozenset({"FINAL", "OFF"})
PREGAME_STATES = frozenset({"FUT", "PRE"})

_ORDINALS = {1: "1ST", 2: "2ND", 3: "3RD"}

# The API has no wall-clock end time, so a finished game's end is estimated
# from its start. Typical NHL game lengths, a little generous so a hold is
# more likely to run slightly long than to be cut short.
REGULATION_LENGTH = timedelta(hours=2, minutes=30)
OVERTIME_EXTRA = timedelta(minutes=10)
SHOOTOUT_EXTRA = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class TeamSide:
    abbrev: str
    name: str
    score: int
    sog: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> TeamSide:
        return cls(
            abbrev=raw.get("abbrev") or "???",
            name=_default_str(raw.get("name")),
            score=int(raw.get("score") or 0),
            sog=int(raw.get("sog") or 0),
        )


@dataclass(frozen=True, slots=True)
class Situation:
    """Special-teams state from ``gamecenter/{id}/landing``.

    Present in that payload only while something is on: a power play, an
    empty net, a penalty shot. ``descriptions`` carry the NHL's codes per
    side -- ``PP``, ``EN``, ``PS`` -- and ``strength`` is skaters on the ice.
    """

    away_strength: int
    home_strength: int
    away_descriptions: tuple[str, ...]
    home_descriptions: tuple[str, ...]
    time_remaining: str
    seconds_remaining: int

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> Situation | None:
        if not raw:
            return None
        away = raw.get("awayTeam") or {}
        home = raw.get("homeTeam") or {}
        return cls(
            away_strength=int(away.get("strength") or 0),
            home_strength=int(home.get("strength") or 0),
            away_descriptions=_codes(away.get("situationDescriptions")),
            home_descriptions=_codes(home.get("situationDescriptions")),
            time_remaining=str(raw.get("timeRemaining") or ""),
            seconds_remaining=int(raw.get("secondsRemaining") or 0),
        )

    def power_play_side(self) -> str | None:
        """``"away"`` or ``"home"`` for the team with the advantage, else None."""
        if "PP" in self.away_descriptions:
            return "away"
        if "PP" in self.home_descriptions:
            return "home"
        return None

    def empty_net_side(self) -> str | None:
        if "EN" in self.away_descriptions:
            return "away"
        if "EN" in self.home_descriptions:
            return "home"
        return None

    def indicator_side(self) -> str | None:
        return self.power_play_side() or self.empty_net_side()

    def label(self) -> str:
        """Short indicator text: ``PP 1:23``, ``5v3 0:41``, ``EN``."""
        side = self.power_play_side()
        if side:
            skaters = (self.away_strength, self.home_strength)
            mine, theirs = skaters if side == "away" else skaters[::-1]
            kind = "PP" if mine - theirs < 2 else f"{mine}v{theirs}"
            return f"{kind} {self.time_remaining}".strip()
        if self.empty_net_side():
            return "EN"
        return ""


@dataclass(frozen=True, slots=True)
class AssistDetail:
    """One assister on a ``GoalEvent`` -- 0, 1 or 2 of these per goal."""

    name: str
    assists_to_date: int
    #: Free in the same landing payload as everything else here (#124) --
    #: unlike the scorer's own entry, an assist's raw object carries this
    #: directly, confirmed live. Unlike scorer_sweater_number/scorer_points
    #: below, no second call needed for this one.
    sweater_number: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> AssistDetail:
        return cls(
            name=_default_str(raw.get("name")),
            assists_to_date=int(raw.get("assistsToDate") or 0),
            sweater_number=int(raw.get("sweaterNumber") or 0),
        )


@dataclass(frozen=True, slots=True)
class GoalEvent:
    """One entry from ``gamecenter/{id}/landing``'s ``summary.scoring`` (#122).

    Confirmed free in that payload against two real live games: scorer name
    (already compact "F. Lastname"), the scorer's season goal total
    (``goalsToDate``, confirmed genuinely cumulative-season, not per-game),
    each assister's name/season assist total/``sweaterNumber``, and
    ``strength`` ("ev"/"pp"/"sh"). NOT free from this endpoint: the
    scorer's own jersey number, and total points (goals + assists) for
    either player -- this endpoint gives only one half of that sum per
    person. ``scorer_sweater_number``/``scorer_points`` close that gap
    (#124) but need a second call this dataclass alone can't make; both
    stay ``None`` until ``ScoreboardApp`` fills them in via
    ``dataclasses.replace`` once the scoring team's roster+stats are
    fetched, and permanently ``None`` if that fetch ever fails -- the
    screen still shows without them, same graceful-degradation precedent
    as the rest of this app.
    """

    team_abbrev: str
    scorer_name: str
    scorer_goals_to_date: int
    #: Free in this payload (unlike an assist's own id, not needed since
    #: sweater_number is already free there) -- the key for looking up
    #: scorer_sweater_number/scorer_points in the team roster (#124).
    scorer_player_id: int
    assists: tuple[AssistDetail, ...]
    strength: str
    scorer_sweater_number: int | None = None
    scorer_points: int | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> GoalEvent:
        return cls(
            team_abbrev=_default_str(raw.get("teamAbbrev")).upper(),
            scorer_name=_default_str(raw.get("name")),
            scorer_goals_to_date=int(raw.get("goalsToDate") or 0),
            scorer_player_id=int(raw.get("playerId") or 0),
            assists=tuple(AssistDetail.from_api(a) for a in (raw.get("assists") or [])),
            strength=str(raw.get("strength") or "ev").lower(),
        )


def goal_events_from_landing(raw: dict[str, Any] | None) -> tuple[GoalEvent, ...]:
    """Every goal in ``summary.scoring``, across all periods, in scoring order.

    One malformed entry is skipped rather than losing the rest -- same
    precedent as ``_parse_items`` in ``nhl/api.py`` for scores/standings.
    """
    if not raw:
        return ()
    periods = (raw.get("summary") or {}).get("scoring") or []
    events = []
    for period in periods:
        for goal in period.get("goals") or []:
            try:
                events.append(GoalEvent.from_api(goal))
            except (AttributeError, KeyError, TypeError, ValueError):
                continue
    return tuple(events)


@dataclass(frozen=True, slots=True)
class PlayerSeasonDetail:
    """Jersey number + season points for one player (#124).

    Exists only because closing GoalEvent's gap needs combining two
    endpoints, confirmed live, neither of which has both alone:
    ``roster/{team}/current`` has ``sweaterNumber`` (keyed by ``id``) but
    not points; ``club-stats/{team}/now`` has ``points`` (keyed by
    ``playerId``) but not sweaterNumber.
    """

    sweater_number: int
    points: int


def player_details_from_api(
    roster: dict[str, Any], club_stats: dict[str, Any]
) -> dict[int, PlayerSeasonDetail]:
    """Combine a team's roster and club-stats payloads into one id -> detail map.

    Only players present in both are included -- a player needs a roster
    entry (for the jersey number) and a stats entry (for points) to be any
    use to the goal-detail screen; one without the other can't be shown
    anyway. Goalies included on both sides even though the goal-detail
    screen only ever looks up scorers/assisters, who are practically never
    goalies -- but rare on-ice-credit oddities exist, and this is a
    zero-cost `dict` builder, not a live call, so there's no reason to
    special-case them out.
    """
    numbers: dict[int, int] = {}
    for group in ("forwards", "defensemen", "goalies"):
        for player in roster.get(group) or []:
            try:
                numbers[int(player["id"])] = int(player["sweaterNumber"])
            except (KeyError, TypeError, ValueError):
                continue
    points: dict[int, int] = {}
    for group in ("skaters", "goalies"):
        for player in club_stats.get(group) or []:
            try:
                points[int(player["playerId"])] = int(player.get("points") or 0)
            except (KeyError, TypeError, ValueError):
                continue
    return {
        player_id: PlayerSeasonDetail(sweater_number=number, points=points[player_id])
        for player_id, number in numbers.items()
        if player_id in points
    }


@dataclass(frozen=True, slots=True)
class Star:
    """One entry from ``gamecenter/{id}/landing``'s top-level ``threeStars`` (#156).

    Present once a game is final (verified against a real completed game's
    landing payload). ``goals``/``assists``/``points`` are this game's own
    totals, *not* season-to-date -- the opposite convention from
    ``GoalEvent``'s ``goalsToDate``/``assistsToDate``, hence the plain names.
    A goalie's entry carries goalie stats instead of these three, so they
    read as zero for one.
    """

    star: int
    player_id: int
    team_abbrev: str
    name: str
    sweater_no: int
    position: str
    goals: int
    assists: int
    points: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Star:
        return cls(
            star=int(raw["star"]),
            player_id=int(raw.get("playerId") or 0),
            team_abbrev=_default_str(raw.get("teamAbbrev")).upper(),
            name=_default_str(raw.get("name")),
            sweater_no=int(raw.get("sweaterNo") or 0),
            position=str(raw.get("position") or "").upper(),
            goals=int(raw.get("goals") or 0),
            assists=int(raw.get("assists") or 0),
            points=int(raw.get("points") or 0),
        )


def three_stars_from_landing(raw: dict[str, Any] | None) -> tuple[Star, ...]:
    """``threeStars``, ordered by rank; empty until the NHL has named them.

    One malformed entry is skipped rather than losing the rest -- same
    precedent as ``goal_events_from_landing``.
    """
    if not raw:
        return ()
    stars = []
    for entry in raw.get("threeStars") or []:
        try:
            stars.append(Star.from_api(entry))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return tuple(sorted(stars, key=lambda s: s.star))


@dataclass(frozen=True, slots=True)
class ShootoutAttempt:
    """One shot from ``summary.shootout.events`` (#259).

    Only a goal counts as a score; any other ``result`` (``save`` seen live,
    ``miss``/``post``/... presumed) is drawn as a miss.
    """

    sequence: int
    team_abbrev: str
    scored: bool
    game_winner: bool = False


#: Rounds each team shoots before sudden death.
SHOOTOUT_ROUNDS = 3


@dataclass(frozen=True, slots=True)
class ShootoutState:
    """``Shootout.state()``'s answer.

    ``kind``: ``open`` (nothing on the line yet), ``must_score`` (``team``
    is eliminated if its next shot misses), ``sudden_death``, ``decided``
    (``team`` won) or ``unknown`` (data too incomplete to say).
    """

    kind: str
    team: str | None = None


@dataclass(frozen=True, slots=True)
class Shootout:
    """The shootout so far, from ``gamecenter/{id}/landing`` (#259).

    ``attempts`` are in shot order; which team shoots first varies, so a
    row is found by ``team_abbrev``, never by position. ``away_goals``/
    ``home_goals`` are the API's running ``liveScore``, which can lead the
    matching event by a poll -- callers show it as given.
    """

    attempts: tuple[ShootoutAttempt, ...]
    away_goals: int = 0
    home_goals: int = 0

    def results_for(self, abbrev: str) -> tuple[bool, ...]:
        """``abbrev``'s attempts in order: True for a goal."""
        return tuple(a.scored for a in self.attempts if a.team_abbrev == abbrev)

    @property
    def winner_decided(self) -> bool:
        return any(a.game_winner for a in self.attempts)

    def state(self, away: str, home: str) -> ShootoutState:
        """Where the shootout stands, from the attempts alone (#259).

        Rules: three rounds each, ended early once one side can no longer
        catch up; if still level, sudden death -- a round each, decided only
        when both have shot. A team ``must_score`` when missing its next shot
        would let the other side clinch. Anything that doesn't look like a
        complete, in-order feed (unknown teams, gaps in ``sequence``, teams
        not alternating, event goals disagreeing with ``liveScore`` because
        one lags the other) is ``unknown``: callers show nothing special
        rather than claim a team is on the brink on shaky data.
        """
        kind = ShootoutState
        attempts = self.attempts
        if not attempts:
            return kind("open")
        teams = [a.team_abbrev for a in attempts]
        if set(teams) - {away, home} or any(x == y for x, y in itertools.pairwise(teams)):
            return kind("unknown")
        sequences = [a.sequence for a in attempts]
        if any(y - x != 1 for x, y in itertools.pairwise(sequences)):
            return kind("unknown")
        results = {t: self.results_for(t) for t in (away, home)}
        goals = {t: sum(r) for t, r in results.items()}
        if (goals[away], goals[home]) != (self.away_goals, self.home_goals):
            return kind("unknown")

        shots = {t: len(r) for t, r in results.items()}
        completed = min(shots.values())
        if completed >= SHOOTOUT_ROUNDS:
            # Level after the first three: every later round is a sudden-death
            # round, so compare only rounds both teams have finished.
            level = {t: sum(r[:completed]) for t, r in results.items()}
            if level[away] != level[home]:
                if shots[away] != shots[home]:
                    return kind("unknown")  # kept shooting after it was decided
                return kind("decided", away if level[away] > level[home] else home)
            return kind("sudden_death")

        remaining = {t: SHOOTOUT_ROUNDS - shots[t] for t in (away, home)}
        if remaining[away] < 0 or remaining[home] < 0:
            return kind("unknown")
        for t, other in ((away, home), (home, away)):
            if goals[t] > goals[other] + remaining[other]:
                return kind("decided", t)
        # Whoever has taken fewer shots goes next; level, the first shooter.
        if shots[away] == shots[home]:
            nxt = teams[0]
        else:
            nxt = away if shots[away] < shots[home] else home
        other = home if nxt == away else away
        if goals[other] > goals[nxt] + remaining[nxt] - 1:
            return kind("must_score", nxt)
        return kind("open")


_KNOWN_SHOOTOUT_RESULTS = frozenset({"goal", "save"})


def shootout_from_landing(raw: dict[str, Any] | None) -> Shootout | None:
    """``summary.shootout``, or None until the shootout has begun.

    One malformed event is skipped rather than losing the rest. A
    ``result`` other than ``goal`` is a miss; unfamiliar ones are logged
    once per call so new values show up in the journal.
    """
    shootout = ((raw or {}).get("summary") or {}).get("shootout")
    if not shootout:
        return None
    attempts = []
    for event in shootout.get("events") or []:
        try:
            result = str(event.get("result") or "").lower()
            if result not in _KNOWN_SHOOTOUT_RESULTS:
                log.warning("Unrecognised shootout result %r; drawing it as a miss", result)
            attempts.append(
                ShootoutAttempt(
                    sequence=int(event["sequence"]),
                    team_abbrev=_default_str(event.get("teamAbbrev")).upper(),
                    scored=result == "goal",
                    game_winner=bool(event.get("gameWinner")),
                )
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    live = shootout.get("liveScore") or {}
    return Shootout(
        attempts=tuple(sorted(attempts, key=lambda a: a.sequence)),
        away_goals=int(live.get("away") or 0),
        home_goals=int(live.get("home") or 0),
    )


@dataclass(frozen=True, slots=True)
class Game:
    id: int
    state: str
    game_type: int
    start_utc: datetime
    away: TeamSide
    home: TeamSide
    period: int
    period_type: str
    max_regulation_periods: int
    clock_time: str
    clock_running: bool
    in_intermission: bool
    #: Filled in separately from the landing endpoint; None at even strength.
    situation: Situation | None = None
    #: Likewise from landing, only once a shootout has begun (#259).
    shootout: Shootout | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Game:
        clock = raw.get("clock") or {}
        descriptor = raw.get("periodDescriptor") or {}
        state = str(raw.get("gameState") or "FUT").upper()
        clock_time = str(clock.get("timeRemaining") or "00:00")
        clock_running = bool(clock.get("running"))
        period = int(raw.get("period") or descriptor.get("number") or 0)
        max_regulation = int(descriptor.get("maxRegulationPeriods") or 3)
        away = TeamSide.from_api(raw.get("awayTeam") or {})
        home = TeamSide.from_api(raw.get("homeTeam") or {})
        # After the last regulation period (or any OT) a score that isn't tied
        # means the game is over, not heading into another period; the state
        # flips to FINAL a poll or two later, and until then the board
        # flashed INT3. A tie is a real intermission (OT or shootout follows).
        game_decided = period >= max_regulation and away.score != home.score
        return cls(
            id=int(raw["id"]),
            state=state,
            game_type=int(raw.get("gameType") or 2),
            start_utc=_parse_utc(raw.get("startTimeUTC")),
            away=away,
            home=home,
            period=period,
            period_type=str(descriptor.get("periodType") or "REG").upper(),
            max_regulation_periods=max_regulation,
            clock_time=clock_time,
            clock_running=clock_running,
            # The API's own inIntermission flag lags briefly right at a period's
            # end -- confirmed against a real live game sitting at
            # timeRemaining "00:00"/running false with inIntermission still
            # false, on both score/now and gamecenter/landing, for well over
            # one poll cycle. A *live* period clock can only read 00:00 once
            # play has stopped (periods start at 20:00/5:00, never count down
            # to it mid-play), so treat that combination as intermission
            # ourselves rather than trust the flag alone -- this also fixes
            # the situation-poll skip and poll_interval() slowdown that key
            # off the same field, not just the displayed label. Gated on
            # state being live: a FINAL/OFF game's clock sits at 00:00/not
            # running too, and is not an intermission.
            in_intermission=not game_decided
            and (
                bool(clock.get("inIntermission"))
                or (state in LIVE_STATES and clock_time == "00:00" and not clock_running)
            ),
        )

    # -- state helpers ---------------------------------------------------

    @property
    def is_live(self) -> bool:
        return self.state in LIVE_STATES

    @property
    def is_final(self) -> bool:
        return self.state in FINAL_STATES

    @property
    def is_pregame(self) -> bool:
        return self.state in PREGAME_STATES

    @property
    def in_shootout(self) -> bool:
        return self.period_type == "SO"

    @property
    def shows_shootout(self) -> bool:
        """Draw the shootout grid while it is live; a finished game shows its final score."""
        return self.in_shootout and self.is_live

    @property
    def special_teams(self) -> bool:
        return self.situation is not None and self.situation.indicator_side() is not None

    def involves(self, abbrev: str) -> bool:
        target = abbrev.strip().upper()
        return bool(target) and target in (self.away.abbrev, self.home.abbrev)

    # -- display helpers -------------------------------------------------

    def period_label(self) -> str:
        """Short label for the period, e.g. ``2ND``, ``OT``, ``SO``."""
        if self.period_type == "SO":
            return "SO"
        if self.period_type == "OT" or self.period > self.max_regulation_periods:
            extra = self.period - self.max_regulation_periods
            return "OT" if extra <= 1 else f"{extra}OT"
        return _ORDINALS.get(self.period, f"{self.period}TH")

    def status_label(self, tz: ZoneInfo) -> str:
        """One short line describing where the game is, sized to fit 128 pixels."""
        if self.is_pregame:
            return self.start_local(tz).strftime("%-I:%M%p").replace("AM", "A").replace("PM", "P")
        if self.is_final:
            if self.period_type == "SO":
                return "FINAL/SO"
            if self.period_type == "OT":
                return f"F/{self.period_label()}"
            return "FINAL"
        if self.in_intermission:
            return f"INT{self.period}"
        return f"{self.period_label()} {self.clock_time}"

    def start_local(self, tz: ZoneInfo) -> datetime:
        return self.start_utc.astimezone(tz)

    def start_label(self, tz: ZoneInfo) -> str:
        """``7:00P`` -- the local start time, sized for the panel."""
        return self.start_local(tz).strftime("%-I:%M%p").replace("AM", "A").replace("PM", "P")

    def day_label(self, now: datetime, tz: ZoneInfo) -> str:
        """``TONIGHT``, ``TOMORROW`` or ``SAT OCT 4``, relative to ``now``."""
        start = self.start_local(tz)
        today = now.astimezone(tz).date()
        days = (start.date() - today).days
        if days == 0:
            return "TONIGHT" if start.hour >= 17 else "TODAY"
        if days == 1:
            return "TOMORROW"
        return start.strftime("%a %b %-d").upper()

    def countdown_label(self, now: datetime) -> str:
        """``IN 1H 23M`` beyond an hour, ``IN 23:45`` (mm:ss) inside it."""
        remaining = max(0, int((self.start_utc - now).total_seconds()))
        hours, rest = divmod(remaining, 3600)
        minutes, seconds = divmod(rest, 60)
        if hours:
            return f"IN {hours}H {minutes:02d}M"
        return f"IN {minutes:02d}:{seconds:02d}"

    def seconds_until_start(self, now: datetime) -> float:
        return (self.start_utc - now).total_seconds()

    def estimated_end(self) -> datetime:
        """When a finished game probably ended; see REGULATION_LENGTH."""
        end = self.start_utc + REGULATION_LENGTH
        if self.period_type == "SO":
            end += SHOOTOUT_EXTRA
        elif self.period_type == "OT" or self.period > self.max_regulation_periods:
            end += OVERTIME_EXTRA
        return end

    def sort_key(self) -> tuple[int, datetime]:
        """Live games first, then upcoming, then finals -- each by start time."""
        rank = 0 if self.is_live else (1 if self.is_pregame else 2)
        return (rank, self.start_utc)


@dataclass(frozen=True, slots=True)
class StandingsRow:
    """One team's line from ``standings/{date}``.

    ``clinch_indicator`` values (``p``, ``y``, ``z``, ``x``, ``e`` seen so
    far) are kept but not interpreted here -- confirmed from only one real,
    end-of-season response and not documented anywhere, so nothing renders
    off them yet (#40).
    """

    abbrev: str
    conference: str
    division: str
    division_sequence: int
    wildcard_sequence: int
    conference_sequence: int
    clinch_indicator: str
    points: int
    games_played: int
    wins: int
    losses: int
    ot_losses: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> StandingsRow:
        return cls(
            abbrev=_default_str(raw.get("teamAbbrev")),
            conference=str(raw.get("conferenceAbbrev") or "").upper(),
            division=str(raw.get("divisionAbbrev") or "").upper(),
            division_sequence=int(raw.get("divisionSequence") or 0),
            wildcard_sequence=int(raw.get("wildcardSequence") or 0),
            conference_sequence=int(raw.get("conferenceSequence") or 0),
            clinch_indicator=str(raw.get("clinchIndicator") or ""),
            points=int(raw.get("points") or 0),
            games_played=int(raw.get("gamesPlayed") or 0),
            wins=int(raw.get("wins") or 0),
            losses=int(raw.get("losses") or 0),
            ot_losses=int(raw.get("otLosses") or 0),
        )

    @property
    def in_playoff_position(self) -> bool:
        """Top 3 per division, or top 2 wildcards -- the NHL's actual format."""
        return (1 <= self.division_sequence <= 3) or (1 <= self.wildcard_sequence <= 2)

    def record_label(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ot_losses}"


@dataclass(frozen=True, slots=True)
class SeasonSeriesRecord:
    """``seasonSeriesWins`` from ``gamecenter/{id}/right-rail`` (#157).

    Verified against real responses: the tally is oriented to *the
    requested game's own* away/home sides (the same NSH-CGY series read
    ``0-3`` from a game NSH hosted and ``3-0`` from one it played away), and
    it is the season-to-date total of completed regular-season meetings,
    not a running count up to that game -- every meeting's right-rail
    reported the same ``2-2`` for a finished four-game series. OT/SO wins
    count as wins. The object carries no team abbreviations of its own, so
    callers pair it with the ``Game`` it was fetched for.
    """

    away_wins: int
    home_wins: int
    #: The completed meetings behind the tally, oldest first (#168).
    meetings: tuple[SeriesMeeting, ...] = ()

    @classmethod
    def from_api(cls, raw: Any) -> SeasonSeriesRecord | None:
        """None for a missing or malformed ``seasonSeriesWins``, never raises."""
        if not isinstance(raw, dict):
            return None
        away, home = raw.get("awayTeamWins"), raw.get("homeTeamWins")
        # bool is an int subclass; a True/False here is malformed, not 1/0.
        if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (away, home)):
            return None
        return cls(away_wins=away, home_wins=home)


#: Game states a finished meeting can be in; ``FUT``/``LIVE`` ones carry no result.
_FINISHED_STATES = frozenset({"FINAL", "OFF"})


def _count(value: Any) -> int | None:
    """A non-negative int, or None -- bool is an int subclass, and malformed here."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


@dataclass(frozen=True, slots=True)
class MeetingResult:
    """One past meeting from one team's side: ``W 4-1``, ``L 2-3 OT`` (#168)."""

    game_date: date
    won: bool
    score_for: int
    score_against: int
    #: ``""`` for regulation, else the API's own ``lastPeriodType`` (``OT``,
    #: and presumably ``SO`` -- not yet seen live).
    decided_in: str

    def score_label(self) -> str:
        return f"{self.score_for}-{self.score_against}"


@dataclass(frozen=True, slots=True)
class SeriesMeeting:
    """A completed regular-season meeting from right-rail's ``seasonSeries[]`` (#168).

    Verified against real 2025-26 responses: a finished entry carries
    ``awayTeam.score``/``homeTeam.score`` and ``gameOutcome.lastPeriodType``.
    A future entry has no scores but still reads ``lastPeriodType: REG``, so
    only the game state and real scores mark one as played.
    """

    game_id: int
    game_date: date
    away_abbrev: str
    home_abbrev: str
    away_score: int
    home_score: int
    last_period_type: str

    @classmethod
    def from_api(cls, raw: Any) -> SeriesMeeting | None:
        """None for anything but a finished regular-season game; never raises."""
        if not isinstance(raw, dict):
            return None
        if raw.get("gameType") != 2 or raw.get("gameState") not in _FINISHED_STATES:
            return None
        away, home = raw.get("awayTeam"), raw.get("homeTeam")
        if not isinstance(away, dict) or not isinstance(home, dict):
            return None
        away_score, home_score = _count(away.get("score")), _count(home.get("score"))
        away_abbrev, home_abbrev = away.get("abbrev"), home.get("abbrev")
        if away_score is None or home_score is None or away_score == home_score:
            return None
        if not isinstance(away_abbrev, str) or not isinstance(home_abbrev, str):
            return None
        try:
            game_date = date.fromisoformat(str(raw.get("gameDate")))
        except ValueError:
            return None
        outcome = raw.get("gameOutcome")
        period = outcome.get("lastPeriodType") if isinstance(outcome, dict) else None
        return cls(
            game_id=int(raw.get("id") or 0),
            game_date=game_date,
            away_abbrev=away_abbrev.upper(),
            home_abbrev=home_abbrev.upper(),
            away_score=away_score,
            home_score=home_score,
            last_period_type=period if isinstance(period, str) and period else "REG",
        )

    def result_for(self, team: str) -> MeetingResult | None:
        """This meeting from ``team``'s side, or None if they didn't play in it."""
        team = team.strip().upper()
        if team == self.away_abbrev:
            score_for, score_against = self.away_score, self.home_score
        elif team == self.home_abbrev:
            score_for, score_against = self.home_score, self.away_score
        else:
            return None
        return MeetingResult(
            game_date=self.game_date,
            won=score_for > score_against,
            score_for=score_for,
            score_against=score_against,
            decided_in="" if self.last_period_type == "REG" else self.last_period_type,
        )


def series_meetings_from_api(raw: Any) -> tuple[SeriesMeeting, ...]:
    """The finished meetings in ``seasonSeries[]``, oldest first; bad entries skipped."""
    if not isinstance(raw, list):
        return ()
    meetings = [m for entry in raw if (m := SeriesMeeting.from_api(entry)) is not None]
    return tuple(sorted(meetings, key=lambda m: (m.game_date, m.game_id)))


@dataclass(frozen=True, slots=True)
class SkaterLine:
    """One skater's season line from ``club-stats/{TEAM}/now`` (#201)."""

    player_id: int
    name: str
    goals: int
    assists: int
    points: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> SkaterLine:
        return cls(
            player_id=int(raw.get("playerId") or 0),
            name=_initial_surname(raw),
            goals=int(raw.get("goals") or 0),
            assists=int(raw.get("assists") or 0),
            points=int(raw.get("points") or 0),
        )


@dataclass(frozen=True, slots=True)
class GoalieLine:
    """One goalie's season line from ``club-stats/{TEAM}/now`` (#201)."""

    player_id: int
    name: str
    games_played: int
    wins: int
    losses: int
    ot_losses: int
    save_pct: float

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> GoalieLine:
        return cls(
            player_id=int(raw.get("playerId") or 0),
            name=_initial_surname(raw),
            games_played=int(raw.get("gamesPlayed") or 0),
            wins=int(raw.get("wins") or 0),
            losses=int(raw.get("losses") or 0),
            ot_losses=int(raw.get("overtimeLosses") or 0),
            save_pct=float(raw.get("savePercentage") or 0.0),
        )

    def record_label(self) -> str:
        return f"{self.wins}-{self.losses}-{self.ot_losses}"

    def save_pct_label(self) -> str:
        """``.915``; ``1.000`` for a perfect one."""
        return f"{self.save_pct:.3f}".removeprefix("0")


@dataclass(frozen=True, slots=True)
class ClubStats:
    """The favourite's whole roster's season stats. Both empty before the season starts.

    Verified live (#201): unlike ``standings/now``, ``club-stats/{TEAM}/now``
    does *not* keep serving last season through the off-season -- it
    resolves to the new season with empty ``skaters``/``goalies``.
    """

    skaters: tuple[SkaterLine, ...]
    goalies: tuple[GoalieLine, ...]

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> ClubStats:
        return cls(
            skaters=tuple(_parse_lines(raw.get("skaters"), SkaterLine.from_api)),
            goalies=tuple(_parse_lines(raw.get("goalies"), GoalieLine.from_api)),
        )


@dataclass(frozen=True, slots=True)
class TeamLeaders:
    """What the ``leaders`` rotation screen draws: any part may be absent."""

    goals: SkaterLine | None
    points: SkaterLine | None
    goalies: tuple[GoalieLine, ...]


def team_leaders(stats: ClubStats, rng: random.Random | None = None) -> TeamLeaders | None:
    """Pick the goals leader, points leader and top two goalies by games played.

    Ties are broken at random (#201: early on everyone is at zero, and the
    screen should still show someone rather than hide). Callers pick once per
    fetch and cache the result, so the choice doesn't flicker frame to frame.
    None when there is nothing at all to show.
    """
    rng = rng or random.Random()
    skaters = list(stats.skaters)
    goalies = list(stats.goalies)
    rng.shuffle(skaters)
    rng.shuffle(goalies)
    goals = max(skaters, key=lambda s: s.goals, default=None)
    points = max(skaters, key=lambda s: s.points, default=None)
    top_goalies = tuple(sorted(goalies, key=lambda g: g.games_played, reverse=True)[:2])
    if goals is None and not top_goalies:
        return None
    return TeamLeaders(goals=goals, points=points, goalies=top_goalies)


def _parse_lines(raw: Any, parse: Any) -> list[Any]:
    lines = []
    for entry in raw if isinstance(raw, list) else []:
        try:
            lines.append(parse(entry))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return lines


def _initial_surname(raw: dict[str, Any]) -> str:
    """``F. Lastname`` from the split ``firstName``/``lastName`` objects."""
    first = _default_str(raw.get("firstName"))
    last = _default_str(raw.get("lastName"))
    return f"{first[:1]}. {last}" if first and last else last or first


def conference_standings(rows: list[StandingsRow], conference: str) -> list[StandingsRow]:
    """``rows`` for one conference, ranked by overall conference position."""
    matches = [r for r in rows if r.conference == conference.strip().upper()]
    return sorted(matches, key=lambda r: r.conference_sequence)


def division_standings(rows: list[StandingsRow], division: str) -> list[StandingsRow]:
    """``rows`` for one division, ranked by ``divisionSequence``."""
    matches = [r for r in rows if division and r.division == division.strip().upper()]
    return sorted(matches, key=lambda r: r.division_sequence)


def wildcard_standings(rows: list[StandingsRow], conference: str) -> list[StandingsRow]:
    """The wild-card race (#298): ``conference``'s teams outside the top 3 of a
    division, ranked by ``wildcardSequence``. The first ``WILDCARD_SPOTS`` get in."""
    matches = [
        r
        for r in rows
        if r.conference == conference.strip().upper() and r.wildcard_sequence >= 1
    ]
    return sorted(matches, key=lambda r: r.wildcard_sequence)


#: Wild-card places per conference.
WILDCARD_SPOTS = 2
#: Automatic places per division.
DIVISION_SPOTS = 3


def playoff_cut(rows: list[StandingsRow]) -> int | None:
    """How many leading rows of a ranked ``rows`` are in a playoff place (#298).

    The line is drawn after that many. None when there is no line to draw: all
    in, all out, or the in-rows aren't a clean prefix (a table not ranked the
    way this expects), in which case a line would be misleading.
    """
    cut = next((i for i, r in enumerate(rows) if not r.in_playoff_position), len(rows))
    if cut == 0 or cut == len(rows):
        return None
    if any(r.in_playoff_position for r in rows[cut:]):
        return None
    return cut


def standings_window(
    rows: list[StandingsRow], abbrev: str, above: int = 2, below: int = 2
) -> list[StandingsRow]:
    """``rows`` (already ranked) trimmed to ``abbrev`` plus nearby teams.

    Clamped at either end of the conference -- a favourite sitting 1st or
    last still gets a full-size window, taking the slack from the other
    side, rather than a short list.
    """
    target = abbrev.strip().upper()
    index = next((i for i, r in enumerate(rows) if r.abbrev == target), None)
    if index is None:
        return []
    size = above + below + 1
    start = max(0, index - above)
    end = min(len(rows), start + size)
    start = max(0, end - size)
    return rows[start:end]


def _codes(value: Any) -> tuple[str, ...]:
    return tuple(str(code).upper() for code in (value or ()))


def _default_str(value: Any) -> str:
    """The NHL API wraps localised strings as ``{"default": "Devils"}``."""
    if isinstance(value, dict):
        return str(value.get("default") or "")
    return str(value or "")


def _parse_utc(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)
