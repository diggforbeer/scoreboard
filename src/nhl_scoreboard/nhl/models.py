"""Typed view over the parts of the NHL API this project actually renders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

# gameState values observed from api-web.nhle.com/v1/score/{date}
LIVE_STATES = frozenset({"LIVE", "CRIT"})
FINAL_STATES = frozenset({"FINAL", "OFF"})
PREGAME_STATES = frozenset({"FUT", "PRE"})

_ORDINALS = {1: "1ST", 2: "2ND", 3: "3RD"}


@dataclass(frozen=True, slots=True)
class TeamSide:
    abbrev: str
    name: str
    score: int
    sog: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> TeamSide:
        return cls(
            abbrev=raw.get("abbrev", "???"),
            name=_default_str(raw.get("name")),
            score=int(raw.get("score") or 0),
            sog=int(raw.get("sog") or 0),
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

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Game:
        clock = raw.get("clock") or {}
        descriptor = raw.get("periodDescriptor") or {}
        return cls(
            id=int(raw["id"]),
            state=str(raw.get("gameState", "FUT")).upper(),
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

    def sort_key(self) -> tuple[int, datetime]:
        """Live games first, then upcoming, then finals -- each by start time."""
        rank = 0 if self.is_live else (1 if self.is_pregame else 2)
        return (rank, self.start_utc)


def _default_str(value: Any) -> str:
    """The NHL API wraps localised strings as ``{"default": "Devils"}``."""
    if isinstance(value, dict):
        return str(value.get("default", ""))
    return str(value or "")


def _parse_utc(value: Any) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
