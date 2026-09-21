"""The scoreboard run loop."""

from __future__ import annotations

import dataclasses
import logging
import signal
import time
from datetime import UTC, datetime
from types import FrameType
from zoneinfo import ZoneInfo

from .config import Settings
from .display.fonts import FontSet
from .display.logos import LogoLibrary
from .display.matrix import Backend, create_matrix, load_backend
from .display.renderer import Renderer
from .nhl.api import NHLApiError, NHLClient
from .nhl.models import Game, Situation

log = logging.getLogger(__name__)

#: How long stale data stays on the board before we admit we are offline.
STALE_AFTER_SECONDS = 15 * 60
FRAME_INTERVAL = 0.5


class ScoreboardApp:
    def __init__(
        self,
        settings: Settings,
        client: NHLClient | None = None,
        backend: Backend | None = None,
    ) -> None:
        self.settings = settings
        self.tz = ZoneInfo(settings.scoreboard.timezone)
        self.client = client or NHLClient()
        self.backend = backend or load_backend()
        self.matrix, self.backend = create_matrix(settings.panel, self.backend)
        self.canvas = self.matrix.CreateFrameCanvas()
        logos = None
        if settings.scoreboard.show_logos:
            logos = LogoLibrary.default(
                size=min(settings.panel.height, 32), variant=settings.scoreboard.logo_variant
            )
        self.renderer = Renderer(
            graphics=self.backend.graphics,
            fonts=FontSet(self.backend.graphics),
            width=settings.panel.width,
            height=settings.panel.height,
            tz=self.tz,
            favourite=settings.scoreboard.favourite_team,
            logos=logos,
        )
        self.games: list[Game] = []
        self.index = 0
        self.last_success: float | None = None
        #: game id -> (fetched at, situation). Only kept for the games we
        #: actually show the indicator on: the favourite's and the on-screen one.
        self.situations: dict[int, tuple[float, Situation | None]] = {}
        self._running = False

    # -- lifecycle -------------------------------------------------------

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        log.info("Received signal %s; shutting down", signal.Signals(signum).name)
        self._running = False

    def run(self) -> None:
        self._running = True
        self.renderer.draw_message(self.canvas, "NHL", "CONNECTING")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        next_poll = 0.0
        next_rotate = 0.0
        while self._running:
            now = time.monotonic()
            if now >= next_poll:
                self.refresh()
                next_poll = now + self.poll_interval()
            if now >= next_rotate:
                self.advance()
                next_rotate = now + self.settings.scoreboard.rotate_seconds
            self.refresh_situations()
            self.draw()
            time.sleep(FRAME_INTERVAL)
        self.shutdown()

    def shutdown(self) -> None:
        try:
            self.matrix.Clear()
        finally:
            self.client.close()
        log.info("Scoreboard stopped")

    # -- data ------------------------------------------------------------

    def refresh(self) -> None:
        try:
            games = self.client.scores()
        except NHLApiError as exc:
            log.warning("Score refresh failed: %s", exc)
            return
        self.games = self.order(games)
        self.last_success = time.monotonic()
        if self.index >= len(self.games):
            self.index = 0
        log.debug("Refreshed: %d games", len(self.games))

    def situation_targets(self) -> list[Game]:
        """Live games worth a second request: the favourite's and the on-screen one.

        Everything else shows even strength; that is the trade for not
        hammering the landing endpoint once per live game every poll.
        """
        targets: list[Game] = []
        favourite = self.settings.scoreboard.favourite_team
        if favourite:
            targets += [g for g in self.games if g.is_live and g.involves(favourite)]
        if self.games:
            current = self.games[self.index]
            if current.is_live and current not in targets:
                targets.append(current)
        return targets

    def refresh_situations(self) -> None:
        now = time.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        wanted = {g.id: g for g in self.situation_targets()}
        for game_id in list(self.situations):
            if game_id not in wanted:
                del self.situations[game_id]
        for game_id, game in wanted.items():
            fetched_at = self.situations.get(game_id, (None, None))[0]
            if fetched_at is not None and now - fetched_at < interval:
                continue
            if game.in_intermission:
                self.situations[game_id] = (now, None)
                continue
            try:
                situation = self.client.situation(game_id)
            except NHLApiError as exc:
                log.debug("Situation fetch for %s failed: %s", game_id, exc)
                situation = self.situations.get(game_id, (None, None))[1]
            self.situations[game_id] = (now, situation)

    def with_situation(self, game: Game) -> Game:
        entry = self.situations.get(game.id)
        if entry is None or entry[1] is None:
            return game
        return dataclasses.replace(game, situation=entry[1])

    def order(self, games: list[Game]) -> list[Game]:
        """Sort live-first, then optionally pin the favourite team to the front.

        The sort is repeated here rather than trusted from the client so that
        display order is a property of the app, not of whoever fetched.
        """
        games = sorted(games, key=Game.sort_key)
        favourite = self.settings.scoreboard.favourite_team
        if not (favourite and self.settings.scoreboard.prefer_favourite):
            return games
        pinned = [g for g in games if g.involves(favourite)]
        rest = [g for g in games if not g.involves(favourite)]
        return pinned + rest

    def poll_interval(self) -> float:
        """Poll harder while a game is actually in progress."""
        cfg = self.settings.scoreboard
        if any(g.is_live and not g.in_intermission for g in self.games):
            return cfg.live_poll_seconds
        return cfg.poll_seconds

    def advance(self) -> None:
        if self.games:
            self.index = (self.index + 1) % len(self.games)

    # -- output ----------------------------------------------------------

    def is_stale(self) -> bool:
        if self.last_success is None:
            return True
        return (time.monotonic() - self.last_success) > STALE_AFTER_SECONDS

    def draw(self) -> None:
        if self.games and not self.is_stale():
            self.renderer.draw_game(self.canvas, self.with_situation(self.games[self.index]))
        elif self.is_stale() and self.last_success is not None:
            self.renderer.draw_message(self.canvas, "NO DATA", "CHECK NETWORK")
        elif self.last_success is None:
            self.renderer.draw_message(self.canvas, "NHL", "CONNECTING")
        elif self.settings.scoreboard.show_clock_when_idle:
            self.renderer.draw_clock(self.canvas, datetime.now(UTC))
        else:
            self.renderer.draw_message(self.canvas, "NO GAMES")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
