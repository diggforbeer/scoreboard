"""Typed events from plays and scores: what the screens will react to (#356).

No drawing and no sound here, only the decision "something worth a screen just happened,
to whom, and how big". The screens (celebrations, the turnover alert, the field goal
screens) are later stories; they read these.

Rules, from ``football_screen.md``:

* **Who scored comes from the score delta**, never from possession, so a pick-six counts
  for the defence. The feed's own running score is on every play.
* **Scoping** decides how big, or whether, an event is: the favourite's scores are
  ``FULL`` (and carry the sound), a followed team's are ``QUICK``, anything else is not
  emitted at all. As on the NHL side, in the **favourite's own game only the favourite's
  scores count**; two followed teams meeting both count. The one exception is **field
  goals**: the outcome, made or missed, is shown for *either* team in a followed game
  (``PLAIN`` for a team that is not followed). Turnovers and the coin toss are about the
  game rather than a team: ``FULL`` in the favourite's game, ``QUICK`` in a followed game.
* **Nothing fires for the score the board started with.** A game's score is seeded from the
  play queue's baseline, and a fresh detector (a new mode after a sport switch) starts
  empty; an unseeded game treats its first play as the baseline rather than guess.
* **Skipped plays still count.** The queue may skip plays to catch up; a touchdown among
  them must still celebrate, so the detector reads every skipped play as well as the one
  shown, in order.
* **Sound** is a flag, not a sound: only the favourite's touchdown and made field goal.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .models import FbGame, Play, PlayKind
from .queue import Shown
from .teams import team_by_id

if TYPE_CHECKING:
    from ..config import FootballConfig

log = logging.getLogger(__name__)


class Scope(StrEnum):
    """How big a screen an event gets. An event with no scope is simply not emitted."""

    FULL = "full"  #: the favourite: the full celebration or alert
    QUICK = "quick"  #: a followed team: the quick version
    PLAIN = "plain"  #: shown, but not as a celebration: a field goal by a team nobody follows


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    play: Play
    game_id: int
    #: The team the event is about: the one that scored or kicked, gained the ball, or receives.
    team: str
    scope: Scope
    #: Only the favourite's touchdown and made field goal carry a sound (to start).
    sound: bool = False
    #: The score after the play.
    away_score: int = 0
    home_score: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreEvent(Event):
    points: int = 0
    away_before: int = 0
    home_before: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class Touchdown(ScoreEvent):
    #: How: ``run``, ``pass``, ``interception`` (a pick-six) or ``return`` (fumble, kick, punt).
    via: str = ""
    #: ``good`` / ``no good`` / ``""`` for the point after, and the two-point attempt's result.
    extra_point: str = ""
    two_point: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class FieldGoal(ScoreEvent):
    made: bool = True
    yards: int | None = None
    #: ``Wide Left``, ``Wide Right``, ``Short``, ``Blocked`` on a miss.
    miss: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class GenericScore(ScoreEvent):
    """A score of a kind nothing else names (a safety, an unrecognised return, ...)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Turnover(Event):
    #: ``interception``, ``fumble``, ``sack_fumble``, ``muffed_punt`` or ``on_downs``.
    reason: str = ""
    #: ``team`` gained the ball from this team.
    lost_by: str = ""
    #: For the favourite: ``gained`` or ``lost`` the ball; ``neither`` when the favourite is not one
    #: of the two teams (a followed team's game). A screen colours its alert by it (#394).
    favourite: str = "neither"


@dataclass(frozen=True, slots=True, kw_only=True)
class CoinToss(Event):
    """``team`` receives the opening kickoff, ``kicker`` kicks it (not who won the toss)."""

    kicker: str = ""


_TD_VIA = {
    PlayKind.RUSHING_TOUCHDOWN: "run",
    PlayKind.PASSING_TOUCHDOWN: "pass",
    PlayKind.INTERCEPTION_TOUCHDOWN: "interception",
}
_TURNOVER_REASON = {
    PlayKind.INTERCEPTION_RETURN: "interception",
    PlayKind.FUMBLE_RECOVERY_OPPONENT: "fumble",
    PlayKind.SACK_FUMBLE: "sack_fumble",
    PlayKind.MUFFED_PUNT: "muffed_punt",
}
#: A scrimmage play that ends with the other team holding the ball on fourth down is a
#: turnover on downs. In 13 real games (2,441 plays) possession changed on a scrimmage play
#: only on fourth down (14 times, no false positives).
_SCRIMMAGE = frozenset(
    {PlayKind.RUSH, PlayKind.PASS_COMPLETE, PlayKind.PASS_INCOMPLETE, PlayKind.SACK}
)


