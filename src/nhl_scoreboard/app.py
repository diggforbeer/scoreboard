"""The scoreboard run loop."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import signal
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType

import qrcode

from .admin_server import AdminServer
from .audio import GoalHornPlayer
from .brightness import lux_to_brightness
from .button import Button
from .config import DEFAULT_CONFIG_PATHS, RotationEntry, Settings, resolve_timezone
from .display.fonts import FontSet
from .display.logos import LogoLibrary
from .display.matrix import Backend, create_matrix, load_backend
from .display.renderer import Renderer
from .light_sensor import LightSensor
from .nhl.api import NHLApiError, NHLClient
from .nhl.models import (
    Game,
    GoalEvent,
    SeasonSeriesRecord,
    Situation,
    StandingsRow,
    Star,
    conference_standings,
    standings_window,
)
from .setup_server import SetupServer
from .updater import installed_version
from .wifi_join import WifiJoinAttempt

log = logging.getLogger(__name__)

#: How long stale data stays on the board before we admit we are offline.
STALE_AFTER_SECONDS = 15 * 60
FRAME_INTERVAL = 0.5
#: The favourite's season schedule changes rarely; this is plenty.
SCHEDULE_TTL_SECONDS = 60 * 60
#: Standings don't change intra-day except right after games finish.
STANDINGS_TTL_SECONDS = 60 * 60
#: The upcoming game's head-to-head tally (#157) only moves when another
#: meeting between the same two teams finishes -- days or weeks apart.
SEASON_SERIES_TTL_SECONDS = 60 * 60
#: How much a new lux reading moves the smoothed value, 0-1. Low on purpose:
#: this is what keeps a cloud passing over a window, or a hand briefly
#: covering the sensor, from visibly flickering the panel.
BRIGHTNESS_SMOOTHING = 0.3
#: How long each scene stays up in ``--demo`` (#47).
DEMO_SCENE_SECONDS = 4.0
#: Written by nhl-scoreboard-setup-ap while the board's own first-boot WiFi
#: AP is up (#131 follow-up); its mere presence means the ap_setup scene
#: overrides everything else, so a phone that can only reach the board over
#: that AP always sees how to join it. /run, matching the script's own
#: choice -- never survives a reboot stale.
AP_SETUP_STATE_PATH = Path("/run/nhl-scoreboard-setup-ap-state.json")
#: Written by nhl-scoreboard-setup-ap's pre-AP-mode scan (#132) -- a JSON
#: array of nearby SSIDs, cached from a snapshot taken moments before the AP
#: came up (this chip can't scan while its own AP is active). Read by the
#: setup page to render its network picker; the page always offers a plain
#: text field alongside it too, since that snapshot can miss a network.
AP_SCAN_STATE_PATH = Path("/run/nhl-scoreboard-setup-ap-networks.json")
#: Written by the setup page (#132) when someone submits a network choice --
#: the hand-off point for #133's still-to-be-built join flow to read from.
#: This app only ever writes it; it never touches iwd/iwctl itself.
AP_SUBMISSION_STATE_PATH = Path("/run/nhl-scoreboard-setup-submission.json")
#: Written by WifiJoinAttempt (#133) while/after acting on a submission --
#: "attempting"/"connected"/"failed" -- and read by _wifi_join_scene() to
#: show it on the panel, the feedback channel #133 decided on since the AP
#: teardown needed to attempt the join kills the phone's own connection to
#: whatever HTTP request submitted it. /run, same non-surviving-a-reboot
#: convention as every other AP-setup-mode state file.
WIFI_JOIN_OUTCOME_PATH = Path("/run/nhl-scoreboard-wifi-join-state.json")
#: Characters the de-facto WIFI: QR-code format requires backslash-escaped
#: inside SSID/password fields -- unescaped, any of these would end the
#: field early or corrupt the payload for a strict parser.
_QR_SPECIAL_CHARS = re.compile(r'([\\;,:"])')


def _qr_escape(value: str) -> str:
    return _QR_SPECIAL_CHARS.sub(r"\\\1", value)


@dataclass(frozen=True, slots=True)
class Scene:
    """What the board should show right now.

    ``kind`` is one of ``game`` (live or final scoreboard), ``goal``,
    ``goal_detail``, ``three_stars``, ``countdown``, ``preview``, ``standings``, ``matchup``,
    ``clock``, ``no_games``, ``connecting``, ``no_data``, ``ap_setup``, ``wifi_join``.
    """

    kind: str
    game: Game | None = None
    standings: tuple[StandingsRow, ...] | None = None
    #: Set only for ``matchup`` (#157) -- oriented to ``game``'s own
    #: away/home sides, as the API returns it.
    season_series: SeasonSeriesRecord | None = None
    #: Set only for ``goal_detail`` -- who scored, and their/their
    #: assisters' season totals (#122).
    goal_event: GoalEvent | None = None
    #: Set only for ``three_stars`` -- the NHL's three stars of a finished
    #: favourite game, ranked, per-game stats (#156).
    stars: tuple[Star, ...] | None = None
    #: Set only for ``ap_setup`` (#131 follow-up) -- the board's own
    #: first-boot WiFi AP, so a phone can join and finish setup. ``None``
    #: password means the AP came up open, not WPA2-protected.
    ap_ssid: str | None = None
    ap_password: str | None = None
    #: Precomputed QR module grid (row-major, True = dark module), or
    #: ``None`` when the payload didn't fit any QR version, or `qrcode`
    #: itself failed for some other reason -- the scene still shows
    #: SSID/password as text either way, same graceful-degradation
    #: precedent as LightSensor/resolve_timezone elsewhere in this app.
    ap_qr_matrix: tuple[tuple[bool, ...], ...] | None = None
    #: Set only for ``wifi_join`` (#133) -- "attempting"/"connected"/"failed",
    #: and the SSID that outcome is about.
    wifi_join_status: str | None = None
    wifi_join_ssid: str | None = None


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
        admin_server: AdminServer | None = None,
        button: Button | None = None,
        sleep: Callable[[float], None] | None = None,
        ap_setup_state_path: Path | None = None,
        ap_scan_state_path: Path | None = None,
        ap_submission_state_path: Path | None = None,
        wifi_join: WifiJoinAttempt | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.ap_setup_state_path = ap_setup_state_path or AP_SETUP_STATE_PATH
        self.ap_scan_state_path = ap_scan_state_path or AP_SCAN_STATE_PATH
        self.ap_submission_state_path = ap_submission_state_path or AP_SUBMISSION_STATE_PATH
        #: Acts on a submission (#133): tears down the AP, calls
        #: nhl_scoreboard.wifi's shared join/rollback path, reports the
        #: outcome to the panel. A full object, not just a path, since
        #: tests need to substitute the whole thing (real subprocess/thread
        #: use), not just where its state files live.
        self.wifi_join = wifi_join or WifiJoinAttempt(
            config_path=settings.source_path or DEFAULT_CONFIG_PATHS[0],
            connect_timeout=settings.wifi.connect_timeout_seconds,
            submission_path=self.ap_submission_state_path,
            outcome_path=WIFI_JOIN_OUTCOME_PATH,
        )
        #: The WiFi setup page (#132) -- only running while nhl-scoreboard-
        #: setup-ap's state file says the AP is up, kept in step by
        #: _sync_setup_server(). None means "not currently running", whether
        #: because the AP is down or wifi_setup.enabled is false.
        self.setup_server: SetupServer | None = None
        #: The (enabled, port) _sync_setup_server last built setup_server
        #: from, so a config reload's port change is noticed even if the AP
        #: state file's presence hasn't changed. None means no server wanted.
        self._setup_server_config: tuple[bool, int] | None = None
        #: (ssid, password) -> precomputed QR matrix, so a QR isn't
        #: recomputed every FRAME_INTERVAL for the whole time the AP stays
        #: up -- it only changes if the AP's own SSID/password ever would.
        self._ap_qr_cache: (
            tuple[tuple[str, str | None], tuple[tuple[bool, ...], ...] | None] | None
        ) = None
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
        # Same lazy-open rule as the light sensor: no GPIO claimed, and no
        # gpiozero import attempted, unless the button is actually enabled.
        if button is not None:
            self.button = button
        elif settings.button.enabled:
            self.button = Button.open(
                pin=settings.button.pin, hold_seconds=settings.button.hold_seconds
            )
        else:
            self.button = None
        #: monotonic time the goal horn stays silent until, after a short
        #: button press (#50). None means not muted.
        self._horn_muted_until: float | None = None
        self._applied_brightness = settings.panel.brightness
        self.tz = resolve_timezone(settings.scoreboard.timezone)
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
        if admin_server is not None:
            self.admin_server = admin_server
        elif settings.status.enabled:
            self.admin_server = AdminServer(
                config_path=str(settings.source_path or DEFAULT_CONFIG_PATHS[0]),
                port=settings.status.port,
                snapshot=self.status_snapshot,
            )
        else:
            self.admin_server = None
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
        #: upcoming game id -> (fetched at, its head-to-head tally), for the
        #: opt-in matchup screen (#157). Only the current upcoming game's
        #: entry is ever kept; it's dropped once a different game is next.
        self._season_series: dict[int, tuple[float, SeasonSeriesRecord | None]] = {}
        #: upcoming game id -> retry-not-before, same backoff as
        #: _standings_retry_after but per game, so a new upcoming game isn't
        #: stuck behind the previous one's failure.
        self._season_series_retry_after: dict[int, float] = {}
        #: game id -> the favourite's own score last seen in that game, so a
        #: goal can be detected as an increase. Set on first sighting without
        #: firing, so a game already 3-1 at startup does not fire a goal.
        self._known_favourite_score: dict[int, int] = {}
        #: (game id, monotonic time) of the most recent favourite goal, for
        #: how long the goal scene stays up.
        self.last_goal: tuple[int, float] | None = None
        #: game id -> (fetched at, favourite's own GoalEvents seen so far in
        #: that game's scoring array). Favourite-only, same scoping
        #: precedent as goal detection and the PP indicator (#122).
        self._goal_events: dict[int, tuple[float, tuple[GoalEvent, ...]]] = {}
        #: game id -> how many of the favourite's goal_events already had a
        #: goal_detail screen shown, so a late scorer/assist correction never
        #: re-fires for the same goal. Set to the full count on first
        #: sighting without firing, same precedent as _known_favourite_score.
        self._shown_goal_events: dict[int, int] = {}
        #: (game id, monotonic time, event) of the most recent goal_detail
        #: screen, for how long it stays up.
        self._goal_detail: tuple[int, float, GoalEvent] | None = None
        #: game id -> monotonic time of the last three-stars fetch attempt,
        #: for the favourite's games we watched go final and haven't got a
        #: non-empty threeStars for yet (#156). None = not tried yet.
        self._three_stars_pending: dict[int, float | None] = {}
        #: Game ids whose three-stars screen has already fired -- never again
        #: for the same game, independent of whether pending still has it.
        self._three_stars_shown: set[int] = set()
        #: (game id, monotonic time, stars) of the three-stars screen, for
        #: how long it stays up.
        self._three_stars: tuple[int, float, tuple[Star, ...]] | None = None
        #: The configured logo library, held by run_demo() while it toggles
        #: renderer.logos between it and None for the text layout.
        self._demo_real_logos: LogoLibrary | None = logos
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
        if self.admin_server is not None:
            self.admin_server.start()
        self.renderer.draw_message(self.canvas, "NHL", "CONNECTING")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

        next_poll = 0.0
        next_rotate = 0.0
        next_brightness = 0.0
        while self._running:
            now = self.monotonic()
            self.reload_config_if_changed()
            self.handle_button()
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
            self.refresh_goal_details()
            self.refresh_three_stars()
            self._sync_setup_server()
            self.wifi_join.poll()
            self.wifi_join.expire_outcome_if_stale()
            self.draw()
            self.sleep(FRAME_INTERVAL)
        self.shutdown()

    def run_demo(self) -> None:
        """Loop every scene with synthetic data until stopped (#47).

        Deliberately bypasses the real state machine: no ``refresh()``,
        ``select_scene()``, situation/brightness sampling or config reload,
        and no NHL client call at all -- coercing live data into every state
        on demand isn't possible, and a bench board may have no network.
        Goals drawn here never reach ``_on_goal()`` (only ``refresh()``'s
        ``_detect_goals()`` does), so the horn stays silent.
        """
        # Imported here: demo builds Scene objects, so a top-level import
        # would be circular.
        from .demo import demo_steps

        self._running = True
        self._demo_real_logos = self.renderer.logos
        ticks_per_scene = max(1, round(DEMO_SCENE_SECONDS / FRAME_INTERVAL))
        while self._running:
            # Rebuilt each pass so the preview/countdown stay relative to now.
            steps = demo_steps(self.settings.scoreboard.favourite_team, self.clock())
            for step in steps:
                if not self._running:
                    break
                self._set_demo_logos(step.use_logos)
                self.draw_scene(step.scene)
                for _ in range(ticks_per_scene):
                    if not self._running:
                        break
                    self.sleep(FRAME_INTERVAL)
        self.renderer.logos = self._demo_real_logos
        self.shutdown()

    def _set_demo_logos(self, use_logos: bool) -> None:
        """Show the text fallback layout on demand, whatever the board has configured.

        With ``show_logos`` off there was never a library, so logo steps
        simply draw as text too.
        """
        self.renderer.logos = self._demo_real_logos if use_logos else None

    def shutdown(self) -> None:
        try:
            if self.admin_server is not None:
                self.admin_server.stop()
            if self.setup_server is not None:
                self.setup_server.stop()
            if self.button is not None:
                self.button.close()
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
                self._queue_three_stars(game, watched=watched)
                log.debug(
                    "Game %s ended at %s (%s)",
                    game.id,
                    self.ended_at[game.id],
                    "observed" if watched else "estimated",
                )
        self._prune_game_state()
        if self.index >= len(self.games):
            self.index = 0
        log.debug("Refreshed: %d games", len(self.games))

    def _prune_game_state(self) -> None:
        """Drop bookkeeping for games no longer in today's slate.

        ``_seen_live``, ``ended_at``, ``_known_favourite_score`` and the
        goal-detail/three-stars bookkeeping are keyed by game id and
        otherwise never cleared, growing by one entry per game for as long
        as the process runs (#64). ``self.games`` is
        refreshed from the live schedule every poll, so any id no longer in
        it is done for today and safe to forget.
        """
        current_ids = {game.id for game in self.games}
        self._seen_live &= current_ids
        for game_id in list(self.ended_at):
            if game_id not in current_ids:
                del self.ended_at[game_id]
        for game_id in list(self._known_favourite_score):
            if game_id not in current_ids:
                del self._known_favourite_score[game_id]
        for game_id in list(self._goal_events):
            if game_id not in current_ids:
                del self._goal_events[game_id]
        for game_id in list(self._shown_goal_events):
            if game_id not in current_ids:
                del self._shown_goal_events[game_id]
        for game_id in list(self._three_stars_pending):
            if game_id not in current_ids:
                del self._three_stars_pending[game_id]
        self._three_stars_shown &= current_ids

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
        loop iteration; ``[audio]``, the logo library, the ambient light
        sensor (``panel.auto_brightness``), the admin server
        (``status.enabled``/``status.port``) and the physical button
        (``[button]``, #50) are built once from it instead, so those get
        rebuilt explicitly here (#62). A rebuilt admin server
        is only started if ``run()``'s loop is live (``self._running``):
        ``run()`` starts it exactly once before looping, so a reload outside
        that loop -- e.g. a test calling this directly -- builds it without
        binding a socket, just as ``__init__`` does. ``[panel]`` geometry
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
        """Apply a config reload's side effects, field by field.

        Deliberately explicit/per-field rather than one generic "something
        changed, re-fetch and rebuild everything" pass -- consistent with
        this project's usual anti-premature-abstraction stance, and a
        blanket invalidation would force unrelated work on every save
        (e.g. a schedule refetch or horn rebuild triggered by editing
        goal_flash_seconds). The real risk with this approach isn't that
        it doesn't scale, it's that a *new* piece of state cached off a
        setting (self._schedule/_standings/_season_series-shaped, or a
        rebuilt object like self.horn/renderer.logos) can be added without
        anyone remembering to hook its invalidation in here -- exactly how
        favourite_team_changed's _schedule fix below was missing until a
        live bug (#178's admin-page work) surfaced it. When adding a new
        cache or rebuilt-from-settings object anywhere in this class,
        check here first: does a relevant field change need to reset or
        rebuild it, the same way audio_changed/logos_changed/
        favourite_team_changed/etc. do below?
        """
        old = self.settings
        audio_changed = dataclasses.astuple(old.audio) != dataclasses.astuple(new_settings.audio)
        logos_changed = (
            old.scoreboard.show_logos != new_settings.scoreboard.show_logos
            or old.scoreboard.logo_variant != new_settings.scoreboard.logo_variant
        )
        timezone_changed = old.scoreboard.timezone != new_settings.scoreboard.timezone
        favourite_team_changed = (
            old.scoreboard.favourite_team != new_settings.scoreboard.favourite_team
        )
        auto_brightness_changed = old.panel.auto_brightness != new_settings.panel.auto_brightness
        status_changed = (old.status.enabled, old.status.port) != (
            new_settings.status.enabled,
            new_settings.status.port,
        )
        # mute_minutes is read fresh on every press, so it alone needs no rebuild.
        button_changed = (old.button.enabled, old.button.pin, old.button.hold_seconds) != (
            new_settings.button.enabled,
            new_settings.button.pin,
            new_settings.button.hold_seconds,
        )

        self.settings = new_settings

        if timezone_changed:
            self.tz = resolve_timezone(new_settings.scoreboard.timezone, fallback=self.tz)
            self.renderer.tz = self.tz

        if favourite_team_changed:
            # next_favourite_game()'s _schedule cache is a single season
            # schedule for whichever team it was last fetched for, kept
            # "fresh" purely by SCHEDULE_TTL_SECONDS elapsing -- nothing
            # about that staleness check knows *which* team the cached
            # games belong to. Left alone, a favourite-team switch keeps
            # showing the *previous* team's next game (not a stale version
            # of the new one -- a different matchup entirely) for up to an
            # hour, until the TTL happens to expire on its own. Confirmed
            # live (#178's admin-page work): this is exactly why the
            # matchup/season-series screen (#157) kept showing the old
            # opponent after a favourite switch -- it's fed straight from
            # next_favourite_game()'s return value. Only relevant when
            # today's game doesn't already answer it: favourite_game_
            # today() reads self.games (today's full slate, already
            # fetched for every team) fresh on every call, so an immediate
            # favourite with a game today was never affected by this --
            # only the countdown/preview/matchup fallback to the season
            # schedule was.
            self._schedule = None
            self._schedule_retry_after = 0.0

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

        if auto_brightness_changed:
            # Same lazy probe as __init__: only touch the I2C bus when the
            # feature is on. Turning it off just drops the sensor, which is
            # what refresh_brightness() already treats as "feature off".
            self.light_sensor = LightSensor.open() if new_settings.panel.auto_brightness else None

        if status_changed:
            # AdminServer's port is fixed at construction, so any change
            # means stop-and-rebuild rather than reconfigure in place.
            if self.admin_server is not None:
                self.admin_server.stop()
            if new_settings.status.enabled:
                self.admin_server = AdminServer(
                    config_path=str(new_settings.source_path or DEFAULT_CONFIG_PATHS[0]),
                    port=new_settings.status.port,
                    snapshot=self.status_snapshot,
                )
                # run() starts the server once, before its loop; a rebuild
                # inside the loop has to start itself. Outside the loop,
                # construct only -- same as __init__ -- so it's run() that
                # binds the socket, not whoever happened to reload.
                if self._running:
                    self.admin_server.start()
            else:
                self.admin_server = None

        if button_changed:
            # gpiozero fixes pin and hold_time at construction; close first
            # so the rebuilt one can reclaim the same pin.
            if self.button is not None:
                self.button.close()
            self.button = (
                Button.open(
                    pin=new_settings.button.pin, hold_seconds=new_settings.button.hold_seconds
                )
                if new_settings.button.enabled
                else None
            )

        # wifi.connect_timeout_seconds: plain attribute update, no
        # stop/rebuild needed the way AdminServer's fixed-at-construction
        # port does -- WifiJoinAttempt reads it fresh on its next attempt,
        # and there's nothing live to restart if one isn't in progress.
        self.wifi_join.connect_timeout = new_settings.wifi.connect_timeout_seconds

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
        behaves as "all" -- a normal combination (no favourite_team
        configured, with night mode on), not a misconfiguration worth a
        warning.
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
        if self._horn_muted():
            log.info("Goal horn muted by button press; not playing")
            return
        self.horn.play(favourite)

    def _horn_muted(self) -> bool:
        return self._horn_muted_until is not None and self.monotonic() < self._horn_muted_until

    # -- physical button (#50) ---------------------------------------------

    def handle_button(self) -> None:
        """Act on any button presses since the last loop iteration.

        The only place button presses turn into state changes: the button's
        own gpiozero callbacks run on background threads and just set flags
        (see button.py), so every mutation here happens on run()'s thread.
        """
        if self.button is None:
            return
        if self.button.consume_short_press():
            minutes = self.settings.button.mute_minutes
            self._horn_muted_until = self.monotonic() + minutes * 60
            log.info("Button: goal horn muted for %g minutes", minutes)
        if self.button.consume_long_press():
            log.info("Button: forcing next rotation")
            self.advance()

    # -- goal detail (#122 phase 2) ---------------------------------------

    def refresh_goal_details(self) -> None:
        """Poll the favourite's live game for scorer/assist detail, phase 2 of #122.

        Deliberately decoupled from ``_detect_goals``: the score-increase
        that drives the ``goal`` scene comes from ``score/now`` and can tick
        up before ``gamecenter/{id}/landing``'s ``summary.scoring`` has
        caught up with that specific goal's entry. Rather than make the
        ``goal`` scene wait on data that might not be ready, this polls the
        favourite's own scoring array independently and fires once a new
        entry actually shows up -- possibly well after the ``goal`` scene's
        own flash has already ended.

        Scoped to the favourite's own live game only, same precedent as
        goal detection and the PP indicator. A separate request to the same
        landing URL ``refresh_situations()`` already polls (not a new
        endpoint), on the same ``live_poll_seconds`` cadence, skipped during
        intermission for the same reason situation is.
        """
        favourite = self.settings.scoreboard.favourite_team
        if not favourite:
            return
        game = next((g for g in self.games if g.is_live and g.involves(favourite)), None)
        if game is None:
            return
        now = self.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        fetched_at, events = self._goal_events.get(game.id, (None, ()))
        if fetched_at is not None and now - fetched_at < interval:
            return
        if game.in_intermission:
            self._goal_events[game.id] = (now, events)
            return
        try:
            all_events = self.client.goal_scoring(game.id)
        except NHLApiError as exc:
            log.debug("Goal scoring fetch for %s failed: %s", game.id, exc)
            all_events = events
        favourite_events = tuple(e for e in all_events if e.team_abbrev == favourite)
        self._goal_events[game.id] = (now, favourite_events)
        self._detect_goal_detail(game.id, favourite_events)

    def _detect_goal_detail(self, game_id: int, events: tuple[GoalEvent, ...]) -> None:
        """The favourite's scoring array grew by one entry: show it, once.

        Tracks a count per game rather than matching goals by identity --
        the simplest approach that still can't refire for the same goal on
        a later scorer/assist correction (the array only ever grows).
        Baseline on first sighting without firing, same precedent as
        ``_detect_goals``, so a game already several goals in at startup
        doesn't dump a backlog of detail screens.
        """
        previous = self._shown_goal_events.get(game_id)
        if previous is None:
            self._shown_goal_events[game_id] = len(events)
            return
        if len(events) > previous:
            self._shown_goal_events[game_id] = previous + 1
            self._goal_detail = (game_id, self.monotonic(), events[previous])

    # -- three stars (#156) -------------------------------------------------

    def _queue_three_stars(self, game: Game, *, watched: bool) -> None:
        """The favourite's game just went final: start polling for its three stars.

        Called from ``refresh()``'s existing first-time-final branch (the
        same one that records ``ended_at``), not a detector of its own.
        Only for a game we actually watched go live -- one already final
        at startup is a first sighting, and records nothing, same "baseline
        without firing" precedent as goal detection, so a restart mid-hold
        doesn't show the screen a second time. Favourite-only, same scoping
        as goal detection and the PP indicator.
        """
        favourite = self.settings.scoreboard.favourite_team
        if not watched or not favourite or not game.involves(favourite):
            return
        if game.id not in self._three_stars_shown:
            self._three_stars_pending.setdefault(game.id, None)

    def refresh_three_stars(self) -> None:
        """Fetch the three stars for a just-final favourite game, retrying until named.

        Decoupled from the final transition itself for the same reason
        ``refresh_goal_details`` is decoupled from the score increase:
        ``score/now`` can flip a game to FINAL/OFF before ``landing`` has
        its ``threeStars`` populated, so an empty result is retried every
        ``live_poll_seconds`` rather than given up on. Stops once the stars
        arrive, once the game leaves today's slate (pruned with the rest of
        the per-game state), or once its final hold is over -- nothing would
        show the screen after that anyway.
        """
        now = self.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        hold = timedelta(minutes=self.settings.scoreboard.final_hold_minutes)
        for game_id, tried_at in list(self._three_stars_pending.items()):
            ended = self.ended_at.get(game_id)
            if game_id in self._three_stars_shown or (
                ended is not None and self.clock() - ended >= hold
            ):
                del self._three_stars_pending[game_id]
                continue
            if tried_at is not None and now - tried_at < interval:
                continue
            self._three_stars_pending[game_id] = now
            try:
                stars = self.client.three_stars(game_id)
            except NHLApiError as exc:
                log.debug("Three stars fetch for %s failed: %s", game_id, exc)
                continue
            if not stars:
                continue
            del self._three_stars_pending[game_id]
            self._three_stars_shown.add(game_id)
            self._three_stars = (game_id, now, stars)

    def _three_stars_override(self, game_id: int) -> Scene | None:
        if self._three_stars is None:
            return None
        stars_game_id, shown_at, stars = self._three_stars
        if stars_game_id != game_id:
            return None
        if self.monotonic() - shown_at >= self.settings.scoreboard.three_stars_seconds:
            return None
        game = next((g for g in self.games if g.id == game_id), None)
        if game is None:
            return None
        return Scene("three_stars", game, stars=stars)

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

    def _refresh_season_series(
        self, game_id: int, *, allow_fetch: bool = True
    ) -> SeasonSeriesRecord | None:
        """The upcoming game's head-to-head tally, cached ``SEASON_SERIES_TTL_SECONDS``.

        Same TTL + backoff-on-failure shape as ``_refresh_standings``, keyed
        by game id since the answer is specific to one matchup. A failed
        refresh keeps serving whatever was cached before it.
        """
        now_mono = self.monotonic()
        entry = self._season_series.get(game_id)
        stale = entry is None or now_mono - entry[0] > SEASON_SERIES_TTL_SECONDS
        retry_after = self._season_series_retry_after.get(game_id, 0.0)
        if allow_fetch and stale and now_mono >= retry_after:
            # Only ever the one upcoming matchup worth remembering.
            self._season_series = {k: v for k, v in self._season_series.items() if k == game_id}
            self._season_series_retry_after = {}
            try:
                entry = (now_mono, self.client.season_series(game_id))
                self._season_series[game_id] = entry
            except NHLApiError as exc:
                log.warning("Season series fetch for %s failed: %s", game_id, exc)
                self._record_error(f"season series fetch: {exc}")
                self._season_series_retry_after[game_id] = now_mono + SEASON_SERIES_TTL_SECONDS
        return entry[1] if entry is not None else None

    def _matchup_scene(self, upcoming: Game | None, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's head-to-head record against their next opponent (#157).

        None -- skipped for this rotation pass, never drawn blank -- with no
        upcoming game, before the fetch has succeeded, or when the API had
        no usable tally. A ``0-0`` tally (preseason, or no meeting finished
        yet) is a real answer and does render.
        """
        if upcoming is None:
            return None
        record = self._refresh_season_series(upcoming.id, allow_fetch=allow_fetch)
        if record is None:
            return None
        return Scene("matchup", upcoming, season_series=record)

    def _countdown_or_preview(self, upcoming: Game) -> Scene:
        cfg = self.settings.scoreboard
        if upcoming.seconds_until_start(self.clock()) <= cfg.countdown_hours * 3600:
            return Scene("countdown", upcoming)
        return Scene("preview", upcoming)

    def _default_rotation(self) -> list[RotationEntry]:
        """The implicit rotation list, derived from the older discrete settings (#150).

        Used whenever ``[[rotation]]`` isn't present in the config file, so
        an upgraded board's idle rotation is unchanged until the owner
        opts into an explicit list. ``matchup`` (#157) is deliberately never
        here: it only appears when someone lists it in ``[[rotation]]``.
        """
        cfg = self.settings.scoreboard
        entries = [RotationEntry("countdown_preview", cfg.rotate_seconds)]
        if cfg.show_standings:
            entries.append(RotationEntry("standings", cfg.rotate_seconds))
        if cfg.show_clock_between_games:
            entries.append(RotationEntry("clock", cfg.rotate_seconds))
        return entries

    def _effective_rotation(self) -> list[RotationEntry]:
        return self.settings.rotation or self._default_rotation()

    def _rotation_screen_scene(
        self,
        screen: str,
        upcoming: Game | None,
        standings: Scene | None,
        *,
        allow_fetch: bool = True,
    ) -> Scene | None:
        if screen == "countdown_preview":
            return self._countdown_or_preview(upcoming) if upcoming is not None else None
        if screen == "standings":
            return standings
        if screen == "clock":
            return Scene("clock")
        if screen == "matchup":
            # Resolved here, not up front like standings, so a board without
            # "matchup" in its rotation never calls right-rail at all.
            return self._matchup_scene(upcoming, allow_fetch=allow_fetch)
        return None

    def _rotate_idle_scenes(
        self, upcoming: Game | None, standings: Scene | None, *, allow_fetch: bool = True
    ) -> Scene | None:
        """Cycle the configured (or derived-default) rotation list, each entry its own dwell time.

        A configured entry with nothing to show right now -- ``standings``
        before the favourite's season has started, or ``countdown_preview``
        with no upcoming game at all -- is skipped for this pass rather than
        shown blank (#150 decision 2); the remaining entries keep cycling
        normally. ``None`` only when every entry is currently unavailable.
        """
        slots = [
            (scene, entry.seconds)
            for entry in self._effective_rotation()
            if (
                scene := self._rotation_screen_scene(
                    entry.screen, upcoming, standings, allow_fetch=allow_fetch
                )
            )
            is not None
        ]
        if not slots:
            return None
        if len(slots) == 1:
            return slots[0][0]
        total = sum(seconds for _, seconds in slots)
        position = self.monotonic() % total
        elapsed = 0.0
        for scene, seconds in slots:
            elapsed += seconds
            if position < elapsed:
                return scene
        return slots[-1][0]

    def select_scene(self, *, allow_fetch: bool = True) -> Scene:
        """Decide what to show; the draw step only renders the answer.

        ``allow_fetch=False`` (the status page, #61) must never trigger a
        network call or mutate ``_schedule``/``_standings``/``last_error``
        from the status thread -- that would race the main loop into
        duplicate fetches, or block a "read-only" page on a slow NHL
        response.

        wifi_join wins over even ap_setup (#133): while a join attempt's
        outcome is still showing, that's more current than "here's how to
        join" -- notably during a failed attempt's retry window, when
        nhl-scoreboard-setup-ap has already brought the AP (and its own
        ap_setup state file) back up underneath the "Failed..." message
        that's still counting down.

        ap_setup otherwise wins over everything else, unconditionally
        (#131 follow-up): if the board's own WiFi AP is up, a phone joining
        it is the only way to reach the board at all -- there is no point
        showing a stale game, a goal flash, or "NO DATA" to nobody.
        """
        join_scene = self._wifi_join_scene()
        if join_scene is not None:
            return join_scene
        ap_scene = self._ap_setup_scene()
        if ap_scene is not None:
            return ap_scene
        scene = self._select_base_scene(allow_fetch=allow_fetch)
        return self._apply_goal_override(scene)

    def _wifi_join_scene(self) -> Scene | None:
        try:
            raw = self.wifi_join.outcome_path.read_text()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("Could not read WiFi join outcome file: %s", exc)
            return None
        try:
            data = json.loads(raw)
            status = str(data["status"])
            ssid = str(data["ssid"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("Malformed WiFi join outcome file: %s", exc)
            return None
        return Scene("wifi_join", wifi_join_status=status, wifi_join_ssid=ssid)

    def _ap_setup_scene(self) -> Scene | None:
        try:
            raw = self.ap_setup_state_path.read_text()
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.warning("Could not read AP setup state file: %s", exc)
            return None
        try:
            data = json.loads(raw)
            ssid = str(data["ssid"])
            password = data["password"]
            password = str(password) if password is not None else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("Malformed AP setup state file: %s", exc)
            return None
        return Scene(
            "ap_setup",
            ap_ssid=ssid,
            ap_password=password,
            ap_qr_matrix=self._ap_setup_qr_matrix(ssid, password),
        )

    def _ap_setup_qr_matrix(
        self, ssid: str, password: str | None
    ) -> tuple[tuple[bool, ...], ...] | None:
        cache_key = (ssid, password)
        if self._ap_qr_cache is not None and self._ap_qr_cache[0] == cache_key:
            return self._ap_qr_cache[1]
        if password is None:
            payload = f"WIFI:T:nopass;S:{_qr_escape(ssid)};;"
        else:
            payload = f"WIFI:T:WPA;S:{_qr_escape(ssid)};P:{_qr_escape(password)};;"
        try:
            # border=0 explicitly: verified live that get_matrix() otherwise
            # includes the library's own default 4-module quiet zone in its
            # output (29x29 modules for this payload becomes 37x37 with it)
            # -- silently exceeding the panel's 32px height and skipping the
            # QR draw entirely, with nothing wrong to log because nothing
            # raised. Confirming the fit still happens in the renderer
            # regardless; this just stops the default border from being the
            # reason it doesn't.
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=0)
            qr.add_data(payload)
            qr.make(fit=True)
            matrix = tuple(tuple(bool(v) for v in row) for row in qr.get_matrix())
        except Exception as exc:
            log.warning("Could not build AP setup QR code: %s", exc)
            matrix = None
        self._ap_qr_cache = (cache_key, matrix)
        return matrix

    # -- WiFi setup page (#132) --------------------------------------------

    def _sync_setup_server(self) -> None:
        """Start/stop the WiFi setup HTTP server in step with the AP state file.

        Only called from run()'s own loop -- status_snapshot() (the admin
        server's own thread) only ever calls select_scene(allow_fetch=False),
        never this, so there is no cross-thread race to start or stop the
        same socket. Only needs "is the AP state file there", the same
        signal _ap_setup_scene keys off of, not its contents. Also reacts to
        a live config reload (wifi_setup.enabled/port) even when the AP
        state file's presence hasn't changed, the same way _apply_reloaded_
        settings handles the admin server's own port change.
        """
        cfg = self.settings.wifi_setup
        wanted = cfg.enabled and self.ap_setup_state_path.exists()
        desired = (cfg.enabled, cfg.port) if wanted else None
        if desired == self._setup_server_config:
            return
        if self.setup_server is not None:
            self.setup_server.stop()
            self.setup_server = None
        self._setup_server_config = desired
        if desired is None:
            return
        self.setup_server = SetupServer(
            networks=self._cached_setup_networks,
            on_submit=self._on_setup_submission,
            port=cfg.port,
        )
        try:
            self.setup_server.start()
        except OSError as exc:
            log.warning("Could not start WiFi setup server: %s", exc)
            self.setup_server = None

    def _cached_setup_networks(self) -> list[str]:
        """The nearby-network snapshot nhl-scoreboard-setup-ap cached before AP mode came up."""
        try:
            raw = self.ap_scan_state_path.read_text()
        except OSError:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("Malformed AP scan state file: %s", exc)
            return []
        if not isinstance(data, list):
            return []
        return [str(item) for item in data]

    def _on_setup_submission(self, ssid: str, password: str | None) -> None:
        """Record a WiFi choice from the setup page for #133's join flow to pick up.

        This app never touches iwd/iwctl itself -- see setup_server.py's own
        module docstring for why actually joining the network is out of
        scope here. Written atomically (tmp + replace), same convention as
        Settings.save(), so a reader never sees a half-written file.
        """
        payload = json.dumps({"ssid": ssid, "password": password})
        tmp_path = self.ap_submission_state_path.with_name(
            self.ap_submission_state_path.name + ".tmp"
        )
        try:
            tmp_path.write_text(payload)
            tmp_path.replace(self.ap_submission_state_path)
        except OSError as exc:
            log.warning("Could not write WiFi setup submission: %s", exc)

    def _select_base_scene(self, *, allow_fetch: bool = True) -> Scene:
        if self.last_success is None:
            return Scene("connecting")
        if self.is_stale():
            return Scene("no_data")
        scene = self._favourite_scene(allow_fetch=allow_fetch)
        if scene is not None:
            return scene
        if self.games:
            return Scene("game", self.games[self.index])
        return Scene("clock" if self.settings.scoreboard.show_clock_when_idle else "no_games")

    def _apply_goal_override(self, scene: Scene) -> Scene:
        """Show the goal (or later, goal_detail) screen over the game it happened in.

        Only ever replaces a "game" scene for the exact game the goal
        belongs to -- it never interrupts a countdown, preview or a
        different game mid-rotation to force attention to the favourite.
        goal_detail wins when both are pending: it fires strictly after the
        goal scene's own score-increase trigger (see refresh_goal_details),
        so by the time it is ready there is no point re-showing the plainer
        "GOAL" + score flash for the same goal.

        three_stars (#156) is the last layer: it only arms once the game is
        final, so it's temporally disjoint from the other two in practice.
        If a late game-winner's flash does overlap it, the goal screens win
        and three_stars just loses that slice of its own window.
        """
        if scene.kind != "game":
            return scene
        detail = self._goal_detail_override(scene.game.id)
        if detail is not None:
            return detail
        if self.last_goal is not None:
            goal_game_id, goal_time = self.last_goal
            if (
                scene.game.id == goal_game_id
                and self.monotonic() - goal_time < self.settings.scoreboard.goal_flash_seconds
            ):
                return Scene("goal", scene.game)
        stars = self._three_stars_override(scene.game.id)
        return stars if stars is not None else scene

    def _goal_detail_override(self, game_id: int) -> Scene | None:
        if self._goal_detail is None:
            return None
        detail_game_id, detail_time, event = self._goal_detail
        if detail_game_id != game_id:
            return None
        if self.monotonic() - detail_time >= self.settings.scoreboard.goal_detail_seconds:
            return None
        game = next((g for g in self.games if g.id == game_id), None)
        if game is None:
            return None
        return Scene("goal_detail", game, goal_event=event)

    def _favourite_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        cfg = self.settings.scoreboard
        if not cfg.favourite_team:
            return None
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
        return self._rotate_idle_scenes(upcoming, standings, allow_fetch=allow_fetch)

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
        """Everything the admin page's status box shows -- state already
        sitting in memory.

        Called from the admin server's own thread (#61, #178 story 10):
        must never trigger a network fetch or mutate shared state
        concurrently with the main loop, hence ``allow_fetch=False`` -- a
        slow NHL response must not block a "read-only" status view, and
        the two threads must not race into duplicate fetches.
        """
        scene = self.select_scene(allow_fetch=False)
        cfg = self.settings.scoreboard
        return {
            "version": installed_version() or "unknown (factory image)",
            "scene": scene.kind,
            "current game": self._scene_game_label(scene),
            "favourite team": cfg.favourite_team or "(none)",
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
        self.draw_scene(self.select_scene())

    def draw_scene(self, scene: Scene) -> None:
        r = self.renderer
        if scene.kind == "game":
            r.draw_game(self.canvas, self.with_situation(scene.game))
        elif scene.kind == "goal":
            r.draw_goal(self.canvas, scene.game)
        elif scene.kind == "goal_detail":
            r.draw_goal_detail(self.canvas, scene.game, scene.goal_event)
        elif scene.kind == "three_stars":
            r.draw_three_stars(self.canvas, scene.game, scene.stars)
        elif scene.kind == "countdown":
            r.draw_countdown(self.canvas, scene.game, self.clock())
        elif scene.kind == "preview":
            r.draw_preview(self.canvas, scene.game, self.clock())
        elif scene.kind == "standings":
            r.draw_standings(self.canvas, scene.standings, self.settings.scoreboard.favourite_team)
        elif scene.kind == "matchup":
            r.draw_matchup(self.canvas, scene.game, scene.season_series)
        elif scene.kind == "no_data":
            r.draw_message(self.canvas, "NO DATA", "CHECK NETWORK")
        elif scene.kind == "connecting":
            r.draw_message(self.canvas, "NHL", "CONNECTING")
        elif scene.kind == "clock":
            r.draw_clock(self.canvas, self.clock(), self.settings.scoreboard.favourite_team)
        elif scene.kind == "ap_setup":
            r.draw_ap_setup(self.canvas, scene.ap_ssid, scene.ap_password, scene.ap_qr_matrix)
        elif scene.kind == "wifi_join":
            r.draw_wifi_join(self.canvas, scene.wifi_join_status, scene.wifi_join_ssid)
        else:
            r.draw_message(self.canvas, "NO GAMES")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
