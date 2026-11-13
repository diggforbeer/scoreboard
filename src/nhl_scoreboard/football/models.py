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

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any

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
        )

    # -- state ---------------------------------------------------------

    @property
    def is_pregame(self) -> bool:
        return self.state == PRE

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