class EventDetector:
    def __init__(self, football: Callable[[], FootballConfig]) -> None:
        """``football`` returns the live ``[football]`` settings, read at each play, so a
        change of favourite or followed teams applies to the very next play."""
        self._football = football
        self._scores: dict[int, tuple[int, int]] = {}
        self._toss_done: set[int] = set()

    # -- seeding -----------------------------------------------------------

    def seeded(self, game_id: int) -> bool:
        return game_id in self._scores

    def seed(self, game_id: int, baseline: Play | None) -> None:
        """Start a game's score from the play queue's baseline (``None``: not started, 0-0)."""
        if baseline is None:
            self._scores[game_id] = (0, 0)
        else:
            self._scores[game_id] = (baseline.away_score, baseline.home_score)

    def retract(self, game_id: int, away_points: int, home_points: int) -> None:
        """Take points back off a game's running score after a reversal (#357).

        A reversed touchdown leaves the tracked score too high: the next play's score comes
        from a game in which it never happened, so without this its real touchdown would show
        no change and go uncelebrated. Subtracting only the reversed points (not resetting to
        the rewritten play's score) keeps later, still-valid scores intact.
        """
        away, home = self._scores.get(game_id, (0, 0))
        if game_id in self._scores:
            self._scores[game_id] = (max(0, away - away_points), max(0, home - home_points))

    def forget(self, keep: Callable[[int], bool]) -> None:
        """Drop games ``keep`` rejects (a game left the slate)."""
        for game_id in [g for g in self._scores if not keep(g)]:
            del self._scores[game_id]
        self._toss_done = {g for g in self._toss_done if keep(g)}

    # -- detection -----------------------------------------------------------

    def on_shown(self, game: FbGame, shown: Shown) -> list[Event]:
        """The events for a play the queue handed out, **and every play it skipped**."""
        plays = sorted([*shown.skipped, shown.play], key=Play.sort_key)
        return self.on_plays(game, plays)

    def on_plays(self, game: FbGame, plays: Sequence[Play]) -> list[Event]:
        events: list[Event] = []
        for play in plays:
            events.extend(self._on_play(game, play))
        return events

    def _on_play(self, game: FbGame, play: Play) -> list[Event]:
        cfg = self._football()
        before = self._scores.get(game.id)
        self._scores[game.id] = (play.away_score, play.home_score)
        out: list[Event] = []

        toss = self._coin_toss(game, play, cfg)
        if toss is not None:
            out.append(toss)
        if before is None:
            # Nothing seeded this game: this play is the baseline, not news.
            log.info("[%s] unseeded game: treating play %s as the baseline", game.id, play.id)
            return out

        deltas = (play.away_score - before[0], play.home_score - before[1])
        scored = False
        for side, delta in zip((game.away, game.home), deltas, strict=True):
            if delta > 0:
                scored = True
                event = self._score(game, play, side.abbrev, delta, before, cfg)
                if event is not None:
                    out.append(event)

        if not scored:
            miss = self._field_goal_miss(game, play, before, cfg)
            if miss is not None:
                out.append(miss)
            turnover = self._turnover(game, play, cfg)
            if turnover is not None:
                out.append(turnover)
        return out

    # -- the pieces ------------------------------------------------------------

    def _score(
        self, game: FbGame, play: Play, team: str, points: int, before: tuple[int, int], cfg
    ) -> Event | None:
        common = dict(
            play=play,
            game_id=game.id,
            team=team,
            away_score=play.away_score,
            home_score=play.home_score,
            points=points,
            away_before=before[0],
            home_before=before[1],
        )
        info = play.info
        if play.kind == PlayKind.FIELD_GOAL_GOOD:
            scope = _field_goal_scope(team, game, cfg, made=True)
            if scope is None:
                return None
            return FieldGoal(
                **common, scope=scope, sound=_favourite_sound(team, scope, cfg),
                made=True, yards=info.fg_yards,
            )  # fmt: skip
        scope = _score_scope(team, game, cfg)
        if scope is None:
            return None
        if play.is_touchdown:
            via = _TD_VIA.get(play.kind) or ("return" if play.kind != PlayKind.UNKNOWN else "")
            return Touchdown(
                **common, scope=scope, sound=_favourite_sound(team, scope, cfg),
                via=via, extra_point=info.extra_point, two_point=info.two_point,
            )  # fmt: skip
        return GenericScore(**common, scope=scope)

    def _field_goal_miss(
        self, game: FbGame, play: Play, before: tuple[int, int], cfg
    ) -> FieldGoal | None:
        if play.kind != PlayKind.FIELD_GOAL_MISSED:
            return None
        team = _abbrev(game, play.start.team_id if play.start else None)
        if not team:
            return None
        scope = _field_goal_scope(team, game, cfg, made=False)
        if scope is None:
            return None
        return FieldGoal(
            play=play, game_id=game.id, team=team, scope=scope,
            away_score=play.away_score, home_score=play.home_score,
            made=False, yards=play.info.fg_yards, miss=play.info.fg_miss,
            away_before=before[0], home_before=before[1],
        )  # fmt: skip

    def _turnover(self, game: FbGame, play: Play, cfg) -> Turnover | None:
        reason = _TURNOVER_REASON.get(play.kind, "")
        if not (play.is_turnover or reason):
            reason = ""
            start, end = play.start, play.end
            if (
                play.kind in _SCRIMMAGE
                and start is not None
                and end is not None
                and start.down == 4
                and start.team_id is not None
                and end.team_id is not None
                and start.team_id != end.team_id
            ):
                reason = "on_downs"
        elif not reason:
            reason = "turnover"
        if not reason:
            return None
        scope = _game_scope(game, cfg)
        if scope is None:
            return None
        gained = _abbrev(game, play.end.team_id if play.end else None)
        lost = _abbrev(game, play.start.team_id if play.start else None)
        if not gained:
            return None
        favourite, _ = _followed(cfg)
        if favourite and favourite == gained:
            relation = "gained"
        elif favourite and favourite == lost:
            relation = "lost"
        else:
            relation = "neither"
        return Turnover(
            play=play, game_id=game.id, team=gained, scope=scope, reason=reason, lost_by=lost,
            favourite=relation, away_score=play.away_score, home_score=play.home_score,
        )  # fmt: skip

    def _coin_toss(self, game: FbGame, play: Play, cfg) -> CoinToss | None:
        """The receiver of the opening kickoff.

        The site feed omits the ``Coin Toss`` play (``football_api.md``), so the opening
        kickoff names the receiver; a ``Coin Toss`` play, if one is ever given, does too.
        The opening kickoff is the one at 15:00 in the first quarter (a kickoff after an
        early score shows the time left), so a board that joins mid-game, whose baseline
        already holds it, never sees it again.
        """
        if game.id in self._toss_done:
            return None
        opening_kick = play.kind == PlayKind.KICKOFF and play.period == 1 and play.clock == "15:00"
        if play.kind != PlayKind.COIN_TOSS and not opening_kick:
            return None
        receiver = _abbrev(game, play.end.team_id if play.end else None)
        kicker = _abbrev(game, play.start.team_id if play.start else None)
        self._toss_done.add(game.id)
        scope = _game_scope(game, cfg)
        if not receiver or scope is None:
            return None
        return CoinToss(
            play=play, game_id=game.id, team=receiver, scope=scope, kicker=kicker,
            away_score=play.away_score, home_score=play.home_score,
        )  # fmt: skip


