"""Models for the ESPN NFL scoreboard (#350).

ESPN's API is free, keyless and **undocumented**, so everything here parses
defensively (see ``football_api.md``): every field is optional, a missing or
oddly typed one becomes a default, unknown values are kept as the feed gave
them, and the only thing that is refused is an event with no usable game in it
(no id, or not two teams), which ``from_api`` reports as a ``ValueError`` for the
client to skip.

``yard_line`` is exactly what the feed sends: 0-100 measured from the **home**
team's goal line, not the offence's. Nothing here flips it; the field-geometry
code owns that (see ``football_api.md``, "Field coordinates").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from enum import StrEnum
from typing import Any

from .playtext import PlayText, parse_text
from .teams import team_by_id

#: ``status.type.state`` values the feed uses; anything else is kept as sent.
PRE, IN, POST = "pre", "in", "post"


def _int(value: Any, default: int | None = 0) -> int | None:
    """``value`` as an int, or ``default`` for anything that isn't one (``"7"`` is)."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return default


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _bool(value: Any) -> bool:
    return value if isinstance(value, bool) else False


_REF_ID = re.compile(r"/(?:athletes|teams)/(\d+)")


def ref_id(ref: Any) -> int | None:
    """The numeric id inside an ESPN ``$ref`` URL (``.../athletes/4430807?lang=en`` -> 4430807).

    Reading it from the link means no athlete or team has to be fetched to learn who it is.
    """
    match = _REF_ID.search(ref) if isinstance(ref, str) else None
    return int(match.group(1)) if match else None


def normalise_ref(url: str) -> str:
    """Some core ``$ref`` links use the host ``espn.pvt``, which does not resolve; ESPN's own
    public host is ``espn.com`` (``football_api.md``). Also upgrades ``http`` to ``https``."""
    return url.replace("espn.pvt", "espn.com").replace("http://", "https://", 1)


def _team_id(raw: Any) -> int | None:
    """A team's ESPN id from either shape: ``{"id": "19"}`` or ``{"$ref": ".../teams/19?..."}``."""
    team = _dict(raw)
    return _int(team.get("id"), None) if team.get("id") is not None else ref_id(team.get("$ref"))


