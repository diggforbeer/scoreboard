"""Typed view over the parts of the NHL API this project actually renders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Game:
        clock = raw.get("clock") or {}
        descriptor = raw.get("periodDescriptor") or {}
        return cls(
            id=int(raw["id"]),
            state=str(raw.get("gameState") or "FUT").upper(),
            game_type=int(raw.get("gameType") or 2),
            start_utc=_parse_utc(raw.get("startTimeUTC")),
            away=TeamSide.from_api(raw.get("awayTeam") or {}),
            home=TeamSide.from_api(raw.get("homeTeam") or {}),
            period=int(raw.get("period") or descriptor.get("number") or 0),
            period_type=str(descriptor.get("periodType") or "REG").upper(),
            max_regulation_periods=int(descriptor.get("maxRegulationPeriods") or 3),
            clock_time=str(clock.get("timeRemaining") or "00:00"),
            clock_running=bool(clock.get("running")),
            in_intermission=bool(clock.get("inIntermission")),
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
            if self.period_type in ("OT", "SO"):
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


def conference_standings(rows: list[StandingsRow], conference: str) -> list[StandingsRow]:
    """``rows`` for one conference, ranked by overall conference position."""
    matches = [r for r in rows if r.conference == conference.strip().upper()]
    return sorted(matches, key=lambda r: r.conference_sequence)


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
