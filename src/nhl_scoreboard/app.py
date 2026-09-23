"""The scoreboard run loop."""

from __future__ import annotations

import dataclasses
import logging
import signal
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import FrameType
from zoneinfo import ZoneInfo

from .audio import GoalHornPlayer
from .brightness import lux_to_brightness
from .config import Settings
from .display.fonts import FontSet
from .display.logos import LogoLibrary
from .display.matrix import Backend, create_matrix, load_backend
from .display.renderer import Renderer
from .light_sensor import LightSensor
from .nhl.api import NHLApiError, NHLClient
from .nhl.models import Game, Situation, StandingsRow, conference_standings, standings_window
from .status_server import StatusServer

log = logging.getLogger(__name__)

#: How long stale data stays on the board before we admit we are offline.
STALE_AFTER_SECONDS = 15 * 60
FRAME_INTERVAL = 0.5
#: The favourite's season schedule changes rarely; this is plenty.
SCHEDULE_TTL_SECONDS = 60 * 60
#: Standings don't change intra-day except right after games finish.
STANDINGS_TTL_SECONDS = 60 * 60
#: How much a new lux reading moves the smoothed value, 0-1. Low on purpose:
#: this is what keeps a cloud passing over a window, or a hand briefly
#: covering the sensor, from visibly flickering the panel.
BRIGHTNESS_SMOOTHING = 0.3


@dataclass(frozen=True, slots=True)
class Scene:
    """What the board should show right now.

    ``kind`` is one of ``game`` (live or final scoreboard), ``countdown``,
    ``preview``, ``standings``, ``clock``, ``no_games``, ``connecting``,
    ``no_data``.
    """

    kind: str
    game: Game | None = None
    standings: tuple[StandingsRow, ...] | None = None