def _parse_time(value: Any) -> datetime | None:
    """ESPN's ISO times: ``2026-11-13T01:15Z`` (no seconds) or with them."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class FbTeam:
    #: The NFL abbreviation (``NYG``). For a team that is not one of the 32
    #: (a Pro Bowl side, say) it is ESPN's own abbreviation, kept as sent.
    abbrev: str
    espn_id: int | None
    #: True when ``espn_id`` is one of the 32 NFL teams in ``football/teams.py``.
    is_nfl: bool
    home: bool
    score: int = 0
    #: Points per period, in order. Empty before the game starts.
    linescores: tuple[int, ...] = ()
    #: ``5-2-1``; the overall record, if the feed gave one.
    record: str = ""
    home_record: str = ""
    road_record: str = ""
    #: ``True``/``False`` once the game is decided, ``None`` before.
    winner: bool | None = None

    @staticmethod
    def from_api(raw: Any) -> FbTeam:
        co = _dict(raw)
        team = _dict(co.get("team"))
        espn_id = _int(team.get("id", co.get("id")), None)
        abbrev = _str(team.get("abbreviation")).strip().upper()
        is_nfl = False
        if espn_id is not None:
            try:
                abbrev = team_by_id(espn_id).abbrev
                is_nfl = True
            except KeyError:
                pass
        if not abbrev:
            raise ValueError("competitor has no team abbreviation or known id")
        records = {
            _str(_dict(r).get("type")): _str(_dict(r).get("summary"))
            for r in _list(co.get("records"))
        }
        winner = co.get("winner")
        return FbTeam(
            abbrev=abbrev,
            espn_id=espn_id,
            is_nfl=is_nfl,
            home=_str(co.get("homeAway")) == "home",
            score=_int(co.get("score")) or 0,
            linescores=tuple(
                _int(_dict(ls).get("value")) or 0 for ls in _list(co.get("linescores"))
            ),
            record=records.get("total", ""),
            home_record=records.get("home", ""),
            road_record=records.get("road", ""),
            winner=winner if isinstance(winner, bool) else None,
        )


@dataclass(frozen=True, slots=True)
class FbLastPlay:
    """The ``lastPlay`` ESPN attaches to a live situation: a summary, not the play feed."""

    id: str
    type: str  #: raw ``type.text``, e.g. ``Pass Reception``
    text: str
    stat_yardage: int
    score_value: int
    team_id: int | None
    #: ``yardLine`` at the start and end of the play (home-goal-line based), if sent.
    start_yard_line: int | None
    end_yard_line: int | None

    @staticmethod
    def from_api(raw: Any) -> FbLastPlay | None:
        lp = _dict(raw)
        if not lp:
            return None
        return FbLastPlay(
            id=str(lp.get("id", "")),
            type=_str(_dict(lp.get("type")).get("text")),
            text=_str(lp.get("text")).strip(),
            stat_yardage=_int(lp.get("statYardage")) or 0,
            score_value=_int(lp.get("scoreValue")) or 0,
            team_id=_int(_dict(lp.get("team")).get("id"), None),
            start_yard_line=_int(_dict(lp.get("start")).get("yardLine"), None),
            end_yard_line=_int(_dict(lp.get("end")).get("yardLine"), None),
        )


@dataclass(frozen=True, slots=True)
class FbSituation:
    """Where a live game stands right now. Only present while a game is on."""

    down: int | None
    distance: int | None
    #: 0-100 from the HOME goal line, exactly as sent.
    yard_line: int | None
    #: ``2nd & 7`` and ``2nd & 7 at NYG 28``.
    short_down_distance_text: str
    down_distance_text: str
    #: ``NYG 28``: the spot as a fan would say it.
    possession_text: str
    #: ESPN team id of the team with the ball, if sent.
    possession_team_id: int | None
    is_red_zone: bool
    home_timeouts: int | None
    away_timeouts: int | None
    last_play: FbLastPlay | None

    @staticmethod
    def from_api(raw: Any) -> FbSituation | None:
        s = _dict(raw)
        if not s:
            return None
        return FbSituation(
            down=_int(s.get("down"), None),
            distance=_int(s.get("distance"), None),
            yard_line=_int(s.get("yardLine"), None),
            short_down_distance_text=_str(s.get("shortDownDistanceText")),
            down_distance_text=_str(s.get("downDistanceText")),
            possession_text=_str(s.get("possessionText")),
            possession_team_id=_int(s.get("possession"), None),
            is_red_zone=_bool(s.get("isRedZone")),
            home_timeouts=_int(s.get("homeTimeouts"), None),
            away_timeouts=_int(s.get("awayTimeouts"), None),
            last_play=FbLastPlay.from_api(s.get("lastPlay")),
        )


def _leaders(comp: dict[str, Any]) -> tuple[FbLeader, ...]:
    out = []
    for cat in _list(comp.get("leaders")):
        leader = FbLeader.from_api(_str(_dict(cat).get("name")), cat)
        if leader is not None:
            out.append(leader)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class FbLeader:
    """A game's passing, rushing or receiving leader, as the scoreboard names it (#420).

    **Only a finished game's leaders are that game's**: a scheduled game carries the same
    categories as season totals, so ``FbGame.from_api`` keeps them for a final only.
    """

    #: ``passingYards``, ``rushingYards`` or ``receivingYards``.
    category: str
    #: ``J.J. McCarthy``: the feed's short name (a full first initial form, not just a surname).
    name: str
    jersey: str
    position: str
    team_id: int | None
    #: A ready string: ``23/36, 293 YDS, 1 TD, 1 INT``.
    display: str

    @staticmethod
    def from_api(category: str, raw: Any) -> FbLeader | None:
        row = _dict(next(iter(_list(_dict(raw).get("leaders"))), None))
        athlete = _dict(row.get("athlete"))
        name = _str(athlete.get("shortName") or athlete.get("fullName"))
        if not name:
            return None
        return FbLeader(
            category=category,
            name=name,
            jersey=_str(athlete.get("jersey")),
            position=_str(_dict(athlete.get("position")).get("abbreviation")),
            team_id=_int(_dict(row.get("team")).get("id"), None),
            display=_str(row.get("displayValue")),
        )


@dataclass(frozen=True, slots=True)
class FbGame:
    id: int
    away: FbTeam
    home: FbTeam
    #: ``pre`` / ``in`` / ``post``; anything else is kept as the feed sent it.
    state: str
    #: ESPN's status name: ``STATUS_IN_PROGRESS``, ``STATUS_FINAL``, ``STATUS_HALFTIME`` ...
    status_name: str
    period: int
    clock_seconds: float
    display_clock: str
    #: ``12:24 - 3rd``, ``Final``, ``11/15 - 9:30 AM EST``.
    short_detail: str
    detail: str
    completed: bool
    start_utc: datetime | None
    neutral_site: bool
    venue: str
    week: int | None
    situation: FbSituation | None
    #: ``1`` preseason, ``2`` regular season, ``3`` postseason (#421).
    season_type: int | None = None
    #: Who shows it: ``("Prime Video",)``, ``("FOX",)``; empty when the feed gives none.
    broadcasts: tuple[str, ...] = ()
    #: The game's top passer, rusher and receiver; **only for a final** (see ``FbLeader``).
    leaders: tuple[FbLeader, ...] = ()

    @staticmethod
    def from_api(raw: Any) -> FbGame:
        event = _dict(raw)
        game_id = _int(event.get("id"), None)
        if game_id is None:
            raise ValueError("event has no game id")
        comp = _dict(next(iter(_list(event.get("competitions"))), None))
        competitors = [FbTeam.from_api(c) for c in _list(comp.get("competitors"))]
        away = next((t for t in competitors if not t.home), None)
        home = next((t for t in competitors if t.home), None)
        if away is None or home is None:
            raise ValueError(f"game {game_id} does not have both an away and a home team")
        status = _dict(comp.get("status") or event.get("status"))
        stype = _dict(status.get("type"))
        return FbGame(
            id=game_id,
            away=away,
            home=home,
            state=_str(stype.get("state")),
            status_name=_str(stype.get("name")),
            period=_int(status.get("period")) or 0,
            clock_seconds=float(status["clock"])
            if isinstance(status.get("clock"), (int, float))
            else 0.0,
            display_clock=_str(status.get("displayClock")),
            short_detail=_str(stype.get("shortDetail")),
            detail=_str(stype.get("detail")),
            completed=_bool(stype.get("completed")),
            start_utc=_parse_time(comp.get("startDate") or comp.get("date") or event.get("date")),
            neutral_site=_bool(comp.get("neutralSite")),
            venue=_str(_dict(comp.get("venue")).get("fullName")),
            week=_int(_dict(event.get("week")).get("number"), None),
            situation=FbSituation.from_api(comp.get("situation")),
            season_type=_int(_dict(event.get("season")).get("type"), None),
            broadcasts=tuple(
                name
                for b in _list(comp.get("broadcasts"))
                for name in (_str(n) for n in _list(_dict(b).get("names")))
                if name
            ),
            leaders=_leaders(comp) if _str(stype.get("state")) == POST else (),
        )

    # -- state ---------------------------------------------------------

    @property
    def is_pregame(self) -> bool:
        return self.state == PRE

    @property
    def is_halftime(self) -> bool:
        """Live, but between halves: no ball in play, so no field to show (#378)."""
        return self.is_live and "HALF" in self.status_name.upper()

    @property
    def is_live(self) -> bool:
        return self.state == IN

    @property
    def is_final(self) -> bool:
        return self.state == POST

    def involves(self, abbrev: str) -> bool:
        key = abbrev.strip().upper()
        return key in (self.away.abbrev, self.home.abbrev)

    def team(self, abbrev: str) -> FbTeam | None:
        key = abbrev.strip().upper()
        return next((t for t in (self.away, self.home) if t.abbrev == key), None)

    def sort_key(self) -> tuple[int, float, int]:
        """Live games first, then upcoming by kick-off, then finished; id breaks ties."""
        rank = {IN: 0, PRE: 1, POST: 2}.get(self.state, 3)
        start = self.start_utc.timestamp() if self.start_utc else 0.0
        return (rank, start, self.id)

    def status_label(self, tz: tzinfo) -> str:
        """What a text line says about the game: kick-off time, clock and quarter, or Final."""
        if self.is_pregame and self.start_utc is not None:
            local = self.start_utc.astimezone(tz)
            return f"{local:%a} {local.month}/{local.day} {local:%I:%M %p}".replace(" 0", " ")
        return self.short_detail or self.detail or self.status_name


# -- plays (#353) --------------------------------------------------------------


class PlayKind(StrEnum):
    """What sort of play ESPN says it was, from ``type.text``.

    Only the types in the sample are named. Anything else is ``UNKNOWN`` with the
    raw type kept on the ``Play``, never lost and never an error. Some things the
    animation cares about are *not* kinds because ESPN does not make them types:
    a kneel is a ``RUSH``, a spike and an intentional grounding are a
    ``PASS_INCOMPLETE`` (see ``Play.info``).
    """

    RUSH = "rush"
    PASS_COMPLETE = "pass_complete"
    PASS_INCOMPLETE = "pass_incomplete"
    SACK = "sack"
    KICKOFF = "kickoff"
    PUNT = "punt"
    FIELD_GOAL_GOOD = "field_goal_good"
    FIELD_GOAL_MISSED = "field_goal_missed"
    PENALTY = "penalty"
    TIMEOUT = "timeout"
    OFFICIAL_TIMEOUT = "official_timeout"
    TWO_MINUTE_WARNING = "two_minute_warning"
    END_PERIOD = "end_period"
    END_HALF = "end_half"
    END_REGULATION = "end_regulation"
    END_GAME = "end_game"
    COIN_TOSS = "coin_toss"
    RUSHING_TOUCHDOWN = "rushing_touchdown"
    PASSING_TOUCHDOWN = "passing_touchdown"
    INTERCEPTION_RETURN = "interception_return"
    INTERCEPTION_TOUCHDOWN = "interception_touchdown"
    FUMBLE_RECOVERY_OWN = "fumble_recovery_own"
    FUMBLE_RECOVERY_OPPONENT = "fumble_recovery_opponent"
    SACK_FUMBLE = "sack_fumble"
    MUFFED_PUNT = "muffed_punt"
    OTHER_TOUCHDOWN = "other_touchdown"
    UNKNOWN = "unknown"


_KINDS: dict[str, PlayKind] = {
    "rush": PlayKind.RUSH,
    "pass reception": PlayKind.PASS_COMPLETE,
    "pass incompletion": PlayKind.PASS_INCOMPLETE,
    "sack": PlayKind.SACK,
    "kickoff": PlayKind.KICKOFF,
    "punt": PlayKind.PUNT,
    "field goal good": PlayKind.FIELD_GOAL_GOOD,
    "field goal missed": PlayKind.FIELD_GOAL_MISSED,
    "penalty": PlayKind.PENALTY,
    "timeout": PlayKind.TIMEOUT,
    "official timeout": PlayKind.OFFICIAL_TIMEOUT,
    "two-minute warning": PlayKind.TWO_MINUTE_WARNING,
    "end period": PlayKind.END_PERIOD,
    "end of half": PlayKind.END_HALF,
    "end of regulation": PlayKind.END_REGULATION,
    "end of game": PlayKind.END_GAME,
    "coin toss": PlayKind.COIN_TOSS,
    "rushing touchdown": PlayKind.RUSHING_TOUCHDOWN,
    "passing touchdown": PlayKind.PASSING_TOUCHDOWN,
    "pass interception return": PlayKind.INTERCEPTION_RETURN,
    "interception return touchdown": PlayKind.INTERCEPTION_TOUCHDOWN,
    "fumble recovery (own)": PlayKind.FUMBLE_RECOVERY_OWN,
    "fumble recovery (opponent)": PlayKind.FUMBLE_RECOVERY_OPPONENT,
    "sack opp fumble recovery": PlayKind.SACK_FUMBLE,
    "muffed punt recovery (opponent)": PlayKind.MUFFED_PUNT,
}


def classify(type_text: str) -> PlayKind:
    """The kind for ESPN's ``type.text``; ``UNKNOWN`` for anything not recognised."""
    key = " ".join(str(type_text or "").lower().split())
    if key in _KINDS:
        return _KINDS[key]
    if "touchdown" in key:  # a type not seen yet, but a touchdown all the same
        return PlayKind.OTHER_TOUCHDOWN
    return PlayKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class FieldPos:
    """Where the ball is, before or after a play. ``yard_line`` as the feed sends it."""

    #: 0-100 from the HOME goal line (not the offence's). See ``football_api.md``.
    yard_line: int | None
    #: Yards to the goal the offence is attacking, relative to the offence.
    yards_to_endzone: int | None
    down: int | None
    distance: int | None
    down_distance_text: str
    short_down_distance_text: str
    possession_text: str
    #: ESPN id of the team the position is for (the offence), if sent.
    team_id: int | None

    @staticmethod
    def from_api(raw: Any) -> FieldPos | None:
        pos = _dict(raw)
        if not pos:
            return None
        return FieldPos(
            yard_line=_int(pos.get("yardLine"), None),
            yards_to_endzone=_int(pos.get("yardsToEndzone"), None),
            down=_int(pos.get("down"), None),
            distance=_int(pos.get("distance"), None),
            down_distance_text=_str(pos.get("downDistanceText")),
            short_down_distance_text=_str(pos.get("shortDownDistanceText")),
            possession_text=_str(pos.get("possessionText")),
            team_id=_team_id(pos.get("team")),
        )


@dataclass(frozen=True, slots=True)
class Participant:
    """Someone named on a play by the core feed: a role and an athlete id (#354).

    The id comes straight from the athlete ``$ref``; nothing is fetched to read it. Who the
    athlete is, and their jersey number, comes from the team roster (``football/people.py``).
    """

    #: ``passer``, ``receiver``, ``rusher``, ``scorer``, ``patScorer``, ``kicker``, ``returner``,
    #: ``fumbler``, ``forcedBy``, ``sackedBy``, ``passDefender``, ``punter``, ``tackler``, ...
    role: str
    athlete_id: int | None
    #: ESPN's ``order`` among the play's participants (0 if not given).
    order: int = 0

    @staticmethod
    def from_api(raw: Any) -> Participant | None:
        p = _dict(raw)
        role = _str(p.get("type"))
        athlete = _dict(p.get("athlete"))
        athlete_id = _int(athlete.get("id"), None) if athlete.get("id") is not None else None
        if athlete_id is None:
            athlete_id = ref_id(athlete.get("$ref"))
        if not role and athlete_id is None:
            return None
        return Participant(role=role, athlete_id=athlete_id, order=_int(p.get("order")) or 0)


@dataclass(frozen=True, slots=True)
class Play:
    #: ESPN's play id (digits as a string). Stable per play: what the queue de-duplicates on.
    id: str
    #: ``sequenceNumber``: the order plays happened in. Ids are not guaranteed to sort.
    sequence: int
    kind: PlayKind
    #: The raw ``type.text``, kept even when ``kind`` is ``UNKNOWN``.
    type: str
    text: str
    period: int
    clock: str
    wallclock: datetime | None
    stat_yardage: int
    scoring_play: bool
    is_turnover: bool
    is_penalty: bool
    #: The score after the play.
    away_score: int
    home_score: int
    yards_after_catch: int | None
    start: FieldPos | None
    end: FieldPos | None
    #: What the text says (kick distance, returner, penalty, review ...), parsed defensively.
    info: PlayText
    #: Who did it, by athlete id, when the feed names them (the core feed always does, the site
    #: summary rarely). See ``football/people.py`` for turning these into names and numbers.
    participants: tuple[Participant, ...] = ()

    @staticmethod
    def from_api(raw: Any) -> Play:
        p = _dict(raw)
        play_id = str(p.get("id", "")).strip()
        if not play_id:
            raise ValueError("play has no id")
        type_text = _str(_dict(p.get("type")).get("text"))
        text = _str(p.get("text")).strip()
        return Play(
            id=play_id,
            sequence=_int(p.get("sequenceNumber")) or 0,
            kind=classify(type_text),
            type=type_text,
            text=text,
            period=_int(_dict(p.get("period")).get("number")) or 0,
            clock=_str(_dict(p.get("clock")).get("displayValue")),
            wallclock=_parse_time(p.get("wallclock")),
            stat_yardage=_int(p.get("statYardage")) or 0,
            scoring_play=_bool(p.get("scoringPlay")),
            is_turnover=_bool(p.get("isTurnover")),
            is_penalty=_bool(p.get("isPenalty")),
            away_score=_int(p.get("awayScore")) or 0,
            home_score=_int(p.get("homeScore")) or 0,
            yards_after_catch=_int(p.get("yardsAfterCatch"), None),
            start=FieldPos.from_api(p.get("start")),
            end=FieldPos.from_api(p.get("end")),
            info=parse_text(type_text, text),
            participants=tuple(
                part
                for part in (Participant.from_api(x) for x in _list(p.get("participants")))
                if part is not None
            ),
        )

    @property
    def is_touchdown(self) -> bool:
        return self.kind in (
            PlayKind.RUSHING_TOUCHDOWN,
            PlayKind.PASSING_TOUCHDOWN,
            PlayKind.INTERCEPTION_TOUCHDOWN,
            PlayKind.OTHER_TOUCHDOWN,
        )

    def sort_key(self) -> tuple[int, float, str]:
        """Play order: ``sequenceNumber``, then time, then id as a last tie-break."""
        when = self.wallclock.timestamp() if self.wallclock else 0.0
        return (self.sequence, when, self.id)