# -- scoping (module-level so the table is easy to read and to test) ----------------------


def _abbrev(game: FbGame, team_id: int | None) -> str:
    if team_id is None:
        return ""
    for side in (game.away, game.home):
        if side.espn_id == team_id:
            return side.abbrev
    try:
        return team_by_id(team_id).abbrev
    except KeyError:
        return ""


def _followed(cfg: FootballConfig) -> tuple[str, set[str]]:
    return cfg.favourite_team, set(cfg.followed_teams)


def _score_scope(team: str, game: FbGame, cfg: FootballConfig) -> Scope | None:
    """A touchdown or other score: the favourite's is FULL, a followed team's QUICK.

    In the favourite's own game only the favourite's scores count (a followed team scoring
    *on* the favourite gets no screen), as on the NHL side; two followed teams meeting both
    count; an opponent's score is not emitted.
    """
    favourite, followed = _followed(cfg)
    if favourite and team == favourite:
        return Scope.FULL
    if team in followed:
        return None if favourite and game.involves(favourite) else Scope.QUICK
    return None


def _field_goal_scope(team: str, game: FbGame, cfg: FootballConfig, *, made: bool) -> Scope | None:
    """The one exception: a field goal's outcome shows for either team in a followed game."""
    favourite, followed = _followed(cfg)
    if not any(game.involves(t) for t in followed):
        return None
    if made and favourite and team == favourite:
        return Scope.FULL
    if team in followed:
        return Scope.QUICK
    return Scope.PLAIN


def _game_scope(game: FbGame, cfg: FootballConfig) -> Scope | None:
    """About the game, not a team: FULL if the favourite plays, QUICK if a followed team does."""
    favourite, followed = _followed(cfg)
    if favourite and game.involves(favourite):
        return Scope.FULL
    if any(game.involves(t) for t in followed):
        return Scope.QUICK
    return None


def _favourite_sound(team: str, scope: Scope, cfg: FootballConfig) -> bool:
    return scope == Scope.FULL and bool(cfg.favourite_team) and team == cfg.favourite_team