class ScoreboardApp:
    def __init__(
        self,
        settings: Settings,
        client: NHLClient | None = None,
        backend: Backend | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        horn: GoalHornPlayer | None = None,
        light_sensor: LightSensor | None = None,
        status_server: StatusServer | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.horn = horn or GoalHornPlayer.default(
            device=settings.audio.device,
            horn_dir=settings.audio.horn_dir,
            enabled=settings.audio.enabled,
        )
        # Only probe the I2C bus when the feature is actually on -- a board
        # without the sensor shouldn't get I2C log noise every startup.
        if light_sensor is not None:
            self.light_sensor = light_sensor
        elif settings.panel.auto_brightness:
            self.light_sensor = LightSensor.open()
        else:
            self.light_sensor = None
        self._smoothed_lux: float | None = None
        self._applied_brightness = settings.panel.brightness
        self.tz = ZoneInfo(settings.scoreboard.timezone)
        self._config_mtime = self._source_mtime()
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
            logos=logos,
        )
        self.games: list[Game] = []
        self.index = 0
        self.last_success: float | None = None
        #: Wall-clock companions to last_success, for the status page (#48) --
        #: last_success itself is monotonic and not meaningful to a human.
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        if status_server is not None:
            self.status_server = status_server
        elif settings.status.enabled:
            self.status_server = StatusServer(
                snapshot=self.status_snapshot, port=settings.status.port
            )
        else:
            self.status_server = None
        #: game id -> (fetched at, situation). Only kept for the games we
        #: actually show the indicator on: the favourite's and the on-screen one.
        self.situations: dict[int, tuple[float, Situation | None]] = {}
        #: game id -> when it ended (wall clock), for final_hold_minutes. Exact
        #: if we watched it finish; estimated from the start time otherwise.
        self.ended_at: dict[int, datetime] = {}
        self._seen_live: set[int] = set()
        self._schedule: tuple[float, list[Game]] | None = None
        #: monotonic time before which a failed schedule fetch won't retry --
        #: without this, a schedule outage gets hit every select_scene() call
        #: (every FRAME_INTERVAL) instead of respecting SCHEDULE_TTL_SECONDS.
        self._schedule_retry_after: float = 0.0
        self._standings: tuple[float, list[StandingsRow]] | None = None
        #: same backoff as _schedule_retry_after, for standings failures.
        self._standings_retry_after: float = 0.0
        #: game id -> the favourite's own score last seen in that game, so a
        #: goal can be detected as an increase. Set on first sighting without
        #: firing, so a game already 3-1 at startup does not fire a goal.
        self._known_favourite_score: dict[int, int] = {}
        #: (game id, monotonic time) of the most recent favourite goal, for
        #: how long the goal scene stays up.
        self.last_goal: tuple[int, float] | None = None
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
        if self.status_server is not None:
            self.status_server.start()
        self.renderer.draw_message(self.canvas, "NHL", "CONNECTING")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        next_poll = 0.0
        next_rotate = 0.0
        next_brightness = 0.0
        while self._running:
            now = self.monotonic()
            self.reload_config_if_changed()
            if now >= next_poll:
                self.refresh()
                next_poll = now + self.poll_interval()
            if now >= next_rotate:
                self.advance()
                next_rotate = now + self.settings.scoreboard.rotate_seconds
            if now >= next_brightness:
                self.refresh_brightness()
                next_brightness = now + self.settings.panel.brightness_poll_seconds
            self.refresh_situations()
            self.draw()
            time.sleep(FRAME_INTERVAL)
        self.shutdown()

    def shutdown(self) -> None:
        try:
            if self.status_server is not None:
                self.status_server.stop()
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
            self._record_error(f"score refresh: {exc}")
            return
        self.games = self.order(games)
        self.last_success = self.monotonic()
        self.last_success_at = self.clock()
        self._detect_goals(self.games)
        now = self.clock()
        for game in self.games:
            if game.is_live:
                self._seen_live.add(game.id)
            elif game.is_final and game.id not in self.ended_at:
                # Watched it finish: now is the end. Found it already over
                # (typically at startup): the API has no end time, so
                # estimate one rather than holding a stale final for the
                # full window from whenever we happened to start.
                watched = game.id in self._seen_live
                self.ended_at[game.id] = now if watched else min(now, game.estimated_end())
                log.debug(
                    "Game %s ended at %s (%s)",
                    game.id,
                    self.ended_at[game.id],
                    "observed" if watched else "estimated",
                )
        if self.index >= len(self.games):
            self.index = 0
        log.debug("Refreshed: %d games", len(self.games))

    def _record_error(self, message: str) -> None:
        """Track the most recent fetch failure, for the status page (#48)."""
        self.last_error = message
        self.last_error_at = self.clock()

    # -- config reload (#51) ----------------------------------------------

    def _source_mtime(self) -> float | None:
        path = self.settings.source_path
        if path is None:
            return None
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def reload_config_if_changed(self) -> bool:
        """Reload scoreboard.toml in place if it changed on disk since last checked.

        Polls mtime rather than reacting to a signal from any particular
        editor: the file is documented to be editable by any method -- SD
        card on another machine, ``nano`` over SSH, or the eventual web
        editor (#48) -- and all three need to pick up a change the same way.
        Most settings are already read fresh from ``self.settings`` every
        loop iteration; ``[audio]`` and the logo library are not, so those
        get rebuilt explicitly here. ``[panel]`` geometry
        (rows/cols/chain_length/hardware_mapping/...) is baked into the
        already-constructed ``RGBMatrix`` and deliberately NOT reloaded --
        that needs a process restart.
        """
        mtime = self._source_mtime()
        if mtime is None or mtime == self._config_mtime:
            return False
        self._config_mtime = mtime
        try:
            new_settings = Settings.from_toml(self.settings.source_path)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            log.warning("Config reload failed, keeping previous settings: %s", exc)
            return False
        self._apply_reloaded_settings(new_settings)
        log.info("Reloaded configuration from %s", new_settings.source_path)
        return True

    def _apply_reloaded_settings(self, new_settings: Settings) -> None:
        old = self.settings
        audio_changed = dataclasses.astuple(old.audio) != dataclasses.astuple(new_settings.audio)
        logos_changed = (
            old.scoreboard.show_logos != new_settings.scoreboard.show_logos
            or old.scoreboard.logo_variant != new_settings.scoreboard.logo_variant
        )
        timezone_changed = old.scoreboard.timezone != new_settings.scoreboard.timezone

        self.settings = new_settings

        if timezone_changed:
            self.tz = ZoneInfo(new_settings.scoreboard.timezone)
            self.renderer.tz = self.tz

        if audio_changed:
            self.horn = GoalHornPlayer.default(
                device=new_settings.audio.device,
                horn_dir=new_settings.audio.horn_dir,
                enabled=new_settings.audio.enabled,
            )

        if logos_changed:
            logos = None
            if new_settings.scoreboard.show_logos:
                logos = LogoLibrary.default(
                    size=min(new_settings.panel.height, 32),
                    variant=new_settings.scoreboard.logo_variant,
                )
            self.renderer.logos = logos

    # -- auto brightness ---------------------------------------------------

    def refresh_brightness(self) -> None:
        """Re-apply matrix brightness: night mode, else the ambient sensor, else static.

        Night mode (#92) wins over the ambient sensor while it's actively
        dimming -- a scheduled window must dim even with the lights on, and
        is already held off during a live game, which a lux sensor in a
        dark TV room can't know about. Outside it, the sensor (if any)
        drives brightness exactly as before; with no sensor the static
        ``brightness`` is re-applied, which is what brings the panel back
        up once a night window ends. A sensor that isn't answering leaves
        brightness where it is.
        """
        if self._night_mode_active():
            self._apply_brightness(self.settings.night_mode.dim_brightness)
            return
        if self.light_sensor is None:
            self._apply_brightness(self.settings.panel.brightness)
            return
        lux = self.light_sensor.read_lux()
        if lux is None:
            return
        self._smoothed_lux = (
            lux
            if self._smoothed_lux is None
            else self._smoothed_lux + BRIGHTNESS_SMOOTHING * (lux - self._smoothed_lux)
        )
        panel = self.settings.panel
        target = lux_to_brightness(self._smoothed_lux, panel.min_brightness, panel.max_brightness)
        self._apply_brightness(target)

    def _apply_brightness(self, target: int) -> None:
        if target == self._applied_brightness:
            return
        self._applied_brightness = target
        try:
            self.matrix.brightness = target
        except (AttributeError, TypeError):
            # The emulator and real rgbmatrix binding both expose a live
            # settable brightness; a backend that doesn't just keeps
            # whatever it was constructed with.
            log.debug("Backend %s has no settable brightness", self.backend.name)

    # -- night mode (#92) ------------------------------------------------

    def _in_night_window(self) -> bool:
        cfg = self.settings.night_mode
        now = self.clock().astimezone(self.tz).time()
        if cfg.start <= cfg.end:
            return cfg.start <= now < cfg.end
        return now >= cfg.start or now < cfg.end

    def _night_mode_suppressed(self) -> bool:
        """A relevant game is live, or finished less than cooldown_minutes ago.

        "tracked" with no favourite_team has nothing to track, so it
        behaves as "all" -- a normal combination (rotation = "all" with
        night mode on), not a misconfiguration worth a warning.
        """
        cfg = self.settings.night_mode
        favourite = self.settings.scoreboard.favourite_team
        if cfg.suppress_scope == "all" or not favourite:
            candidates = self.games
        else:
            candidates = [g for g in self.games if g.involves(favourite)]
        if any(g.is_live for g in candidates):
            return True
        ended = [self.ended_at[g.id] for g in candidates if g.id in self.ended_at]
        if not ended:
            return False
        return self.clock() - max(ended) < timedelta(minutes=cfg.cooldown_minutes)

    def _night_mode_active(self) -> bool:
        """Should the panel be at night_mode.dim_brightness right now?"""
        return (
            self.settings.night_mode.enabled
            and self._in_night_window()
            and not self._night_mode_suppressed()
        )

    # -- goal detection ---------------------------------------------------

    def _favourite_score(self, game: Game) -> int | None:
        favourite = self.settings.scoreboard.favourite_team
        if not favourite or not game.involves(favourite):
            return None
        return game.home.score if game.home.abbrev == favourite else game.away.score

    def _detect_goals(self, games: list[Game]) -> None:
        """A favourite-team goal: their own score increased since we last saw it.

        Scoped to the favourite only -- same reasoning as the power-play
        indicator (situation_targets): this is a favourite-team board
        feature, not a "celebrate every goal in every game" one.
        """
        for game in games:
            score = self._favourite_score(game)
            if score is None:
                continue
            previous = self._known_favourite_score.get(game.id)
            self._known_favourite_score[game.id] = score
            if previous is not None and score > previous:
                self._on_goal(game)

    def _on_goal(self, game: Game) -> None:
        favourite = self.settings.scoreboard.favourite_team
        log.info(
            "GOAL: %s %s %d-%d %s",
            favourite,
            game.away.abbrev,
            game.away.score,
            game.home.score,
            game.home.abbrev,
        )
        self.last_goal = (game.id, self.monotonic())
        self.horn.play(favourite)

    # -- favourite mode --------------------------------------------------

    def favourite_game_today(self) -> Game | None:
        favourite = self.settings.scoreboard.favourite_team
        if not favourite:
            return None
        return next((g for g in self.games if g.involves(favourite)), None)

    def next_favourite_game(self, *, allow_fetch: bool = True) -> Game | None:
        """The favourite's next game from the season schedule, cached an hour.

        Today's game is excluded once it is final so the board moves on to
        the one after it. ``allow_fetch=False`` (used by the status page,
        #61) skips the network call entirely and answers from whatever is
        already cached -- the status thread must never race the main loop
        into the same fetch or block on it.
        """
        favourite = self.settings.scoreboard.favourite_team
        if not favourite:
            return None
        now_mono = self.monotonic()
        stale = self._schedule is None or now_mono - self._schedule[0] > SCHEDULE_TTL_SECONDS
        if allow_fetch and stale and now_mono >= self._schedule_retry_after:
            try:
                self._schedule = (now_mono, self.client.schedule(favourite))
            except NHLApiError as exc:
                log.warning("Schedule fetch failed: %s", exc)
                self._record_error(f"schedule fetch: {exc}")
                self._schedule_retry_after = now_mono + SCHEDULE_TTL_SECONDS
        if self._schedule is None:
            return None
        now = self.clock()
        finished = {g.id for g in self.games if g.is_final}
        for game in self._schedule[1]:
            if game.id in finished or game.is_final:
                continue
            if game.is_live or game.start_utc > now:
                return game
        return None

    def _refresh_standings(self, *, allow_fetch: bool = True) -> list[StandingsRow] | None:
        """League standings, cached for ``STANDINGS_TTL_SECONDS`` like the schedule.

        ``allow_fetch=False`` answers from cache only, same reasoning as
        ``next_favourite_game`` -- for the status page (#61).
        """
        now_mono = self.monotonic()
        stale = self._standings is None or now_mono - self._standings[0] > STANDINGS_TTL_SECONDS
        if allow_fetch and stale and now_mono >= self._standings_retry_after:
            try:
                self._standings = (now_mono, self.client.standings())
            except NHLApiError as exc:
                log.warning("Standings fetch failed: %s", exc)
                self._record_error(f"standings fetch: {exc}")
                self._standings_retry_after = now_mono + STANDINGS_TTL_SECONDS
        if self._standings is None:
            return None
        return self._standings[1]

    def _standings_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's conference neighbourhood, or None if there's nothing to show.

        Suppressed entirely until the favourite has actually played a game
        this season (#40): the standings endpoint keeps serving last
        season's final table through the whole off-season rather than an
        empty result, and ``games_played`` is the only signal available to
        tell the two apart.
        """
        cfg = self.settings.scoreboard
        favourite = cfg.favourite_team
        if not cfg.show_standings or not favourite:
            return None
        rows = self._refresh_standings(allow_fetch=allow_fetch)
        if not rows:
            return None
        favourite_row = next((r for r in rows if r.abbrev == favourite), None)
        if favourite_row is None or favourite_row.games_played <= 0:
            return None
        window = standings_window(conference_standings(rows, favourite_row.conference), favourite)
        if not window:
            return None
        return Scene("standings", standings=tuple(window))

    def _show_standings_now(self) -> bool:
        """Alternate standings with the preview/countdown scene, on rotate_seconds' cadence."""
        period = max(self.settings.scoreboard.rotate_seconds, 1.0)
        return int(self.monotonic() // period) % 2 == 1

    def select_scene(self, *, allow_fetch: bool = True) -> Scene:
        """Decide what to show; the draw step only renders the answer.

        ``allow_fetch=False`` (the status page, #61) must never trigger a
        network call or mutate ``_schedule``/``_standings``/``last_error``
        from the status thread -- that would race the main loop into
        duplicate fetches, or block a "read-only" page on a slow NHL
        response.
        """
        scene = self._select_base_scene(allow_fetch=allow_fetch)
        return self._apply_goal_override(scene)

    def _select_base_scene(self, *, allow_fetch: bool = True) -> Scene:
        if self.last_success is None:
            return Scene("connecting")
        if self.is_stale():
            return Scene("no_data")
        if self.settings.scoreboard.rotation == "favourite":
            scene = self._favourite_scene(allow_fetch=allow_fetch)
            if scene is not None:
                return scene
        if self.games:
            return Scene("game", self.games[self.index])
        return Scene("clock" if self.settings.scoreboard.show_clock_when_idle else "no_games")

    def _apply_goal_override(self, scene: Scene) -> Scene:
        """Show the goal screen in place of the game it just happened in.

        Only ever replaces a "game" scene for the exact game the goal
        belongs to -- it never interrupts a countdown, preview or a
        different game mid-rotation to force attention to the favourite.
        """
        if scene.kind != "game" or self.last_goal is None:
            return scene
        goal_game_id, goal_time = self.last_goal
        if scene.game.id != goal_game_id:
            return scene
        if self.monotonic() - goal_time >= self.settings.scoreboard.goal_flash_seconds:
            return scene
        return Scene("goal", scene.game)

    def _favourite_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        cfg = self.settings.scoreboard
        today = self.favourite_game_today()
        if today is not None:
            if today.is_live:
                return Scene("game", today)
            if today.is_final:
                ended = self.ended_at.get(today.id)
                hold = timedelta(minutes=cfg.final_hold_minutes)
                if ended is not None and self.clock() - ended < hold:
                    return Scene("game", today)
        upcoming = (
            today
            if today is not None and today.is_pregame
            else self.next_favourite_game(allow_fetch=allow_fetch)
        )
        standings = self._standings_scene(allow_fetch=allow_fetch)
        if standings is not None and (upcoming is None or self._show_standings_now()):
            return standings
        if upcoming is None:
            return None
        if upcoming.seconds_until_start(self.clock()) <= cfg.countdown_hours * 3600:
            return Scene("countdown", upcoming)
        return Scene("preview", upcoming)

    def situation_targets(self) -> list[Game]:
        """Live games worth a second request: the favourite's and the on-screen one.

        Everything else shows even strength; that is the trade for not
        hammering the landing endpoint once per live game every poll.
        """
        targets: list[Game] = []
        favourite = self.settings.scoreboard.favourite_team
        if favourite:
            targets += [g for g in self.games if g.is_live and g.involves(favourite)]
        if self.settings.scoreboard.rotation == "all" and self.games:
            current = self.games[self.index]
            if current.is_live and current not in targets:
                targets.append(current)
        return targets

    def refresh_situations(self) -> None:
        now = self.monotonic()
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
        return (self.monotonic() - self.last_success) > STALE_AFTER_SECONDS

    # -- status page (#48) ------------------------------------------------

    def status_snapshot(self) -> dict[str, str]:
        """Everything the status page shows -- state already sitting in memory.

        Called from the status server's own request thread (#61): must
        never trigger a network fetch or mutate shared state concurrently
        with the main loop, hence ``allow_fetch=False`` -- a slow NHL
        response must not block a "read-only" status page, and the two
        threads must not race into duplicate fetches.
        """
        scene = self.select_scene(allow_fetch=False)
        cfg = self.settings.scoreboard
        return {
            "scene": scene.kind,
            "current game": self._scene_game_label(scene),
            "favourite team": cfg.favourite_team or "(none)",
            "rotation": cfg.rotation,
            "last successful poll": self._format_time(self.last_success_at),
            "last error": self.last_error or "(none)",
            "last error at": self._format_time(self.last_error_at) if self.last_error_at else "",
        }

    @staticmethod
    def _scene_game_label(scene: Scene) -> str:
        if scene.game is None:
            return ""
        return f"{scene.game.away.abbrev} @ {scene.game.home.abbrev}"

    def _format_time(self, value: datetime | None) -> str:
        if value is None:
            return "never"
        return value.astimezone(self.tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    def draw(self) -> None:
        if self._night_mode_active() and self.settings.night_mode.dim_brightness == 0:
            # Blank outright: brightness 0 alone isn't guaranteed dark on
            # every backend, and there's no point rendering a scene nobody
            # can see.
            self.canvas.Clear()
            self.canvas = self.matrix.SwapOnVSync(self.canvas)
            return
        scene = self.select_scene()
        r = self.renderer
        if scene.kind == "game":
            r.draw_game(self.canvas, self.with_situation(scene.game))
        elif scene.kind == "goal":
            r.draw_goal(self.canvas, scene.game)
        elif scene.kind == "countdown":
            r.draw_countdown(self.canvas, scene.game, self.clock())
        elif scene.kind == "preview":
            r.draw_preview(self.canvas, scene.game, self.clock())
        elif scene.kind == "standings":
            r.draw_standings(self.canvas, scene.standings, self.settings.scoreboard.favourite_team)
        elif scene.kind == "no_data":
            r.draw_message(self.canvas, "NO DATA", "CHECK NETWORK")
        elif scene.kind == "connecting":
            r.draw_message(self.canvas, "NHL", "CONNECTING")
        elif scene.kind == "clock":
            r.draw_clock(self.canvas, self.clock())
        else:
            r.draw_message(self.canvas, "NO GAMES")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
