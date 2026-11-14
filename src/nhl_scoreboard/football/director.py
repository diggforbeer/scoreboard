"""Decide what the NFL panel shows *now*, play by play (#377).

Everything the screens need already exists as data: the play queue (#355), the event detector
(#356), the reversal detector (#357), jersey numbers (#354). This is the one place that wires
them to the panel. It draws nothing; it hands :class:`~.mode.NflMode` a :class:`Stage` (what is
on screen, for how long, since when) and the renderer's registries draw it.

One play becomes a short run of stages::

    [coin toss]  play animation  [celebration  detail | alert]  play text

and then the board rests on whatever it showed before (``fb_scores``; the field arrives with
its own story). The rules, from ``football_screen.md``:

* **A reversal preempts** whatever is up, skips the detail screen, and is shown once.
* **A celebration preempts a play's own rest**: the animation plays first so the ball is seen
  arriving, then the celebration starts when it lands.
* **Scope decides the size** (the detector already did): ``FULL`` is the favourite's whole
  celebration and detail, ``QUICK`` a followed team's short version, ``PLAIN`` a field goal by
  a team nobody follows: the play animation only, no celebration.
* **Catch-up is the queue's job** (it drops stoppages first and skips the oldest plays). The
  events of the plays it skipped still come out, so a touchdown among them still celebrates.
* **The animation clock starts when a stage is shown**, so ``broadcast_delay_seconds`` shifts
  everything together and a stage is a pure function of the seconds since it began.
* A game already in progress at startup plays nothing from before startup (the queue baselines
  it, and the detector is seeded from that baseline).
* An unknown play type, or an event nobody has drawn yet, never throws: the renderer falls back
  to a generic animation and a generic card.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .events import (
    CoinToss,
    Event,
    EventDetector,
    FieldGoal,
    GenericScore,
    Scope,
    Touchdown,
    Turnover,
)
from .models import FbGame, Play
from .pacing import animation_seconds
from .people import Person, RosterPlayer, resolve_people
from .queue import PlayWatcher, Shown
from .reversals import Reversal, ReversalDetector
from .textlayout import playtext_seconds

if TYPE_CHECKING:
    from ..config import FootballConfig
    from .worker import FeedSnapshot

log = logging.getLogger(__name__)

#: The stages a scene can be in (``Scene.fb_stage``).
PLAY, PLAYTEXT, EVENT, DETAIL, REVERSAL = "play", "playtext", "event", "detail", "reversal"


@dataclass(frozen=True, slots=True)
class Timings:
    """Seconds each stage lasts at normal speed: the proposed values in ``football_screen.md``
    ("Timing"). Held to the ranges below by :meth:`clamped`; the owner's own come from
    ``[football]`` (``timings_from``)."""

    play: float = 3.0
    playtext: float = 5.0
    score: float = 6.0  #: ``fb_score_seconds``, held to 4-15
    score_detail: float = 8.0  #: ``fb_score_detail_seconds``
    quick: float = 4.0  #: a followed team's score
    fg_miss: float = 3.0
    turnover: float = 4.0  #: ``fb_turnover_seconds``
    reversal: float = 5.0  #: ``fb_reversal_seconds``
    cointoss: float = 6.0  #: ``fb_cointoss_seconds``

    def clamped(self) -> Timings:
        def hold(value: float, low: float, high: float) -> float:
            return max(low, min(high, value))

        return Timings(
            play=hold(self.play, 1.0, 8.0),
            playtext=hold(self.playtext, 2.0, 30.0),
            score=hold(self.score, 4.0, 15.0),
            score_detail=hold(self.score_detail, 3.0, 20.0),
            quick=hold(self.quick, 2.0, 10.0),
            fg_miss=hold(self.fg_miss, 2.0, 10.0),
            turnover=hold(self.turnover, 2.0, 10.0),
            reversal=hold(self.reversal, 3.0, 15.0),
            cointoss=hold(self.cointoss, 4.0, 12.0),
        )


def timings_from(cfg: FootballConfig) -> Timings:
    """The stage lengths the owner set in ``[football]`` (``<name>_seconds``), held to range."""
    from ..config import FOOTBALL_TIMING_RANGES

    return Timings(**{n: getattr(cfg, f"{n}_seconds") for n in FOOTBALL_TIMING_RANGES}).clamped()


@dataclass(frozen=True, slots=True)
class Stage:
    """One thing on the panel for ``seconds`` (at ``speed`` 1.0; faster while catching up)."""

    stage: str
    seconds: float
    game: FbGame
    play: Play
    people: tuple[Person, ...] = ()
    event: Event | None = None
    speed: float = 1.0

    @property
    def duration(self) -> float:
        """Real seconds on screen."""
        return self.seconds / self.speed


@dataclass(frozen=True, slots=True)
class Current:
    """The stage on screen and how far into it the board is."""

    stage: Stage
    #: Animation seconds into the stage (already scaled by its speed).
    elapsed: float


class Director:
    def __init__(
        self,
        football: Callable[[], FootballConfig],
        monotonic: Callable[[], float] = time.monotonic,
        delay_seconds: Callable[[], float] = lambda: 0.0,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        timings: Callable[[], Timings] | None = None,
    ) -> None:
        self._monotonic = monotonic
        self._timings = timings or Timings
        self.detector = EventDetector(football)
        self.reversals = ReversalDetector(self.detector)
        self.watcher = PlayWatcher(monotonic, delay_seconds, utc_now, on_applied=self._applied)
        self._games: dict[int, FbGame] = {}
        self._players: Mapping[int, Mapping[int, RosterPlayer]] = {}
        self._offered: dict[int, object] = {}
        self._reversed: deque[Reversal] = deque()
        self._stages: deque[Stage] = deque()
        self._active: Stage | None = None
        self._since = 0.0

    # -- input -----------------------------------------------------------------

    def ingest(self, snap: FeedSnapshot) -> None:
        """Take the feed worker's latest snapshot: new games, rosters, and each game's plays.

        Cheap to call every frame: a game's plays are only handed to the queue when the worker
        published a new list for it.
        """
        if snap.games is None:
            return
        self._games = {g.id: g for g in snap.games}
        self._players = snap.players
        for game_id, plays in snap.plays.items():
            if self._offered.get(game_id) is not plays:
                self._offered[game_id] = plays
                self.watcher.on_fetch(game_id, plays)
        slate = set(self._games)
        self._offered = {g: p for g, p in self._offered.items() if g in slate}
        for forget in (self.watcher, self.detector, self.reversals):
            forget.forget(lambda game_id: game_id in slate)

    def _applied(self, game_id: int | str, plays: Sequence[Play]) -> None:
        """A poll's plays got past the broadcast delay: seed the detector, look for reversals."""
        if not isinstance(game_id, int):
            return
        if not self.detector.seeded(game_id):
            self.detector.seed(game_id, self.watcher.queue(game_id).baseline)
        self._reversed.extend(self.reversals.on_poll(game_id, plays))

    # -- what is on screen -----------------------------------------------------------

    def current(self, preferred: int | None = None) -> Current | None:
        """The stage to draw now, advancing to the next when one ends; ``None`` when at rest.

        ``preferred`` is the game on screen: its plays go first, then any other watched game's.
        """
        now = self._monotonic()
        self.watcher.tick()
        if self._reversed:
            self._start_reversal(self._reversed.popleft(), now)
        if self._active is not None and now - self._since >= self._active.duration:
            self._active = None
        if self._active is None:
            self._start_next(preferred, now)
        if self._active is None:
            return None
        return Current(self._active, (now - self._since) * self._active.speed)

    @property
    def busy(self) -> bool:
        return self._active is not None or bool(self._stages)

    def _start_next(self, preferred: int | None, now: float) -> None:
        while self._active is None:
            if self._stages:
                self._active, self._since = self._stages.popleft(), now
                return
            if not self._load_play(preferred):
                return

    def _load_play(self, preferred: int | None) -> bool:
        """Take the next waiting play, from the game on screen first. False if none waits."""
        order = [g for g in self._games if g != preferred]
        if preferred in self._games:
            order.insert(0, preferred)
        for game_id in order:
            if self.watcher.queue(game_id).depth == 0:
                continue
            shown = self.watcher.next(game_id)
            if shown is not None:
                self._stages.extend(self._build(self._games[game_id], shown))
                return True
        return False

    def _start_reversal(self, reversal: Reversal, now: float) -> None:
        game = self._games.get(reversal.game_id)
        if game is None:
            return
        timings = self._timings().clamped()
        self._stages.clear()
        self._active = Stage(REVERSAL, timings.reversal, game, reversal.play, event=reversal)
        self._since = now
        log.info("[%s] reversal shown: %s (%s)", game.id, reversal.title, reversal.rule)

    # -- one play into stages ---------------------------------------------------------

    def _build(self, game: FbGame, shown: Shown) -> list[Stage]:
        timings = self._timings().clamped()
        play = shown.play
        events = self.detector.on_shown(game, shown)
        already = self.reversals.remember_all(events)
        undone = {r.original.play.id for r in already}
        people = self._people(game, play)

        def stage(kind: str, seconds: float, event: Event | None = None) -> Stage:
            subject = event.play if event is not None else play
            return Stage(
                kind,
                seconds,
                game,
                subject,
                people if subject is play else self._people(game, subject),
                event,
                shown.speed,
            )

        out: list[Stage] = []
        earlier = [e for e in events if e.play.id != play.id]
        own = [e for e in events if e.play.id == play.id]
        for event in earlier:
            out.extend(self._event_stages(event, stage, timings, undone))
        for event in own:
            if isinstance(event, CoinToss):
                out.append(stage(EVENT, timings.cointoss, event))
        # A made field goal's kick animation knows how it was scored (its scope), so the plain
        # kick of a team nobody follows can be dimmer than the favourite's (#392).
        kick = next((e for e in own if isinstance(e, FieldGoal)), None)
        seconds = timings.fg_miss if kick is not None and not kick.made else None
        out.append(stage(PLAY, seconds or animation_seconds(play, timings.play), kick))
        for event in own:
            if not isinstance(event, CoinToss):
                out.extend(self._event_stages(event, stage, timings, undone))
        for reversal in already:
            out.append(stage(REVERSAL, timings.reversal, reversal))
        # Long sentences scroll, so they stay up longer than the 5s minimum (#379).
        out.append(stage(PLAYTEXT, playtext_seconds(play.text, timings.playtext)))
        return out

    @staticmethod
    def _event_stages(event: Event, stage, timings: Timings, undone: set[str]) -> list[Stage]:
        """The celebration (and detail) an event gets, by its scope."""
        if event.play.id in undone or isinstance(event, CoinToss):
            return []
        if isinstance(event, FieldGoal) and not event.made:
            # A miss is shown for either team in a followed game (decided), at every scope, as
            # its own play stage (``fb_fg_miss``, 3s): the kick, the miss and its words in one
            # screen, so there is no separate card after it (#393).
            return []
        if isinstance(event, GenericScore):
            # A score nothing else names has one plain screen and no detail (#395).
            if event.scope == Scope.FULL:
                return [stage(EVENT, timings.score, event)]
            return [stage(EVENT, timings.quick, event)] if event.scope == Scope.QUICK else []
        if isinstance(event, Touchdown | FieldGoal):
            if event.scope == Scope.FULL:
                return [
                    stage(EVENT, timings.score, event),
                    stage(DETAIL, timings.score_detail, event),
                ]
            if event.scope == Scope.QUICK:
                return [stage(EVENT, timings.quick, event)]
            return []  # PLAIN: the play's own animation is all it gets
        if isinstance(event, Turnover):
            return [stage(EVENT, timings.turnover, event)]
        return []

    def _people(self, game: FbGame, play: Play) -> tuple[Person, ...]:
        players = self._players.get(game.id)
        return resolve_people(play, players) if players else resolve_people(play, {})
