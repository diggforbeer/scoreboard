"""The scoreboard run loop."""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import random
import re
import signal
import subprocess
import threading
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Any

import qrcode

from . import april_fools, blowout
from .admin_server import AdminServer
from .audio import GoalHornPlayer
from .brightness import lux_to_brightness
from .button import Button
from .config import (
    DEFAULT_CONFIG_PATHS,
    DEFAULT_FOOTBALL_ROTATION,
    PANEL_HARDWARE_MAPPING_CHOICES,
    ConfigWriteError,
    RotationEntry,
    Settings,
    TeamEntry,
    next_hardware_mapping,
    resolve_timezone,
    screen_sport,
)
from .delay import DelayQueue
from .display import goal_light
from .display import penalty as penalty_screen
from .display.fonts import FontSet
from .display.holiday import (
    HOLIDAYS,
    Holiday,
    HolidayOverlay,
    active_holiday,
    christmas_countdown,
    thanksgiving_countdown,
    tree_egg,
    turkey_egg,
    use_sport,
)
from .display.logos import LogoLibrary, LogoSet
from .display.matrix import Backend, create_matrix, load_backend
from .display.mirror import Mirror, MirrorCanvas, MirrorGraphics, unwrap
from .display.renderer import Renderer
from .fetcher import SLOW_FETCH_SECONDS, InlineFetcher, ThreadedFetcher
from .football.events import Event as FbEvent
from .football.events import Touchdown
from .football.mode import FootballMode
from .football.models import FbGame, Play
from .football.people import Person
from .hockey.api import HockeyApiError, HockeyClient
from .hockey.models import (
    DIVISION_SPOTS,
    WILDCARD_SPOTS,
    ClubStats,
    Game,
    GameStats,
    GoalEvent,
    MeetingResult,
    Penalty,
    PlayerSeasonDetail,
    SeasonSeriesRecord,
    Shootout,
    Situation,
    StandingsRow,
    Star,
    TeamLeaders,
    conference_standings,
    division_standings,
    playoff_cut,
    playoff_line_ready,
    standings_window,
    team_leaders,
    wildcard_standings,
)
from .hostname import AliasPublisher, current_hostname, valid_hostname_label
from .light_sensor import LightSensor
from .network import default_route_ip
from .priority import Moment, Priority, Windows, idle_segments, segment_at
from .setup_server import SetupServer
from .updater import installed_version
from .wifi_join import WifiJoinAttempt

if TYPE_CHECKING:
    from .demo import DemoStep

log = logging.getLogger(__name__)

#: How long stale data stays on the board before we admit we are offline.
STALE_AFTER_SECONDS = 15 * 60
FRAME_INTERVAL = 0.5
#: Frame interval while a holiday fly-by is crossing the panel (#237). At
#: FRAME_INTERVAL a sprite would jump ~10px a frame; this is ~1px. Only for
#: the few seconds something is moving -- the board idles at 2fps otherwise.
ANIMATION_FRAME_INTERVAL = 0.05
#: The favourite's share of ``rotate_seconds`` while other followed games take
#: turns during its intermission or held final (#260): long enough to read
#: the score, short enough that the games actually being played get the time.
FAVOURITE_QUICK_TURN = 0.5
#: The intermission stats screen (``intermission``): how long each page of the table stays up, and
#: how often the stats are fetched again while the favourite's game sits in an intermission.
INTERMISSION_PAGE_SECONDS = 6.0
INTERMISSION_STATS_REFRESH_SECONDS = 60.0
#: A failed or empty stats fetch is tried again after this long.
INTERMISSION_STATS_RETRY_SECONDS = 15.0
#: The favourite's season schedule changes rarely; this is plenty.
SCHEDULE_TTL_SECONDS = 60 * 60
#: Standings don't change intra-day except right after games finish.
STANDINGS_TTL_SECONDS = 60 * 60
#: A team's jersey numbers never change intra-season; points change only
#: when that team plays, at most a few times a week (#124).
ROSTER_TTL_SECONDS = 60 * 60
#: The upcoming game's head-to-head tally (#157) only moves when another
#: meeting between the same two teams finishes -- days or weeks apart.
SEASON_SERIES_TTL_SECONDS = 60 * 60
#: Season stat leaders (#201) move only when a game finishes.
LEADERS_TTL_SECONDS = 60 * 60
#: How much a new lux reading moves the smoothed value, 0-1. Low on purpose:
#: this is what keeps a cloud passing over a window, or a hand briefly
#: covering the sensor, from visibly flickering the panel.
BRIGHTNESS_SMOOTHING = 0.3
#: How long each scene stays up in ``--demo`` (#47).
DEMO_SCENE_SECONDS = 4.0

#: Scene kinds whose table scrolls over the slot (#280, #296).
SCROLLING_KINDS = ("conference_leaders", "division", "wildcard")
#: How long the admin page's address stays up after the board first gets a
#: default route -- on boot (Ethernet or saved Wi-Fi) or after a join (#293).
ADDRESS_SHOW_SECONDS = 60.0
#: How long a looked-up IP is reused, so the lookup isn't made every frame.
IP_CACHE_SECONDS = 5.0
#: Written by scoreboard-setup-ap while the board's own first-boot WiFi
#: AP is up (#131 follow-up); its mere presence means the ap_setup scene
#: overrides everything else, so a phone that can only reach the board over
#: that AP always sees how to join it. /run, matching the script's own
#: choice -- never survives a reboot stale.
AP_SETUP_STATE_PATH = Path("/run/scoreboard-setup-ap-state.json")
#: Written by scoreboard-setup-ap's pre-AP-mode scan (#132) -- a JSON
#: array of nearby SSIDs, cached from a snapshot taken moments before the AP
#: came up (this chip can't scan while its own AP is active). Read by the
#: setup page to render its network picker; the page always offers a plain
#: text field alongside it too, since that snapshot can miss a network.
AP_SCAN_STATE_PATH = Path("/run/scoreboard-setup-ap-networks.json")
#: Written by the setup page (#132) when someone submits a network choice --
#: the hand-off point for #133's still-to-be-built join flow to read from.
#: This app only ever writes it; it never touches iwd/iwctl itself.
AP_SUBMISSION_STATE_PATH = Path("/run/scoreboard-setup-submission.json")
#: Written by WifiJoinAttempt (#133) while/after acting on a submission --
#: "attempting"/"connected"/"failed" -- and read by _wifi_join_scene() to
#: show it on the panel, the feedback channel #133 decided on since the AP
#: teardown needed to attempt the join kills the phone's own connection to
#: whatever HTTP request submitted it. /run, same non-surviving-a-reboot
#: convention as every other AP-setup-mode state file.
WIFI_JOIN_OUTCOME_PATH = Path("/run/scoreboard-wifi-join-state.json")
#: Marker written by _on_panel_next() while the setup page's display check
#: (#172) has a hardware_mapping trial running -- i.e. it changed
#: [panel].hardware_mapping and restarted the service to try the new value,
#: and "yes, it's working" (_on_panel_confirm()) hasn't cleared it yet.
#: Its existence is the gate; its content is the JSON list of mappings
#: tried so far this trial, so the page can say when a full lap of the
#: candidates has gone by with nothing lit (wiring, not the setting). The
#: current mapping itself is read fresh from self.settings.panel.
#: hardware_mapping, which the restart this file exists to survive already
#: reloads from disk. /run, same never-survives-a-reboot
#: convention as every other AP-setup-mode state file: a full reboot always
#: starts over at whatever's actually configured, not a half-finished trial
#: from hours ago.
HW_MAPPING_TRIAL_PATH = Path("/run/scoreboard-hw-mapping-trial.json")
#: Characters the de-facto WIFI: QR-code format requires backslash-escaped
#: inside SSID/password fields -- unescaped, any of these would end the
#: field early or corrupt the payload for a strict parser.
_QR_SPECIAL_CHARS = re.compile(r'([\\;,:"])')


def _qr_escape(value: str) -> str:
    return _QR_SPECIAL_CHARS.sub(r"\\\1", value)


def _restart_scoreboard_service() -> None:
    """Fire-and-forget ``systemctl restart scoreboard.service`` (#172).

    [panel] settings including hardware_mapping never hot-reload (see
    config.py's Settings.save() and reload_config_if_changed()'s own
    docstring) -- an actual process restart is what rebuilds RGBMatrix with
    a newly-saved mapping. Backgrounded on its own thread, same pattern as
    admin_server.py's _reboot_board(): the
    HTTP response announcing "trying <mapping> now" must reach the phone
    before this process might be torn down to restart, not block on the
    restart finishing first. Restart=always/RestartSec=10 in the unit file
    only governs an unplanned crash; an explicit `restart` here stops and
    starts right away, no 10s delay.
    """

    def _run() -> None:
        try:
            subprocess.run(
                ["systemctl", "restart", "scoreboard.service"],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("Could not restart scoreboard.service: %s", exc)

    threading.Thread(target=_run, daemon=True, name="hw-mapping-restart").start()


#: The least time the board stays on one sport before the ranked list may switch it again.
SPORT_MIN_DWELL_SECONDS = 15.0


#: The football scenes that are a game's own screens (#430): a holiday decorates these only on a
#: Thanksgiving or Christmas game. The clock, the standings, the week grid and the schedule are not.
FOOTBALL_GAME_SCENES = frozenset(
    {
        "fb_scores",
        "fb_field",
        "fb_halftime",
        "fb_play",
        "fb_playtext",
        "fb_event",
        "fb_countdown",
        "fb_preview",
        "fb_final",
        "fb_redzone",
    }
)


@dataclass(frozen=True, slots=True)
class Scene:
    """What the board should show right now.

    ``kind`` is one of ``game`` (live or final scoreboard), ``goal``,
    ``goal_detail``, ``penalty``, ``three_stars``, ``intermission``, ``countdown``, ``preview``,
    ``standings``,
    ``conference_leaders``, ``division``, ``wildcard``, ``matchup``, ``matchup_meetings``,
    ``leaders``, ``scores``, ``clock``, ``christmas_tree``, ``thanksgiving``, ``no_games``,
    ``connecting``, ``no_data``, ``ap_setup``, ``wifi_join``, ``address``.

    Football mode (football) adds the ``fb_`` kinds listed in ``football.mode.FB_SCENE_KINDS``,
    documented in ``football_screen.md`` rather than ``screens.md``.
    """

    kind: str
    game: Game | None = None
    standings: tuple[StandingsRow, ...] | None = None
    #: Set only for ``matchup`` (#157) -- oriented to ``game``'s own
    #: away/home sides, as the API returns it.
    season_series: SeasonSeriesRecord | None = None
    #: Set only for ``matchup``/``matchup_meetings`` (#168) -- the finished
    #: meetings from the favourite's side, oldest first.
    meetings: tuple[MeetingResult, ...] = ()
    #: Set only for ``leaders`` (#201) -- the favourite's own top players.
    leaders: TeamLeaders | None = None
    #: Set only for ``scores`` (#269) -- one grid page of today's games.
    games: tuple[Game, ...] = ()
    #: Set only for ``goal_detail`` -- who scored, and their/their
    #: assisters' season totals (#122).
    goal_event: GoalEvent | None = None
    #: Set only for ``goal`` -- the scoring team's abbreviation, for the
    #: screen's colour and name (#265).
    goal_team: str = ""
    #: Set only for ``penalty`` (#340) -- the call being announced.
    penalty: Penalty | None = None
    #: Set only for ``three_stars`` -- the hockey's three stars of a finished
    #: favourite game, ranked, per-game stats (#156).
    stars: tuple[Star, ...] | None = None
    #: Set only for ``intermission`` -- the favourite's game stats table, and the page tick (the
    #: renderer takes it modulo its own page count).
    stats: GameStats | None = None
    stats_page: int = 0
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
    #: Rows above the playoff line on a standings table (#298), or None for no line.
    playoff_cut: int | None = None
    #: Set only for ``address`` (#293) -- where the admin page is reachable.
    address_ip: str | None = None
    address_port: int = 80
    #: The board's mDNS name (``<host>.local``, #292), None when unknown.
    address_name: str | None = None
    address_qr: tuple[tuple[bool, ...], ...] | None = None
    #: Set only for ``fb_scores`` (#352) -- the football game to show.
    fb_game: FbGame | None = None
    #: Set only for the football play scenes (``fb_play``, ``fb_playtext``, ``fb_event``, #377):
    #: the play, who was on it (jersey numbers), the event being celebrated or alerted, which
    #: stage of it this is (``football.director``), how many animation seconds in and how long
    #: the stage runs. ``fb_elapsed`` is not part of the scene's identity (it changes every
    #: frame; the live view would otherwise snapshot every one), and ``animating`` makes the
    #: loop run fast while the scene is up.
    fb_play: Play | None = None
    fb_people: tuple[Person, ...] = ()
    fb_event: FbEvent | None = None
    fb_stage: str = ""
    #: Set only for the ``stats`` stage: the game's team stats (``football.stats.GameStats``).
    fb_stats: Any = None
    #: What an idle screen draws (#419): the view its builder in ``football/idle_screens.py`` made.
    fb_idle: Any = None
    #: Which page of a several-page idle screen (the standings' division, then conference).
    fb_page: int = 0
    fb_elapsed: float = field(default=0.0, compare=False)
    fb_seconds: float = 0.0
    animating: bool = False
    #: Set only for ``conference_leaders`` -- pixels the list has scrolled up.
    scroll_px: int = 0
    #: True while ``scroll_px`` is still moving, so the loop runs fast.
    scrolling: bool = False


class ScoreboardApp:
    def __init__(
        self,
        settings: Settings,
        client: HockeyClient | None = None,
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
        hw_mapping_trial_path: Path | None = None,
        restart_service: Callable[[], None] | None = None,
        ip_lookup: Callable[[], str | None] | None = None,
        hostname_lookup: Callable[[], str] | None = None,
        alias_publisher: AliasPublisher | None = None,
        football_client_factory: Callable[[], Any] | None = None,
        fetcher: InlineFetcher | ThreadedFetcher | None = None,
    ) -> None:
        self.settings = settings
        #: Where hockey requests run (#267). Inline by default, so tests and the demo
        #: fetch and apply in one call; the real entry point passes a ThreadedFetcher
        #: so a slow API never stops the render loop.
        self.fetcher = fetcher or InlineFetcher()
        self._hostname_lookup = hostname_lookup or current_hostname
        #: None = never publish ``scoreboard.local`` (tests, the demo); the
        #: real entry point passes one (#292).
        self.alias_publisher = alias_publisher
        #: True while the admin page has stepped off port 80 so the WiFi setup
        #: page can have it (see _sync_setup_server).
        self._admin_yielded = False
        #: Injectable so tests never touch a real socket (#293).
        self._ip_lookup = ip_lookup or default_route_ip
        self._ip_cache: tuple[float, str | None] | None = None
        #: monotonic time the post-connect address screen runs until, and
        #: whether the last check found an address (see _track_address).
        self._address_until: float | None = None
        self._had_ip = False
        self._address_qr_cache: tuple[str, tuple[tuple[bool, ...], ...] | None] | None = None
        self.clock = clock or (lambda: datetime.now(UTC))
        self.monotonic = monotonic or time.monotonic
        self.sleep = sleep or time.sleep
        self.ap_setup_state_path = ap_setup_state_path or AP_SETUP_STATE_PATH
        self.ap_scan_state_path = ap_scan_state_path or AP_SCAN_STATE_PATH
        self.ap_submission_state_path = ap_submission_state_path or AP_SUBMISSION_STATE_PATH
        #: The setup page's display check (#172) -- see HW_MAPPING_TRIAL_PATH.
        self.hw_mapping_trial_path = hw_mapping_trial_path or HW_MAPPING_TRIAL_PATH
        self._restart_service = restart_service or _restart_scoreboard_service
        #: Acts on a submission (#133): tears down the AP, calls
        #: scoreboard.wifi's shared join/rollback path, reports the
        #: outcome to the panel. A full object, not just a path, since
        #: tests need to substitute the whole thing (real subprocess/thread
        #: use), not just where its state files live.
        self.wifi_join = wifi_join or WifiJoinAttempt(
            config_path=settings.source_path or DEFAULT_CONFIG_PATHS[0],
            connect_timeout=settings.wifi.connect_timeout_seconds,
            submission_path=self.ap_submission_state_path,
            outcome_path=WIFI_JOIN_OUTCOME_PATH,
        )
        #: The WiFi setup page (#132) -- only running while scoreboard-
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
            volume=settings.audio.volume,
            wah_wah=settings.audio.wah_wah,
            ding=settings.audio.ding,
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
        self.client = client or HockeyClient()
        self.backend = backend or load_backend()
        self.matrix, self.backend = create_matrix(settings.panel, self.backend)
        self.canvas = self.matrix.CreateFrameCanvas()
        #: The admin page's live view (#268): a snapshot per change of scene,
        #: only while it's open. _mirror_key is what the last one showed.
        self.mirror = Mirror(settings.panel.width, settings.panel.height)
        self._mirror_key: object = None
        logos = None
        if settings.scoreboard.show_logos:
            logos = LogoLibrary.default(
                size=min(settings.panel.height, 32), variant=settings.scoreboard.logo_variant
            )
        graphics = MirrorGraphics(self.backend.graphics)
        self.renderer = Renderer(
            graphics=graphics,
            fonts=FontSet(graphics),
            width=settings.panel.width,
            height=settings.panel.height,
            tz=self.tz,
            logos=logos,
        )
        self.renderer.football_logos = self._make_football_logos(settings)
        self.games: list[Game] = []
        self.index = 0
        #: Fetch results waiting out ``broadcast_delay_seconds`` (#301), and the
        #: undelayed games the side fetches target so they start when the API
        #: says a game is live, not N seconds later.
        self._delay = DelayQueue(self.monotonic)
        self._latest_games: list[Game] | None = None
        self._shown_situations: dict[int, Situation | None] = {}
        self._shown_shootouts: dict[int, Shootout | None] = {}
        self.last_success: float | None = None
        #: Wall-clock companions to last_success, for the status page (#48) --
        #: last_success itself is monotonic and not meaningful to a human.
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        #: When a later score poll succeeded after a score-poll error, so the
        #: admin page doesn't show a long-past blip as if it were current.
        self.last_error_recovered_at: datetime | None = None
        self._last_error_from_scores = False
        #: Only a server built here may be rebuilt to yield port 80.
        self._admin_owned = admin_server is None
        self.admin_server = admin_server if admin_server is not None else self._build_admin()
        #: game id -> (fetched at, situation). Only kept for the games we
        #: actually show the indicator on: the favourite's and the on-screen one.
        self.situations: dict[int, tuple[float, Situation | None]] = {}
        #: game id -> (fetched at, shootout, fetched after the game ended).
        #: Same targets as situations, but for games in a shootout (#259).
        self.shootouts: dict[int, tuple[float, Shootout | None, bool]] = {}
        #: game id -> {attempt sequence -> monotonic time it first showed up,
        #: None for attempts already there at our first sighting}, so a
        #: restart mid-shootout doesn't replay every cell (#259).
        self._shootout_seen: dict[int, dict[int, float | None]] = {}
        #: Whether the last shootout frame had a cell mid-animation, which
        #: speeds the loop up the way a moving holiday sprite does.
        self._shootout_animating = False
        self._scroll_animating = False
        #: Demo only: when the current step's newest attempt "appeared".
        self._demo_shootout_started: float | None = None
        #: Demo only: when the current step's goal light "started".
        self._demo_goal_started: float | None = None
        self._egg_animating = False
        #: ``scoreboard --eggs``: the tree egg being shown and its monotonic start (eggs.py).
        self._egg_show: tuple[str, float] | None = None
        #: The favourite's goal light is on screen (fast loop); _goal_building
        #: is its first BUILD_SECONDS, which a live-view snapshot waits out.
        self._goal_animating = False
        self._fb_animating = False
        self._goal_building = False
        #: The penalty screen is on (fast loop); _penalty_building is its
        #: entrance, which a live-view snapshot waits out (#340).
        self._penalty_animating = False
        self._penalty_building = False
        #: Demo only: when the current step's penalty screen "started".
        self._demo_penalty_started: float | None = None
        #: game id -> (fetched at), for the favourite's live games' penalty polls.
        self._penalty_fetched: dict[int, float] = {}
        #: game id -> keys of penalties already seen. Absent until the first
        #: fetch, which is a baseline that never fires (a restart mid-game
        #: doesn't replay) -- same precedent as goal detection.
        self._seen_penalties: dict[int, set[str]] = {}
        #: (game id, monotonic time, penalty) of the screen being shown.
        self._penalty: tuple[int, float, Penalty] | None = None
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
        #: (team, fetched at, picked leaders) for the opt-in leaders screen (#201).
        #: The random tie-break is made once per fetch, so it holds for a whole
        #: TTL instead of flickering each frame.
        self._leaders: tuple[str, float, TeamLeaders | None] | None = None
        self._leaders_retry_after: float = 0.0
        #: Scopes the admin page's Cache tab asked to clear; applied on the render thread.
        self._cache_clears: set[str] = set()
        self._rng = random.Random()
        #: (game id, followed team) -> that team's own score last seen in that
        #: game, so a goal can be detected as an increase. Set on first
        #: sighting without firing, so a game already 3-1 at startup does not
        #: fire a goal. Keyed by team too: two followed teams can meet (#260).
        self._known_scores: dict[tuple[int, str], int] = {}
        #: (game id, monotonic time, scoring team) of the most recent
        #: followed-team goal, for how long the goal scene stays up and
        #: whose colour and name it shows (#265).
        self.last_goal: tuple[int, float, str] | None = None
        #: game id -> (fetched at, followed teams' own GoalEvents seen so far
        #: in that game's scoring array). Followed teams only (#260), same
        #: scoping precedent as goal detection and the PP indicator (#122).
        self._goal_events: dict[int, tuple[float, tuple[GoalEvent, ...]]] = {}
        #: game id -> how many of the favourite's goal_events already had a
        #: goal_detail screen shown, so a late scorer/assist correction never
        #: re-fires for the same goal. Set to the full count on first
        #: sighting without firing, same precedent as _known_scores.
        self._shown_goal_events: dict[int, int] = {}
        #: (game id, monotonic time, event) of the most recent goal_detail
        #: screen, for how long it stays up.
        self._goal_detail: tuple[int, float, GoalEvent] | None = None
        #: team abbrev -> (fetched at, jersey number/points by player id),
        #: for GoalEvent's scorer_sweater_number/scorer_points (#124). Only
        #: ever fetched for a team that has actually just scored the
        #: favourite a goal-detail screen -- not proactively for every team
        #: in the schedule.
        self._team_rosters: dict[str, tuple[float, dict[int, PlayerSeasonDetail]]] = {}
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
        #: game id -> (fetched at, its team stats) for the intermission screen, and when each
        #: game's fetch was last tried. Only the favourite's game in an intermission is fetched.
        self._int_stats: dict[int, tuple[float, GameStats]] = {}
        self._int_stats_tried: dict[int, float] = {}
        #: (game id, monotonic start) of the blowout flash (#326, blowout.py).
        self._blowout: tuple[int, float] | None = None
        self._blowout_shown: set[int] = set()
        #: The configured logo library, held by run_demo() while it toggles
        #: renderer.logos between it and None for the text layout.
        self._demo_real_logos: LogoLibrary | None = logos
        #: Live demo toggle (#204). Set from admin_server's thread, a plain
        #: bool read once per draw() on run()'s thread -- same cross-thread
        #: rule as the physical button's flags. Everything else the main
        #: loop does (polling, goal horn, config reload) keeps running.
        self._demo_mode = False
        self._demo_steps: list[DemoStep] = []
        self._demo_step_index = 0
        self._demo_next_step_at = 0.0
        self._demo_scene: Scene | None = None
        self._demo_was_on = False
        #: Holiday decorations (#237). _overlay_animating is whether the
        #: last frame drew something moving, which is what speeds the loop
        #: up. While a demo is drawing, its own step decides the holiday
        #: (_demo_holiday) instead of the config and the calendar.
        self.holiday_overlay = HolidayOverlay()
        self._overlay_animating = False
        self._demo_drawing = False
        self._demo_holiday: Holiday | None = None
        self._running = False
        #: The sport the board is running right now (#346). Only
        #: ``_switch_sport`` changes it, so ``current_mode()`` is the one
        #: place that decides which sport's code runs.
        #: The ranked ``[[teams]]`` list (epic #470) picks it through the priority layer.
        self._sport = self._initial_sport(settings)
        self._football_client_factory = football_client_factory
        #: Football's mode exists whenever football may take the board (a football team is ranked,
        #: or nothing is and every live game counts): both feeds then run all the time and the
        #: priority layer picks between them.
        self._football: FootballMode | None = (
            self._new_football() if self._wants("football", settings) else None
        )
        #: Today's hockey games as the lite poll saw them while football has the screen (the full
        #: hockey machinery only runs for the sport on screen); the priority layer reads these.
        self._hockey_lite: list[Game] = []
        #: When the light poll last succeeded (monotonic), so hockey is not stale on return.
        self._hockey_lite_at: float | None = None
        #: The priority layer's current owner (the favourite of the moment), set each loop.
        self._owner: Moment | None = None
        #: When the idle rotation began (monotonic): the sports alternate, and this puts the sport
        #: that has the turn at the top of its rotation.
        self._idle_origin = 0.0
        #: The rows of the idle segment now up, by sport (empty unless the sports alternate).
        self._segment_rows: dict[str, list[RotationEntry]] = {}
        self._priority_cache: tuple[tuple[TeamEntry, ...], Priority] | None = None
        #: The hockey favourite the caches were fetched for, to notice the owner changing it.
        self._hockey_favourite = self._hockey_cfg().favourite_team
        #: When the sport on screen last changed, for the minimum dwell between switches.
        self._sport_since = self.monotonic()
        #: Set by a sport switch so run() fetches on its next pass rather than
        #: leaving the new sport on ``connecting`` for a whole poll interval.
        self._poll_asap = False

    # -- lifecycle -------------------------------------------------------

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum: int, _frame: FrameType | None) -> None:
        log.info("Received signal %s; shutting down", signal.Signals(signum).name)
        self._running = False

    def _apply_boot_volume(self) -> threading.Thread:
        """Push the configured volume to the mixer once, off the render loop.

        apply_volume() blocks on `amixer`, so it runs on a short-lived daemon
        thread (#189). Without this a volume set only in the boot TOML was
        never applied until the admin page saved Audio or ran Test horn.
        """

        def work() -> None:
            try:
                self.horn.apply_volume()
            except Exception:
                log.exception("Could not apply boot volume")

        thread = threading.Thread(target=work, name="apply-volume", daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        self._running = True
        self._apply_boot_volume()
        if self.admin_server is not None:
            self.admin_server.start()
        self.renderer.draw_message(self.canvas, "HOCKEY", "CONNECTING")
        self.swap_canvas()
        if self._football is not None:
            self._football.start()

        next_poll = 0.0
        next_rotate = 0.0
        next_brightness = 0.0
        while self._running:
            now = self.monotonic()
            self.reload_config_if_changed()
            self.handle_button()
            self._apply_cache_clears()
            self.fetcher.drain()
            if self._poll_asap:
                self._poll_asap = False
                next_poll = 0.0
            if now >= next_poll:
                self.refresh()
                next_poll = now + self.poll_interval()
            if now >= next_rotate:
                self.advance()
                next_rotate = now + self.settings.scoreboard.rotate_seconds
            if now >= next_brightness:
                self.refresh_brightness()
                next_brightness = now + self.settings.panel.brightness_poll_seconds
            if self.current_mode() == "hockey":
                self.refresh_situations()
                self.refresh_shootouts()
                self.refresh_goal_details()
                self.refresh_penalties()
                self.refresh_three_stars()
                self.refresh_intermission_stats()
            self._choose_sport()
            self._sync_setup_server()
            self._track_address()
            self._sync_alias()
            self.wifi_join.poll()
            self.wifi_join.expire_outcome_if_stale()
            self.draw()
            self.sleep(self.frame_interval())
        self.shutdown()

    def frame_interval(self) -> float:
        animating = (
            self._overlay_animating
            or self._shootout_animating
            or self._scroll_animating
            or self._goal_animating
            or self._fb_animating
            or self._penalty_animating
            or self._egg_animating
        )
        return ANIMATION_FRAME_INTERVAL if animating else FRAME_INTERVAL

    def run_demo(self) -> None:
        """Loop every scene with synthetic data until stopped (#47).

        Deliberately bypasses the real state machine: no ``refresh()``,
        ``select_scene()``, situation/brightness sampling or config reload,
        and no hockey client call at all -- coercing live data into every state
        on demand isn't possible, and a bench board may have no network.
        Goals drawn here never reach ``_on_goal()`` (only ``refresh()``'s
        ``_detect_goals()`` does), so the horn stays silent.
        """
        self._running = True
        self._demo_real_logos = self.renderer.logos
        self._demo_drawing = True
        ticks_per_scene = max(1, round(DEMO_SCENE_SECONDS / FRAME_INTERVAL))
        while self._running:
            # Rebuilt each pass so the preview/countdown stay relative to now.
            steps = self._demo_step_list()
            for step in steps:
                if not self._running:
                    break
                self._set_demo_logos(step.use_logos)
                self._start_demo_holiday(step)
                self._start_demo_shootout(step)
                self._start_demo_goal(step)
                self._start_demo_penalty(step)
                if step.scroll_seconds:
                    self._play_scrolling_demo_step(step.scene, step.scroll_seconds)
                    continue
                if (
                    self._demo_holiday is not None
                    or step.animate_shootout
                    or step.animate_goal
                    or step.animate_penalty
                ):
                    self._play_animated_demo_step(step.scene)
                    continue
                self.draw_scene(step.scene)
                for _ in range(ticks_per_scene):
                    if not self._running:
                        break
                    self.sleep(FRAME_INTERVAL)
        self._demo_drawing = False
        self.renderer.logos = self._demo_real_logos
        self.shutdown()

    def run_eggs(self, names: tuple[str, ...]) -> None:
        """Play the named Easter eggs in a loop until stopped (``--eggs``, see eggs.py).

        Like ``run_demo`` it bypasses the state machine and hands scenes to ``draw_scene``. The
        clock is held on a date the screen's countdown works for, whatever the real date.
        """
        from . import eggs

        self._running = True
        self._demo_drawing = True
        real_clock = self.clock
        try:
            while self._running:
                for name in names:
                    for phase in eggs.plan(name):
                        self._play_egg_phase(phase, real_clock)
        finally:
            self._egg_show = None
            self.clock = real_clock
            self._demo_drawing = False
        self.shutdown()

    def _play_egg_phase(self, phase: Any, real_clock: Any) -> None:
        """Draw one stretch of the egg tour (an ``eggs.Phase``), the clock held on its day."""
        from . import eggs

        month, day = phase.day or eggs.TOUR_DAY
        now = real_clock()
        offset = now.replace(month=month, day=day, hour=18) - now
        self.clock = lambda: real_clock() + offset
        started = self.monotonic()
        self._egg_show = (phase.egg, started) if phase.egg else None
        if phase.prank:
            # April Fools only happens on the day, on a Preds board: force it for this stretch.
            self.april_fools_active = lambda: True  # type: ignore[method-assign]
        try:
            while self._running and self.monotonic() - started < phase.seconds:
                self.draw_scene(phase.scene)
                self.sleep(self.frame_interval())
        finally:
            self._egg_show = None
            self.__dict__.pop("april_fools_active", None)

    def _demo_step_list(self) -> list[DemoStep]:
        """The steps for the board's sport; football's are all text and field, no sound (#359)."""
        # Imported here: demo builds Scene objects, so a top-level import would be circular.
        if self._sport == "football":
            from .football.demo import football_demo_steps

            return football_demo_steps(self.clock())
        from .demo import demo_steps

        # A demo has to show a favourite's screens: Nashville when no hockey team is ranked.
        return demo_steps(self._hockey_cfg().favourite_team or "NSH", self.clock())

    def _start_demo_holiday(self, step: DemoStep) -> None:
        """Force a step's holiday on, with a fly-by starting right now.

        A demo step lasts seconds; the real gap between fly-bys is minutes.
        """
        self._demo_holiday = HOLIDAYS.get(step.holiday) if step.holiday else None
        if self._demo_holiday is not None:
            self.holiday_overlay.start_flyby(self.monotonic())

    def _start_demo_shootout(self, step: DemoStep) -> None:
        """Make a step's newest shootout attempt pop in as the step starts (#259)."""
        self._demo_shootout_started = self.monotonic() if step.animate_shootout else None

    def _start_demo_goal(self, step: DemoStep) -> None:
        """Start a step's goal light as the step starts."""
        self._demo_goal_started = self.monotonic() if step.animate_goal else None

    def _turkey_egg(self) -> tuple[str, float] | None:
        """The Thanksgiving turkey egg playing now and its age (#516); never in demo mode."""
        if self._egg_show is not None:
            kind, started = self._egg_show
            return (kind, self.monotonic() - started) if kind == "turkey" else None
        if self._demo_drawing:
            return None
        return turkey_egg(self.clock().timestamp())

    def _tree_egg(self) -> tuple[str, float] | None:
        """The Christmas tree Easter egg playing now and its age (#509); never in demo mode."""
        if self._egg_show is not None:
            kind, started = self._egg_show
            return (kind, self.monotonic() - started) if kind != "turkey" else None
        if self._demo_drawing:
            return None
        return tree_egg(self.clock().timestamp())

    def _start_demo_penalty(self, step: DemoStep) -> None:
        """Start a step's penalty screen as the step starts."""
        self._demo_penalty_started = self.monotonic() if step.animate_penalty else None

    def _penalty_age(self, scene: Scene) -> float | None:
        """Seconds into the penalty screen, or ``None`` for any other scene."""
        if scene.kind != "penalty":
            return None
        if self._demo_penalty_started is not None:
            return self.monotonic() - self._demo_penalty_started
        if self._penalty is not None and scene.game is not None:
            game_id, started, _penalty = self._penalty
            if game_id == scene.game.id:
                return max(0.0, self.monotonic() - started)
        return 0.0

    def _goal_age(self, scene: Scene) -> float | None:
        """Seconds into the favourite's goal light, or ``None`` for the quick
        static goal screen: followed teams' goals are quick updates (#260),
        and a goal scene with no goal behind it (a direct draw) has no age."""
        if scene.kind != "goal":
            return None
        favourite = self._hockey_cfg().favourite_team
        if april_fools.active(favourite, self.clock().astimezone(self.tz)):
            favourite = april_fools.PRANK_AS
        if not favourite or (scene.goal_team or favourite) != favourite:
            return None
        if self._demo_goal_started is not None:
            return self.monotonic() - self._demo_goal_started
        if self.last_goal is not None and scene.game is not None:
            game_id, goal_time, _team = self.last_goal
            if game_id == scene.game.id:
                return max(0.0, self.monotonic() - goal_time)
        return None

    def _play_animated_demo_step(self, scene: Scene) -> None:
        """Redraw every frame for DEMO_SCENE_SECONDS, so the fly-by actually moves."""
        end = self.monotonic() + DEMO_SCENE_SECONDS
        while self._running and self.monotonic() < end:
            self.draw_scene(scene)
            self.sleep(self.frame_interval())

    def _play_scrolling_demo_step(self, scene: Scene, seconds: float) -> None:
        """Scroll a conference table through one slot's worth of dwell."""
        start = self.monotonic()
        while self._running and (elapsed := self.monotonic() - start) < seconds:
            self.draw_scene(self._scroll_conference(scene, elapsed, seconds))
            self.sleep(self.frame_interval())

    def set_demo_mode(self, enabled: bool) -> None:
        """Turn the live demo on or off (#204); safe from any thread."""
        self._demo_mode = bool(enabled)

    def _draw_demo_step(self) -> None:
        """Advance the live demo on ``DEMO_SCENE_SECONDS`` and draw its current step."""
        now = self.monotonic()
        if now >= self._demo_next_step_at:
            if self._demo_step_index >= len(self._demo_steps):
                # Rebuilt each pass so preview/countdown stay relative to now.
                self._demo_steps = self._demo_step_list()
                self._demo_step_index = 0
            step = self._demo_steps[self._demo_step_index]
            self._demo_step_index += 1
            self._demo_next_step_at = now + DEMO_SCENE_SECONDS
            self._set_demo_logos(step.use_logos)
            self._start_demo_holiday(step)
            self._start_demo_shootout(step)
            self._start_demo_goal(step)
            self._demo_scene = step.scene
        self._demo_drawing = True
        try:
            self.draw_scene(self._demo_scene)
        finally:
            self._demo_drawing = False

    def _set_demo_logos(self, use_logos: bool) -> None:
        """Show the text fallback layout on demand, whatever the board has configured.

        With ``show_logos`` off there was never a library, so logo steps
        simply draw as text too.
        """
        self.renderer.logos = self._demo_real_logos if use_logos else None

    def shutdown(self) -> None:
        try:
            if self._football is not None:
                self._football.stop()
            if self.admin_server is not None:
                self.admin_server.stop()
            if self.setup_server is not None:
                self.setup_server.stop()
            if self.alias_publisher is not None:
                self.alias_publisher.stop()
            if self.button is not None:
                self.button.close()
            self.matrix.Clear()
        finally:
            self.fetcher.close()
            self.client.close()
        log.info("Scoreboard stopped")

    # -- data ------------------------------------------------------------

    @staticmethod
    def _make_football_logos(settings: Settings) -> LogoSet | None:
        """The football logo set, or ``None`` with logos switched off (#349). Cheap: the files
        are only read when a screen first asks for a team at a size."""
        if not settings.scoreboard.show_logos:
            return None
        return LogoSet("football", settings.scoreboard.logo_variant)

    def _new_football(self) -> FootballMode:
        """A football mode over the live settings. Its feed thread is not started here: ``run()``
        starts it, and a later edit of the ranked list starts it once the loop is running."""
        return FootballMode(
            lambda: self.settings.scoreboard,
            client_factory=self._football_client_factory,
            monotonic=self.monotonic,
            football=self._football_cfg,
            delay_seconds=self._delay_seconds,
            utc_now=self.clock,
            wide=lambda: self.renderer.width >= 128,
            on_sound=self._on_football_sound,
        )

    def _on_football_sound(self, event: FbEvent) -> None:
        """The lead football team's touchdown or made field goal (#517): its own sound, else the
        default. Same rules as the hockey horn: the audio switch, volume and button mute apply."""
        kind = "td" if isinstance(event, Touchdown) else "fg"
        log.info("Football %s sound: %s", kind, event.team)
        if self._horn_muted():
            log.info("Sounds muted by button press; not playing the football sound")
            return
        self.horn.play_football(event.team, kind)

    def current_mode(self) -> str:
        """``hockey`` or ``football``: the one place that says which sport is running (#346)."""
        return self._sport

    @staticmethod
    def _initial_sport(settings: Settings) -> str:
        """The sport to start on: the top-ranked team's, else hockey."""
        return settings.teams[0].sport if settings.teams else "hockey"

    @staticmethod
    def _wants(sport: str, settings: Settings) -> bool:
        """Whether ``sport``'s feed is needed: a team of it is ranked, or none is (every live game
        of either sport counts then). A hockey-only list never polls football's feed."""
        return not settings.teams or any(entry.sport == sport for entry in settings.teams)

    def _reset_favourite_caches(self) -> None:
        """Forget what was fetched for the previous favourite.

        ``next_favourite_game()``'s ``_schedule`` cache is one season schedule for whichever team
        it was last fetched for, kept fresh purely by ``SCHEDULE_TTL_SECONDS`` elapsing: nothing in
        that check knows *which* team the cached games belong to. Left alone, a change of
        favourite keeps showing the *previous* team's next game (a different matchup entirely) for
        up to an hour, which is exactly why the matchup screen (#157) once kept showing the old
        opponent. Only the countdown/preview/matchup fallback to the season schedule is affected
        (today's game is read fresh from ``self.games``). The team leaders are one team's too.

        Called when the ranked list is edited and when the owner (the favourite of the moment)
        changes."""
        self._schedule = None
        self._schedule_retry_after = 0.0
        self._leaders = None
        self._leaders_retry_after = 0.0

    def _colour_scheme(self, favourite: str, *, clock: bool = False) -> tuple[str, str]:
        """The (sport, team) the clock, tree and holiday overlay take their colours from.

        It is the overall rank 1, whichever sport is on screen, so the colours do not change as
        games start and end (epic #470). With no team ranked they are plain, as the clock always was
        in football mode (``favourite`` is only what a game screen is about, not a colour choice).
        """
        if favourite == april_fools.PRANK_AS:
            return "hockey", favourite  # the April Fools prank recolours everything, as ever
        first = self._priority().colour_team()
        if first is not None:
            return first.sport, first.team
        return "hockey", ""

    def _priority(self) -> Priority:
        """The priority layer over the current ranked list (rebuilt only when the list changes)."""
        teams = tuple(self.settings.teams)
        if self._priority_cache is None or self._priority_cache[0] != teams:
            self._priority_cache = (teams, Priority(teams))
        return self._priority_cache[1]

    def _football_cfg(self) -> Any:
        """Football's settings as its screens read them: ``[football]`` seen through
        the priority layer (the owner is the favourite, the other ranked football teams are
        followed, the lead team has the horn; with no team ranked, nobody is)."""
        return self._priority().view(
            "football", self.settings.football, self._owner, self._sport_rotation("football")
        )

    def _hockey_cfg(self) -> Any:
        """Hockey's settings as its screens read them: ``[scoreboard]`` seen through
        the priority layer (the owner is the favourite, the other ranked hockey teams are followed,
        the lead team has the horn; with no team ranked, nobody is)."""
        return self._priority().view("hockey", self.settings.scoreboard, self._owner)

    def _priority_windows(self) -> dict[str, Windows]:
        hockey, football = self.settings.scoreboard, self.settings.football
        return {
            "hockey": Windows(
                countdown=timedelta(hours=hockey.countdown_hours),
                final_hold=timedelta(minutes=hockey.final_hold_minutes),
            ),
            "football": Windows(
                countdown=timedelta(minutes=football.countdown_minutes),
                final_hold=timedelta(minutes=football.final_hold_minutes),
            ),
        }

    def _desired_sport(self) -> str:
        """The sport the ranked list wants on screen now (epic #470).

        The owner (the highest-ranked team that is live, else in its countdown, else in a held
        final) decides; with nobody on, the sports take turns showing their idle rotations. With no
        team ranked at all, a live game of either sport takes the board (hockey first), and
        otherwise hockey keeps it (its no-favourite flow shows every game, or the clock).
        """
        football_games = list(self._football.snapshot.games or ()) if self._football else []
        hockey_games = self._hockey_priority_games()
        now = self.clock()
        ages = {("hockey", gid): now - ended for gid, ended in self.ended_at.items()}
        if self._football is not None:
            self._football.track()
            ages.update(
                {
                    ("football", gid): timedelta(seconds=s)
                    for gid, s in self._football.final_ages().items()
                }
            )
        priority = self._priority()
        owner = priority.owner(
            {"hockey": hockey_games, "football": football_games},
            now,
            self._priority_windows(),
            ages,
        )
        self._owner = owner
        if owner is not None:
            self._segment_rows = {}
            return owner.sport
        if priority.empty:
            self._idle_origin = 0.0
            games = {"hockey": hockey_games, "football": football_games}
            return priority.empty_list_sport(games) or "hockey"
        return self._idle_sport(priority)

    def _hockey_priority_games(self) -> list[Game]:
        """Today's hockey games for the priority layer: the full machinery's while hockey has the
        board, else the light poll's. Right after a switch to hockey ``games`` is still empty until
        the next poll, so the light poll's last answer covers that gap."""
        return (self.games if self._sport == "hockey" else None) or self._hockey_lite

    def _idle_available(self) -> list[str]:
        """The sports with something to show now, best-ranked lead first: a sport whose slate is
        empty (the offseason, or its feed is down) sits out of the idle rotation."""
        football_games = self._football.snapshot.games if self._football is not None else None
        have = {"hockey": bool(self._hockey_priority_games()), "football": bool(football_games)}
        order = self._priority().sports() or ["hockey", "football"]
        return [sport for sport in order if have.get(sport)]

    def _idle_sport(self, priority: Priority) -> str:
        """With nothing ranked on, the one idle rotation runs across both sports: its rows are
        grouped into per-sport segments and the board alternates between them (epic #470). Falls
        back to the top-ranked team's sport when no sport has anything to show."""
        segments = idle_segments(self._unified_rotation(), self._idle_available())
        now = self.monotonic()
        slot = segment_at(segments, now)
        self._segment_rows = {}
        if slot is None:
            self._idle_origin = 0.0
            if self._football is not None:
                self._football.idle_origin = 0.0
            return priority.sports()[0]
        index, fraction = slot
        segment = segments[index]
        # The segment began ``fraction`` of its length ago: its sport times its rows from there.
        self._idle_origin = now - fraction * segment.seconds
        self._segment_rows = {segment.sport: list(segment.entries)}
        if self._football is not None:
            self._football.idle_origin = self._idle_origin
        return segment.sport

    def _apply_teams_change(self, new_settings: Settings) -> None:
        """The ranked list was edited: start or stop football's feed as it is wanted, forget what
        belonged to the old favourite and followed teams, and let the next ``_choose_sport`` pick
        from the new order."""
        wants_football = self._wants("football", new_settings)
        if wants_football and self._football is None:
            self._football = self._new_football()
        if wants_football and self._running:
            self._football.start()  # idempotent
        elif not wants_football and self._football is not None:
            self._football.stop()  # its feed thread must not outlive the mode
            self._football = None
            if self._sport == "football":
                self._switch_sport("hockey", force_clean=True)
        self._reset_favourite_caches()
        # _goal_events counts only followed teams' goals, so a team added mid-game would read as its
        # whole tally scoring at once. Forget them; the next poll re-baselines without firing.
        self._goal_events.clear()
        self._shown_goal_events.clear()
        self._seen_penalties.clear()
        self._penalty_fetched.clear()
        self._choose_sport(force=True)  # an edit takes effect now, not after the minimum dwell

    def _choose_sport(self, *, force: bool = False) -> None:
        """Switch the sport on screen when the ranked list wants another, but not twice within
        ``SPORT_MIN_DWELL_SECONDS``: a game starting is taken at once after a quiet spell, yet two
        borderline moments cannot make the board flip back and forth."""
        wanted = self._desired_sport()
        favourite = self._hockey_cfg().favourite_team
        if favourite != self._hockey_favourite:
            self._hockey_favourite = favourite
            self._reset_favourite_caches()
        dwelt = self.monotonic() - self._sport_since >= SPORT_MIN_DWELL_SECONDS
        if wanted != self._sport and (force or dwelt):
            # An edit of the list (``force``) starts the new sport from a clean slate; only the idle
            # rotation's own alternation keeps hockey's state.
            self._switch_sport(wanted, force_clean=force)

    def _switch_sport(self, sport: str, *, force_clean: bool = False) -> None:
        """Swap the running sport live, from a clean slate (#346).

        Drops everything the old sport held -- cached data, remembered scores,
        goal detection, the last scene, animations -- so the new sport starts
        at ``connecting`` and baselines on its first fetch: nothing celebrates
        or sounds on the first frame after a switch. The button mute is the
        owner's, not the sport's, so it survives.
        """
        # The idle rotation passing between the sports happens every few seconds and says nothing
        # new, so it is DEBUG; a switch caused by a game, or by editing the list, stays INFO.
        idle_alternation = self._owner is None and not force_clean
        log.log(
            logging.DEBUG if idle_alternation else logging.INFO,
            "Switching sport %s -> %s",
            self._sport,
            sport,
        )
        if self._sport == "hockey" and self.games:
            self._hockey_lite = list(self.games)  # the priority layer keeps seeing hockey's slate
            self._hockey_lite_at = self.last_success
        # Both feeds keep running: football's mode stays up and only starts its screens afresh when
        # it takes the board.
        if self._football is None:
            # Normally only when a football team is ranked (or none is); a demo on a hockey-only
            # board asks for football explicitly, and football's mode must exist to show it.
            if sport == "football" or self._wants("football", self.settings):
                self._football = self._new_football()
                if self._running:
                    self._football.start()
        elif sport == "football":
            self._football.reset_screens()
        self._sport = sport
        self._sport_since = self.monotonic()
        self._poll_asap = True
        if self._owner is None and not force_clean:
            # Nothing ranked is on, so this is only the idle rotation passing between the sports,
            # which happens every few seconds. Wiping hockey's state each time put CONNECTING on
            # the panel at every return and emptied its standings, schedule and leaders caches.
            # Keep it all; hockey comes back on its light poll's last answer, and the next poll
            # catches up. Scores are re-baselined so a goal scored while away does not celebrate.
            if sport == "hockey":
                if self._hockey_lite:
                    self.games = list(self._hockey_lite)
                    self.last_success = self._hockey_lite_at or self.last_success
                self._known_scores = {}
            self._mirror_key = None
            self.mirror.requested = True
            return
        self.games = []
        self.index = 0
        self._delay = DelayQueue(self.monotonic)
        self._latest_games = None
        self._shown_situations = {}
        self._shown_shootouts = {}
        self.situations = {}
        self.shootouts = {}
        self._shootout_seen = {}
        self.last_success = None
        self.last_success_at = None
        self.last_error = None
        self.last_error_at = None
        self.last_error_recovered_at = None
        self._last_error_from_scores = False
        self.ended_at = {}
        self._seen_live = set()
        self._schedule = None
        self._schedule_retry_after = 0.0
        self._standings = None
        self._standings_retry_after = 0.0
        self._season_series = {}
        self._season_series_retry_after = {}
        self._leaders = None
        self._leaders_retry_after = 0.0
        self._known_scores = {}
        self.last_goal = None
        self._goal_events = {}
        self._shown_goal_events = {}
        self._goal_detail = None
        self._team_rosters = {}
        self._three_stars_pending = {}
        self._three_stars_shown = set()
        self._three_stars = None
        self._int_stats = {}
        self._int_stats_tried = {}
        self._blowout = None
        self._blowout_shown = set()
        self._shootout_animating = False
        self._scroll_animating = False
        self._goal_animating = self._goal_building = self._fb_animating = False
        self._overlay_animating = False
        self._demo_shootout_started = None
        self._demo_goal_started = None
        self._egg_animating = False
        self._mirror_key = None
        self.mirror.requested = True

    def refresh(self) -> None:
        if self._sport == "football" and self._football is not None:
            self._football.refresh()
            if self._wants("hockey", self.settings):
                # Hockey keeps being polled, lightly, so the priority layer can see it start.
                self.fetcher.submit("scores_lite", self.client.scores, self._on_scores_lite)
            return
        self.fetcher.submit("scores", self.client.scores, self._on_scores)

    def _on_scores_lite(self, games: list[Game] | None, error: Exception | None) -> None:
        """The hockey poll made while football has the screen: remember the games for the priority
        layer and nothing else (no goal detection, no horn, no status errors)."""
        if error is not None or games is None:
            log.debug("Hockey lite poll failed: %s", error)
            return
        self._hockey_lite = list(games)
        self._hockey_lite_at = self.monotonic()

    def _on_scores(self, games: list[Game] | None, error: Exception | None) -> None:
        """A score fetch finished (on the render thread): apply it, or record the failure."""
        if error is not None or games is None:
            log.warning("Score refresh failed: %s", error)
            self._record_error(f"score refresh: {error}", from_scores=True)
            return
        self._latest_games = self.order(games)
        self.last_success = self.monotonic()
        self.last_success_at = self.clock()
        if self._last_error_from_scores and self.last_error_recovered_at is None:
            self.last_error_recovered_at = self.last_success_at
        self._submit("games", lambda: self._apply_games(games))

    def _delay_seconds(self) -> float:
        return min(max(self.settings.scoreboard.broadcast_delay_seconds, 0.0), 300.0)

    def _submit(self, key: object, apply: Callable[[], None]) -> None:
        """Apply a fetch result after the broadcast delay (#301); at once with none."""
        self._delay.submit(key, self._delay_seconds(), apply)

    def _api_games(self) -> list[Game]:
        """Today's games as the API has them now, ahead of the delayed ``self.games``.

        Side fetches (situation, shootout, scorer) and the poll cadence follow
        this so they start on time; their results are delayed on the way in.
        """
        if self._latest_games is not None and self._delay_seconds() > 0:
            return self._latest_games
        return self.games

    def _apply_games(self, games: list[Game]) -> None:
        self.games = self.order(games)
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
                self._note_blowout(game, watched=watched)
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

        ``_seen_live``, ``ended_at``, ``_known_scores`` and the
        goal-detail/three-stars bookkeeping are keyed by game id and
        otherwise never cleared, growing by one entry per game for as long
        as the process runs (#64). ``self.games`` is
        refreshed from the live schedule every poll, so any id no longer in
        it is done for today and safe to forget.
        """
        current_ids = {game.id for game in self.games} | {game.id for game in self._api_games()}
        self._delay.forget(lambda key: not isinstance(key, tuple) or key[1] in current_ids)
        for shown in (self._shown_situations, self._shown_shootouts):
            for game_id in list(shown):
                if game_id not in current_ids:
                    del shown[game_id]
        self._seen_live &= current_ids
        for game_id in list(self.ended_at):
            if game_id not in current_ids:
                del self.ended_at[game_id]
        for key in list(self._known_scores):
            if key[0] not in current_ids:
                del self._known_scores[key]
        for game_id in list(self._goal_events):
            if game_id not in current_ids:
                del self._goal_events[game_id]
        for game_id in list(self._shown_goal_events):
            if game_id not in current_ids:
                del self._shown_goal_events[game_id]
        for game_id in list(self._three_stars_pending):
            if game_id not in current_ids:
                del self._three_stars_pending[game_id]
        for game_id in list(self._seen_penalties):
            if game_id not in current_ids:
                del self._seen_penalties[game_id]
        for game_id in list(self._penalty_fetched):
            if game_id not in current_ids:
                del self._penalty_fetched[game_id]
        self._three_stars_shown &= current_ids
        self._blowout_shown &= current_ids

    def _record_error(self, message: str, *, from_scores: bool = False) -> None:
        """Track the most recent fetch failure, for the status page (#48).

        Only a score-poll error can be marked recovered: the next good score
        poll says nothing about whether, say, the standings fetch works now.
        """
        self.last_error = message
        self.last_error_at = self.clock()
        self.last_error_recovered_at = None
        self._last_error_from_scores = from_scores

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
        the favourite's _schedule fix (``_reset_favourite_caches``) was missing until a
        live bug (#178's admin-page work) surfaced it. When adding a new
        cache or rebuilt-from-settings object anywhere in this class,
        check here first: does a relevant field change need to reset or
        rebuild it, the same way audio_changed/logos_changed/
        teams_changed/etc. do below?
        """
        old = self.settings
        audio_changed = dataclasses.astuple(old.audio) != dataclasses.astuple(new_settings.audio)
        logos_changed = (
            old.scoreboard.show_logos != new_settings.scoreboard.show_logos
            or old.scoreboard.logo_variant != new_settings.scoreboard.logo_variant
        )
        timezone_changed = old.scoreboard.timezone != new_settings.scoreboard.timezone
        teams_changed = old.teams != new_settings.teams
        auto_brightness_changed = old.panel.auto_brightness != new_settings.panel.auto_brightness
        status_changed = (
            old.status.enabled,
            old.status.port,
            old.status.alias_port,
        ) != (new_settings.status.enabled, new_settings.status.port, new_settings.status.alias_port)
        # mute_minutes is read fresh on every press, so it alone needs no rebuild.
        button_changed = (old.button.enabled, old.button.pin, old.button.hold_seconds) != (
            new_settings.button.enabled,
            new_settings.button.pin,
            new_settings.button.hold_seconds,
        )

        self.settings = new_settings

        if teams_changed:
            # The favourite's cached season schedule and team leaders belong to one team, and the
            # followed teams' goal tallies to the old set (see ``_reset_favourite_caches``).
            self._apply_teams_change(new_settings)

        if timezone_changed:
            self.tz = resolve_timezone(new_settings.scoreboard.timezone, fallback=self.tz)
            self.renderer.tz = self.tz

        if audio_changed:
            # volume is carried on the rebuilt object but deliberately not
            # applied to the ALSA mixer here: GoalHornPlayer.apply_volume()
            # blocks on a real `amixer` subprocess, and this method runs on
            # the same thread as frame rendering -- a stalled/slow amixer
            # call here would stutter the panel. admin_server.py applies it
            # instead, from its own background thread, on an audio save and
            # on Test horn (#187).
            self.horn = GoalHornPlayer.default(
                device=new_settings.audio.device,
                horn_dir=new_settings.audio.horn_dir,
                enabled=new_settings.audio.enabled,
                volume=new_settings.audio.volume,
                wah_wah=new_settings.audio.wah_wah,
                ding=new_settings.audio.ding,
            )

        if logos_changed:
            logos = None
            if new_settings.scoreboard.show_logos:
                logos = LogoLibrary.default(
                    size=min(new_settings.panel.height, 32),
                    variant=new_settings.scoreboard.logo_variant,
                )
            self.renderer.logos = logos
            self.renderer.football_logos = self._make_football_logos(new_settings)

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
            self.admin_server = self._build_admin()
            # run() starts the server once, before its loop; a rebuild
            # inside the loop has to start itself. Outside the loop,
            # construct only -- same as __init__ -- so it's run() that
            # binds the socket, not whoever happened to reload.
            if self.admin_server is not None and self._running:
                self.admin_server.start()

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

        "tracked" means every followed team's games (#260), the favourite's
        included. With no team followed at all it has nothing to track, so
        it behaves as "all" -- a normal combination (no favourite_team
        configured, with night mode on), not a misconfiguration worth a
        warning.
        """
        cfg = self.settings.night_mode
        if cfg.suppress_scope == "all" or not self._hockey_cfg().followed_teams:
            candidates = self.games
        else:
            candidates = [g for g in self.games if self._is_followed(g)]
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

    def _is_followed(self, game: Game) -> bool:
        """Does ``game`` involve the favourite or an ``also_follow`` team (#260)?"""
        return any(game.involves(team) for team in self._hockey_cfg().followed_teams)

    def _celebrated_teams(self, game: Game) -> list[str]:
        """The teams in ``game`` whose goals get the goal screen (#260).

        In the favourite's own game that's only the favourite, even against a
        followed team: a goal against the favourite is never celebrated.
        """
        favourite = self._hockey_cfg().favourite_team
        if favourite and game.involves(favourite):
            return [favourite]
        return [t for t in self._hockey_cfg().also_follow if game.involves(t)]

    def _detect_goals(self, games: list[Game]) -> None:
        """A followed team's goal: their own score increased since we last saw it.

        Scoped to followed teams' own goals -- the favourite plus
        ``also_follow`` (#260) -- never their opponents' or other games',
        same reasoning as the power-play indicator (situation_targets):
        this is a your-teams board, not a "celebrate every goal in every
        game" one. A followed team playing the favourite is an opponent
        there (``_celebrated_teams``).
        """
        for game in games:
            for team in self._celebrated_teams(game):
                score = game.home.score if game.home.abbrev == team else game.away.score
                previous = self._known_scores.get((game.id, team))
                self._known_scores[(game.id, team)] = score
                if previous is not None and score > previous:
                    self._on_goal(game, team)
            self._detect_opponent_goal(game)

    def _detect_opponent_goal(self, game: Game) -> None:
        """The favourite's opponent scored in a live game: the "wah wah" (#307).

        Sound only: no goal screen, same as any non-favourite goal. Baselined
        on first sighting without firing, so a restart mid-game stays quiet;
        recorded under the opponent's own ``_known_scores`` key (free in the
        favourite's game, where only the favourite is celebrated). Skipped
        in a shootout, where the headline score only moves when it's decided.
        """
        favourite = self._hockey_cfg().favourite_team
        if not favourite or not game.involves(favourite):
            return
        opponent = game.away if game.home.abbrev == favourite else game.home
        previous = self._known_scores.get((game.id, opponent.abbrev))
        self._known_scores[(game.id, opponent.abbrev)] = opponent.score
        if previous is None or opponent.score <= previous:
            return
        if not game.is_live or game.in_shootout:
            return
        log.info("Opponent goal: %s (%d)", opponent.abbrev, opponent.score)
        if self._horn_muted():
            log.info("Sounds muted by button press; not playing the wah wah")
            return
        self.horn.play_wah_wah()

    def _on_goal(self, game: Game, team: str | None = None) -> None:
        """Show the goal scene; the horn is the lead team's (the favourite's, without a ranked
        list), another followed team gets the ding."""
        cfg = self._hockey_cfg()
        favourite = cfg.favourite_team
        horn_team = getattr(cfg, "horn_team", favourite)
        team = team or favourite
        log.info(
            "GOAL: %s %s %d-%d %s",
            team,
            game.away.abbrev,
            game.away.score,
            game.home.score,
            game.home.abbrev,
        )
        self.last_goal = (game.id, self.monotonic(), team)
        if team != horn_team:
            # #311: live goals only; a shootout's headline score moves when decided.
            if game.is_live and not game.in_shootout:
                if self._horn_muted():
                    log.info("Sounds muted by button press; not playing the ding")
                else:
                    self.horn.play_ding()
            return
        if self._horn_muted():
            log.info("Goal horn muted by button press; not playing")
            return
        self.horn.play(team)

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

        Scoped to followed teams' live games (the favourite plus
        ``also_follow``, #260) and their own goals, same precedent as goal
        detection and the PP indicator: one request per live followed game,
        to the same landing URL ``refresh_situations()`` already polls (not
        a new endpoint), on the same ``live_poll_seconds`` cadence, skipped
        during intermission for the same reason situation is.
        """
        for game in self._api_games():
            if game.is_live and self._is_followed(game):
                self._refresh_goal_detail(game, self._celebrated_teams(game))

    def _refresh_goal_detail(self, game: Game, teams: list[str]) -> None:
        now = self.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        fetched_at, events = self._goal_events.get(game.id, (None, ()))
        if fetched_at is not None and now - fetched_at < interval:
            return
        if game.in_intermission:
            self._goal_events[game.id] = (now, events)
            return
        self.fetcher.submit(
            ("goal_detail", game.id),
            lambda i=game.id, t=tuple(teams): self._fetch_goal_events(i, t),
            lambda r, e, i=game.id, t=now, tm=tuple(teams): self._on_goal_events(i, t, tm, r, e),
        )

    def _fetch_goal_events(
        self, game_id: int, teams: tuple[str, ...]
    ) -> tuple[tuple[GoalEvent, ...], dict[str, dict[int, PlayerSeasonDetail]]]:
        """Worker thread: the scoring array, plus the roster a new goal will need (#124).

        The roster is fetched here, not when the scorer screen builds, so that
        screen never waits on the network. Still lazy, as before: only when a
        goal beyond the ones already shown has appeared, and only if that
        team's cached roster is missing or stale. Reads the app's caches
        without writing them; ``_on_goal_events`` stores the result.
        """
        all_events = self.client.goal_scoring(game_id)
        team_events = tuple(e for e in all_events if e.team_abbrev in teams)
        rosters: dict[str, dict[int, PlayerSeasonDetail]] = {}
        shown = self._shown_goal_events.get(game_id)
        if shown is not None:
            for event in team_events[shown : shown + 1]:
                if not self._roster_fresh(event.team_abbrev):
                    try:
                        rosters[event.team_abbrev] = self.client.team_roster(event.team_abbrev)
                    except HockeyApiError as exc:
                        log.debug("Roster fetch for %s failed: %s", event.team_abbrev, exc)
        return team_events, rosters

    def _on_goal_events(
        self,
        game_id: int,
        fetched_at: float,
        teams: tuple[str, ...],
        result: tuple[tuple[GoalEvent, ...], dict[str, dict[int, PlayerSeasonDetail]]] | None,
        error: Exception | None,
    ) -> None:
        if error is not None or result is None:
            log.debug("Goal scoring fetch for %s failed: %s", game_id, error)
            team_events = self._goal_events.get(game_id, (None, ()))[1]
        else:
            team_events, rosters = result
            for team, roster in rosters.items():
                self._team_rosters[team] = (fetched_at, roster)
        self._goal_events[game_id] = (fetched_at, team_events)
        self._submit(
            ("goal_detail", game_id), lambda: self._detect_goal_detail(game_id, team_events)
        )

    def _detect_goal_detail(self, game_id: int, events: tuple[GoalEvent, ...]) -> None:
        """A followed team's scoring array grew by one entry: show it, once.

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
            self._goal_detail = (
                game_id,
                self.monotonic(),
                self._enrich_goal_detail(events[previous]),
            )

    def _roster_fresh(self, team: str) -> bool:
        fetched_at = self._team_rosters.get(team, (None, {}))[0]
        return fetched_at is not None and self.monotonic() - fetched_at < ROSTER_TTL_SECONDS

    def _team_roster(self, team: str) -> dict[int, PlayerSeasonDetail]:
        """Jersey number + season points for ``team``, from the cache only (#124).

        Never fetches: ``_fetch_goal_events`` fetches the roster on the worker,
        lazily -- only once a new goal for that team has appeared, not
        proactively for every team on the schedule -- and a failed fetch
        leaves whatever was cached before (possibly still nothing), same
        precedent as ``next_favourite_game``/``conference_standings``.
        """
        return self._team_rosters.get(team, (None, {}))[1]

    def _enrich_goal_detail(self, event: GoalEvent) -> GoalEvent:
        """Fill in scorer_sweater_number/scorer_points, if the roster fetch works out.

        Left as-is (both stay None) on a failed fetch or a scorer missing
        from the roster response -- the screen still shows fine without
        them, same graceful-degradation precedent as everything else here.
        """
        detail = self._team_roster(event.team_abbrev).get(event.scorer_player_id)
        if detail is None:
            return event
        return dataclasses.replace(
            event, scorer_sweater_number=detail.sweater_number, scorer_points=detail.points
        )

    # -- penalties (#340) ---------------------------------------------------

    def refresh_penalties(self) -> None:
        """Poll the favourite's live game for new penalties, for either team.

        Same landing request and ``live_poll_seconds`` cadence as the scorer
        poll (no new endpoint), skipped in intermission and the shootout.
        Scoped to the favourite's own game only; an opponent's penalty is
        news too, so both teams count there.
        """
        favourite = self._hockey_cfg().favourite_team
        if not favourite:
            return
        now = self.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        for game in self._api_games():
            if not game.is_live or not game.involves(favourite):
                continue
            fetched = self._penalty_fetched.get(game.id)
            if fetched is not None and now - fetched < interval:
                continue
            self._penalty_fetched[game.id] = now
            if game.in_intermission or game.in_shootout:
                continue
            self.fetcher.submit(
                ("penalty", game.id),
                lambda i=game.id: self.client.penalties(i),
                lambda p, e, i=game.id: self._on_penalties(i, p, e),
            )

    def _on_penalties(
        self, game_id: int, penalties: tuple[Penalty, ...] | None, error: Exception | None
    ) -> None:
        if error is not None or penalties is None:
            log.debug("Penalty fetch for %s failed: %s", game_id, error)
            return
        self._submit(("penalty", game_id), lambda: self._detect_penalties(game_id, penalties))

    def _detect_penalties(self, game_id: int, penalties: tuple[Penalty, ...]) -> None:
        """Announce the newest penalty not seen before, once.

        The first fetch for a game only records what is already there. If
        several arrive in one poll only the last is shown; all are recorded.
        """
        keys = {p.key for p in penalties}
        seen = self._seen_penalties.get(game_id)
        if seen is None:
            self._seen_penalties[game_id] = keys
            return
        fresh = [p for p in penalties if p.key not in seen]
        seen |= keys
        if fresh:
            self._penalty = (game_id, self.monotonic(), fresh[-1])

    def _penalty_override(self) -> Scene | None:
        if self._penalty is None:
            return None
        game_id, started, penalty = self._penalty
        if self.monotonic() - started >= penalty_screen.TOTAL_SECONDS:
            return None
        game = next((g for g in self.games if g.id == game_id), None)
        if game is None or game.in_shootout or game.is_final:
            return None
        return Scene("penalty", game, penalty=penalty)

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
        favourite = self._hockey_cfg().favourite_team
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
            self.fetcher.submit(
                ("three_stars", game_id),
                lambda i=game_id: self.client.three_stars(i),
                lambda s, e, i=game_id: self._on_three_stars(i, s, e),
            )

    def _on_three_stars(
        self, game_id: int, stars: tuple[Star, ...] | None, error: Exception | None
    ) -> None:
        if error is not None:
            log.debug("Three stars fetch for %s failed: %s", game_id, error)
            return
        if not stars or game_id in self._three_stars_shown:
            return  # not named yet (retried next interval), or already shown
        if game_id not in self._three_stars_pending:
            return  # pruned or timed out while this was in flight
        del self._three_stars_pending[game_id]
        self._three_stars_shown.add(game_id)
        self._three_stars = (game_id, self.monotonic() + self._blowout_remaining(), stars)

    def _note_blowout(self, game: Game, *, watched: bool) -> None:
        """Arm the blowout flash (#326) when a game we watched ends as one."""
        favourite = self._hockey_cfg().favourite_team
        if (
            watched
            and game.id not in self._blowout_shown
            and blowout.is_blowout_loss(game, favourite)
        ):
            self._blowout_shown.add(game.id)
            self._blowout = (game.id, self.monotonic())

    def _blowout_remaining(self) -> float:
        if self._blowout is None:
            return 0.0
        return max(0.0, self._blowout[1] + blowout.SECONDS - self.monotonic())

    def _blowout_override(self) -> Scene | None:
        if self._blowout is None or self._blowout_remaining() <= 0:
            return None
        game = next((g for g in self.games if g.id == self._blowout[0]), None)
        return None if game is None else Scene("blowout", game)

    def refresh_intermission_stats(self) -> None:
        """Fetch the team stats for the favourite's game while it sits in an intermission.

        Only that game, only then: one ``right-rail`` request when the intermission starts and one
        a minute while it lasts (the numbers do not move without play), a failed one retried after
        ``INTERMISSION_STATS_RETRY_SECONDS``. Stats for any other game are forgotten. Runs on the
        fetch worker; the render loop never waits for it.
        """
        game = self.favourite_game_today()
        if game is None or not game.is_live or not game.in_intermission or game.in_shootout:
            self._int_stats.clear()
            self._int_stats_tried.clear()
            return
        self._int_stats = {k: v for k, v in self._int_stats.items() if k == game.id}
        now = self.monotonic()
        have = self._int_stats.get(game.id)
        if have is not None and now - have[0] < INTERMISSION_STATS_REFRESH_SECONDS:
            return
        tried = self._int_stats_tried.get(game.id)
        if tried is not None and now - tried < INTERMISSION_STATS_RETRY_SECONDS:
            return
        self._int_stats_tried[game.id] = now
        self.fetcher.submit(
            ("int_stats", game.id),
            lambda i=game.id: self.client.game_stats(i),
            lambda s, e, i=game.id: self._on_intermission_stats(i, s, e),
        )

    def _on_intermission_stats(
        self, game_id: int, stats: GameStats | None, error: Exception | None
    ) -> None:
        if error is not None or stats is None:
            log.debug("Intermission stats for %s unavailable: %s", game_id, error)
            return
        self._int_stats[game_id] = (self.monotonic(), stats)

    def _intermission_scene(self, scene: Scene) -> Scene | None:
        """The stats table in place of the favourite's game scene while it is in an intermission
        (nothing else is moving), once its stats have arrived; else ``None`` and the game scene
        stays. The page is a pure function of the clock."""
        game = scene.game
        if game is None or not game.in_intermission or game.in_shootout:
            return None
        if not game.involves(self._hockey_cfg().favourite_team):
            return None
        have = self._int_stats.get(game.id)
        if have is None:
            return None
        stats = have[1]
        if not stats.pages:
            return None
        # The page count is the renderer's (it depends on the panel), so this is just the tick.
        tick = int(self.monotonic() // INTERMISSION_PAGE_SECONDS)
        return Scene("intermission", game, stats=stats, stats_page=tick)

    def _three_stars_override(self) -> Scene | None:
        if self._three_stars is None:
            return None
        stars_game_id, shown_at, stars = self._three_stars
        if self.monotonic() - shown_at >= self.settings.scoreboard.three_stars_seconds:
            return None
        game = next((g for g in self.games if g.id == stars_game_id), None)
        if game is None:
            return None
        return Scene("three_stars", game, stars=stars)

    # -- favourite mode --------------------------------------------------

    def favourite_game_today(self) -> Game | None:
        favourite = self._hockey_cfg().favourite_team
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
        favourite = self._hockey_cfg().favourite_team
        if not favourite:
            return None
        now_mono = self.monotonic()
        stale = self._schedule is None or now_mono - self._schedule[0] > SCHEDULE_TTL_SECONDS
        if allow_fetch and stale and now_mono >= self._schedule_retry_after:
            self.fetcher.submit(
                ("schedule", favourite),
                lambda: self.client.schedule(favourite),
                lambda s, e: self._on_schedule(favourite, now_mono, s, e),
            )
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

    def _on_schedule(
        self, team: str, fetched_at: float, games: list[Game] | None, error: Exception | None
    ) -> None:
        if team != self._hockey_cfg().favourite_team:
            return  # the favourite changed while this was in flight: it is the old team's
        if error is not None or games is None:
            log.warning("Schedule fetch failed: %s", error)
            self._record_error(f"schedule fetch: {error}")
            self._schedule_retry_after = fetched_at + SCHEDULE_TTL_SECONDS
            return
        self._schedule = (fetched_at, games)

    def _refresh_standings(self, *, allow_fetch: bool = True) -> list[StandingsRow] | None:
        """League standings, cached for ``STANDINGS_TTL_SECONDS`` like the schedule.

        ``allow_fetch=False`` answers from cache only, same reasoning as
        ``next_favourite_game`` -- for the status page (#61).
        """
        now_mono = self.monotonic()
        stale = self._standings is None or now_mono - self._standings[0] > STANDINGS_TTL_SECONDS
        if allow_fetch and stale and now_mono >= self._standings_retry_after:
            self.fetcher.submit(
                "standings",
                self.client.standings,
                lambda r, e: self._on_standings(now_mono, r, e),
            )
        if self._standings is None:
            return None
        return self._standings[1]

    def _on_standings(
        self, fetched_at: float, rows: list[StandingsRow] | None, error: Exception | None
    ) -> None:
        if error is not None or rows is None:
            log.warning("Standings fetch failed: %s", error)
            self._record_error(f"standings fetch: {error}")
            self._standings_retry_after = fetched_at + STANDINGS_TTL_SECONDS
            return
        self._standings = (fetched_at, rows)

    def _standings_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's conference neighbourhood, or None if there's nothing to show.

        Suppressed entirely until the favourite has actually played a game
        this season (#40): the standings endpoint keeps serving last
        season's final table through the whole off-season rather than an
        empty result, and ``games_played`` is the only signal available to
        tell the two apart.

        Deliberately does NOT also gate on ``cfg.show_standings`` here (it
        used to): that field now only controls whether ``standings`` is
        included in the *derived default* rotation (``_default_rotation()``,
        for a board with no explicit ``[[rotation]]``) -- checking it again
        in this method meant an explicit ``[[rotation]]`` entry for
        ``standings`` could be silently defeated by a stale
        ``show_standings`` toggle left over from before the board migrated,
        which contradicts #150/#151's whole point of the rotation list
        being the authoritative, admin-editable source of truth.
        """
        cfg = self._hockey_cfg()
        favourite = cfg.favourite_team
        if not favourite:
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
        return Scene(
            "standings",
            standings=tuple(window),
            playoff_cut=self._line(window, playoff_cut(window)),
        )

    def _conference_leaders_scene(
        self, conference: str, *, allow_fetch: bool = True
    ) -> Scene | None:
        """The whole of one conference (#200), or None with no standings yet.

        Scrolled by ``_split_slot`` over the slot's dwell.

        Deliberately not gated on anyone's ``games_played``: the owner chose
        to just show whatever the latest table says.
        """
        rows = self._refresh_standings(allow_fetch=allow_fetch)
        if not rows:
            return None
        table = conference_standings(rows, conference)
        if not table:
            return None
        return Scene(
            "conference_leaders",
            standings=tuple(table),
            playoff_cut=self._line(table, playoff_cut(table)),
        )

    @staticmethod
    def _line(table: list[StandingsRow], cut: int | None) -> int | None:
        """``cut`` once the season is far enough along for a playoff line (#298)."""
        return cut if playoff_line_ready(table) else None

    def _division_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's whole division (#296), or None to skip the slot.

        Gated on the favourite having played, like ``standings``: the API
        serves last season's final table all through the off-season.
        """
        favourite = self._hockey_cfg().favourite_team
        if not favourite:
            return None
        rows = self._refresh_standings(allow_fetch=allow_fetch)
        if not rows:
            return None
        favourite_row = next((r for r in rows if r.abbrev == favourite), None)
        if favourite_row is None or favourite_row.games_played <= 0:
            return None
        table = division_standings(rows, favourite_row.division)
        if not table:
            return None
        cut = DIVISION_SPOTS if len(table) > DIVISION_SPOTS else None
        return Scene("division", standings=tuple(table), playoff_cut=self._line(table, cut))

    def _wildcard_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's conference wild-card race (#298), or None to skip the slot.

        Gated on the favourite having played, like ``standings``/``division``.
        """
        favourite = self._hockey_cfg().favourite_team
        if not favourite:
            return None
        rows = self._refresh_standings(allow_fetch=allow_fetch)
        if not rows:
            return None
        favourite_row = next((r for r in rows if r.abbrev == favourite), None)
        if favourite_row is None or favourite_row.games_played <= 0:
            return None
        table = wildcard_standings(rows, favourite_row.conference)
        if not table:
            return None
        cut = WILDCARD_SPOTS if len(table) > WILDCARD_SPOTS else None
        return Scene("wildcard", standings=tuple(table), playoff_cut=self._line(table, cut))

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
        key = ("season_series", game_id)
        if allow_fetch and stale and now_mono >= retry_after and not self.fetcher.pending(key):
            # Only ever the one upcoming matchup worth remembering.
            self._season_series = {k: v for k, v in self._season_series.items() if k == game_id}
            self._season_series_retry_after = {}
            self.fetcher.submit(
                key,
                lambda: self.client.season_series(game_id),
                lambda r, e: self._on_season_series(game_id, now_mono, r, e),
            )
            entry = self._season_series.get(game_id)
        return entry[1] if entry is not None else None

    def _on_season_series(
        self,
        game_id: int,
        fetched_at: float,
        record: SeasonSeriesRecord | None,
        error: Exception | None,
    ) -> None:
        if error is not None:
            log.warning("Season series fetch for %s failed: %s", game_id, error)
            self._record_error(f"season series fetch: {error}")
            self._season_series_retry_after[game_id] = fetched_at + SEASON_SERIES_TTL_SECONDS
            return
        self._season_series[game_id] = (fetched_at, record)

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
        favourite = self._hockey_cfg().favourite_team
        meetings = tuple(
            result for m in record.meetings if (result := m.result_for(favourite)) is not None
        )
        return Scene("matchup", upcoming, season_series=record, meetings=meetings)

    def _split_slot(self, scene: Scene, offset: float, seconds: float) -> Scene:
        """One rotation slot's scene at ``offset`` seconds into its ``seconds`` dwell."""
        if scene.kind == "scores":
            return self._page_scores(scene, offset, seconds)
        if scene.kind in SCROLLING_KINDS:
            return self._scroll_conference(scene, offset, seconds)
        return self._split_matchup(scene, offset, seconds)

    def _slot_seconds(self, scene: Scene, configured: float) -> float:
        """A scrolling table's slot lasts as long as a readable scroll needs.

        The configured seconds is a minimum there, not an exact length.
        """
        if scene.kind not in SCROLLING_KINDS:
            return configured
        return self.renderer.standings_scroll_seconds(len(scene.standings), configured)

    def _scroll_conference(self, scene: Scene, offset: float, seconds: float) -> Scene:
        """Scroll the conference table down over the slot's dwell."""
        r = self.renderer
        rows = len(scene.standings)
        px = r.standings_scroll_px(rows, offset, seconds)
        hold = min(r.SCROLL_HOLD_SECONDS, seconds / 4)
        moving = r.standings_scroll_range(rows) > 0 and hold <= offset < seconds - hold
        return dataclasses.replace(scene, scroll_px=px, scrolling=moving)

    def _page_scores(self, scene: Scene, offset: float, seconds: float) -> Scene:
        """The ``scores`` slot's dwell is shared evenly by its grid pages (#269)."""
        per_page = self.renderer.scores_per_page()
        pages = math.ceil(len(scene.games) / per_page)
        page = min(pages - 1, int(offset * pages / seconds))
        return dataclasses.replace(
            scene, games=scene.games[page * per_page : (page + 1) * per_page]
        )

    @staticmethod
    def _split_matchup(scene: Scene, offset: float, seconds: float) -> Scene:
        """The second half of a matchup slot shows the meetings behind the tally (#168).

        One rotation entry, by the owner's choice, rather than a second
        screen to configure. With no finished meeting yet (a 0-0 tally) the
        tally keeps the whole slot.
        """
        if scene.kind != "matchup" or not scene.meetings or offset < seconds / 2:
            return scene
        return dataclasses.replace(scene, kind="matchup_meetings")

    def _refresh_leaders(self, team: str, *, allow_fetch: bool = True) -> TeamLeaders | None:
        """The favourite's stat leaders, cached ``LEADERS_TTL_SECONDS`` like standings.

        A cache for a different team counts as stale, so a live favourite
        switch never shows the old team's players. A failed refresh keeps
        serving what was cached for the same team.
        """
        now_mono = self.monotonic()
        entry = self._leaders
        if entry is not None and entry[0] != team:
            entry = self._leaders = None
        stale = entry is None or now_mono - entry[1] > LEADERS_TTL_SECONDS
        if allow_fetch and stale and now_mono >= self._leaders_retry_after:
            self.fetcher.submit(
                ("club_stats", team),
                lambda: self.client.club_stats(team),
                lambda r, e: self._on_club_stats(team, now_mono, r, e),
            )
            entry = self._leaders
            if entry is not None and entry[0] != team:
                entry = None
        return entry[2] if entry is not None else None

    def _on_club_stats(
        self, team: str, fetched_at: float, stats: ClubStats | None, error: Exception | None
    ) -> None:
        if team != self._hockey_cfg().favourite_team:
            return  # the favourite changed while this was in flight
        if error is not None or stats is None:
            log.warning("Club stats fetch failed: %s", error)
            self._record_error(f"club stats fetch: {error}")
            self._leaders_retry_after = fetched_at + LEADERS_TTL_SECONDS
            return
        self._leaders = (team, fetched_at, team_leaders(stats, self._rng))

    def _leaders_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        """The favourite's top players (#201), or None (skipped, never blank).

        None with no favourite, before the first fetch lands, or while the
        API's arrays are empty (pre-season). There's deliberately no minimum
        games-played floor: early on everyone sits at zero and a random
        leader is shown rather than hiding the screen.
        """
        favourite = self._hockey_cfg().favourite_team
        if not favourite:
            return None
        leaders = self._refresh_leaders(favourite, allow_fetch=allow_fetch)
        if leaders is None:
            return None
        return Scene("leaders", leaders=leaders)

    def _countdown_or_preview(self, upcoming: Game) -> Scene:
        cfg = self._hockey_cfg()
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
        cfg = self._hockey_cfg()
        entries = [RotationEntry("countdown_preview", cfg.rotate_seconds)]
        if cfg.show_standings:
            entries.append(RotationEntry("standings", cfg.rotate_seconds))
        if cfg.show_clock_between_games:
            entries.append(RotationEntry("clock", cfg.rotate_seconds))
        return entries

    def _unified_rotation(self) -> list[RotationEntry]:
        """The one idle rotation, both sports' screens: the configured ``[[rotation]]`` list, else
        each sport's default in the order of the lead teams' ranks."""
        if self.settings.rotation:
            return list(self.settings.rotation)
        order = self._priority().sports() or ["hockey", "football"]
        rows: list[RotationEntry] = []
        for sport in order:
            if sport == "hockey":
                rows += self._default_rotation()
            else:
                rows += [RotationEntry(s, sec) for s, sec in DEFAULT_FOOTBALL_ROTATION]
        return rows

    def _sport_rotation(self, sport: str) -> list[RotationEntry]:
        """The rows ``sport`` shows: its current segment's while the sports alternate, else its own
        screens (and the clock) of the one list, else its default."""
        if sport in self._segment_rows:
            return list(self._segment_rows[sport])
        if self.settings.rotation:
            rows = [
                e for e in self.settings.rotation if screen_sport(e.screen) in (sport, "shared")
            ]
            if rows:
                return rows
        if sport == "hockey":
            return self._default_rotation()
        return [RotationEntry(s, sec) for s, sec in DEFAULT_FOOTBALL_ROTATION]

    def _effective_rotation(self) -> list[RotationEntry]:
        return self._sport_rotation("hockey")

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
        if screen in ("top_west", "top_east"):
            # Resolved here so a board not listing them never needs the fetch.
            conference = "W" if screen == "top_west" else "E"
            return self._conference_leaders_scene(conference, allow_fetch=allow_fetch)
        if screen == "division":
            return self._division_scene(allow_fetch=allow_fetch)
        if screen == "wildcard":
            return self._wildcard_scene(allow_fetch=allow_fetch)
        if screen == "matchup":
            # Resolved here, not up front like standings, so a board without
            # "matchup" in its rotation never calls right-rail at all.
            return self._matchup_scene(upcoming, allow_fetch=allow_fetch)
        if screen == "leaders":
            # Resolved lazily like matchup: club-stats is never called unless listed.
            return self._leaders_scene(allow_fetch=allow_fetch)
        if screen == "holiday":
            return self._holiday_screen_scene()
        if screen == "address":
            return self._address_scene()
        if screen == "scores_grid":
            return Scene("scores", games=tuple(self.games)) if self.games else None
        return None

    def _holiday_screen_scene(self) -> Scene | None:
        """The active holiday's own screen (#243), or None to skip the slot.

        Two have one: the turkey, Nov 1 through US Thanksgiving Day, and the tree, Dec 1-25.
        Each needs Holiday Cheer on and its own theme ticked -- the same switches as its
        overlay -- and the two windows never overlap.
        """
        cfg = self.settings.holiday
        if not cfg.enabled:
            return None
        today = self.clock().astimezone(self.tz).date()
        if "thanksgiving" in cfg.themes and thanksgiving_countdown(today):
            return Scene("thanksgiving")
        if "christmas" in cfg.themes and christmas_countdown(today):
            return Scene("christmas_tree")
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
            (scene, self._slot_seconds(scene, entry.seconds))
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
        clock = self.monotonic() - self._idle_origin
        if len(slots) == 1:
            scene, seconds = slots[0]
            return self._split_slot(scene, clock % seconds, seconds)
        total = sum(seconds for _, seconds in slots)
        position = clock % total
        start = 0.0
        for scene, seconds in slots:
            if position < start + seconds:
                return self._split_slot(scene, position - start, seconds)
            start += seconds
        return slots[-1][0]

    def select_scene(self, *, allow_fetch: bool = True) -> Scene:
        """Decide what to show; the draw step only renders the answer.

        ``allow_fetch=False`` (the status page, #61) must never trigger a
        network call or mutate ``_schedule``/``_standings``/``last_error``
        from the status thread -- that would race the main loop into
        duplicate fetches, or block a "read-only" page on a slow hockey
        response.

        wifi_join wins over even ap_setup (#133): while a join attempt's
        outcome is still showing, that's more current than "here's how to
        join" -- notably during a failed attempt's retry window, when
        scoreboard-setup-ap has already brought the AP (and its own
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
        if self._address_until is not None and self.monotonic() < self._address_until:
            address_scene = self._address_scene()
            if address_scene is not None:
                return address_scene
        if self._sport == "football" and self._football is not None:
            return self._football.scene()
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
        matrix = self._qr_matrix(payload, "AP setup")
        self._ap_qr_cache = (cache_key, matrix)
        return matrix

    @staticmethod
    def _qr_matrix(payload: str, what: str) -> tuple[tuple[bool, ...], ...] | None:
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
            return tuple(tuple(bool(v) for v in row) for row in qr.get_matrix())
        except Exception as exc:
            log.warning("Could not build %s QR code: %s", what, exc)
            return None

    # -- Admin page address (#293) -----------------------------------------

    def _build_admin(self) -> AdminServer | None:
        """The admin server for the current settings (not started).

        Normally on ``status.port`` plus the ``alias_port`` listener. While the
        WiFi setup page holds port 80 (``_admin_yielded``) it is on the alias
        port alone, or off if that is disabled -- the setup page is what a
        phone on the AP needs then, and both can't have the port.
        """
        cfg = self.settings.status
        if not cfg.enabled:
            return None
        port, alias = cfg.port, cfg.alias_port
        if self._admin_yielded:
            if not cfg.alias_port:
                return None
            port, alias = cfg.alias_port, 0
        return AdminServer(
            config_path=str(self.settings.source_path or DEFAULT_CONFIG_PATHS[0]),
            port=port,
            snapshot=self.status_snapshot,
            demo_setter=self.set_demo_mode,
            mirror=self.mirror,
            alias_port=alias,
            cache_items=self.cache_items,
            cache_clearer=self.request_cache_clear,
        )

    def _set_admin_yield(self, yielded: bool) -> None:
        """Hand port 80 to (or take it back from) the WiFi setup page (#292).

        Must stop the admin listener before the setup server binds, and
        rebuild it only after the setup server has released the port.
        """
        if yielded == self._admin_yielded or not self._admin_owned:
            return
        if self.admin_server is not None:
            self.admin_server.stop()
        self._admin_yielded = yielded
        self.admin_server = self._build_admin()
        if self.admin_server is not None and self._running:
            self.admin_server.start()

    def _board_name(self) -> str | None:
        """``<hostname>.local`` for the panel and status page, None if unknown."""
        name = self._hostname_lookup().strip().lower()
        return f"{name}.local" if valid_hostname_label(name) else None

    def _sync_alias(self) -> None:
        """Keep plain ``scoreboard.local`` published while it's free (#292)."""
        if self.alias_publisher is None:
            return
        cfg = self.settings.status
        own = self._hostname_lookup().strip().lower()
        wanted = cfg.enabled and cfg.local_alias and own != "scoreboard"
        self.alias_publisher.sync(wanted, self._current_ip())

    def _current_ip(self) -> str | None:
        now = self.monotonic()
        if self._ip_cache is None or now - self._ip_cache[0] >= IP_CACHE_SECONDS:
            self._ip_cache = (now, self._ip_lookup())
        return self._ip_cache[1]

    def _track_address(self) -> None:
        """Start the address screen's minute when the board first gets online.

        Keyed on "has a default route" (the same test the setup-AP script
        uses), not on the Wi-Fi join state, so an Ethernet-only boot gets it
        too. Mutates state, so only run()'s own loop calls it, never the
        admin server's status thread.
        """
        has_ip = self._current_ip() is not None
        if has_ip and not self._had_ip:
            self._address_until = self.monotonic() + ADDRESS_SHOW_SECONDS
        self._had_ip = has_ip

    def _address_scene(self) -> Scene | None:
        """Where to reach the admin page, or None with no address or no page.

        The name (``<name>.local``, #292) leads and the IP is the fallback for
        a device that can't resolve it. The QR always carries the IP URL.
        """
        cfg = self.settings.status
        ip = self._current_ip()
        if not cfg.enabled or ip is None:
            return None
        url = f"http://{ip}" if cfg.port == 80 else f"http://{ip}:{cfg.port}"
        if self._address_qr_cache is None or self._address_qr_cache[0] != url:
            self._address_qr_cache = (url, self._qr_matrix(url, "admin address"))
        return Scene(
            "address",
            address_ip=ip,
            address_port=cfg.port,
            address_qr=self._address_qr_cache[1],
            address_name=self._board_name(),
        )

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
        # Port 80 is shared by name only: the admin page steps back to its
        # alias port while the setup page runs, and returns after (#292).
        self._set_admin_yield(
            desired is not None and cfg.port == self.settings.status.port,
        )
        if desired is None:
            # The AP setup flow is over (WiFi joined, or setup disabled) --
            # any hardware_mapping trial (#172) belongs to this session
            # only. A later AP session on the same boot (WiFi drops hours
            # later) must not inherit a stale "still testing" gate from one
            # that already ended.
            self.hw_mapping_trial_path.unlink(missing_ok=True)
            return
        self.setup_server = SetupServer(
            networks=self._cached_setup_networks,
            on_submit=self._on_setup_submission,
            port=cfg.port,
            panel_state=self._panel_check_state,
            on_panel_confirm=self._on_panel_confirm,
            on_panel_next=self._on_panel_next,
        )
        try:
            self.setup_server.start()
        except OSError as exc:
            log.warning("Could not start WiFi setup server: %s", exc)
            self.setup_server = None

    def _cached_setup_networks(self) -> list[str]:
        """The nearby-network snapshot scoreboard-setup-ap cached before AP mode came up."""
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

    # -- display check (#172) ----------------------------------------------

    def _panel_check_state(self) -> tuple[str, bool, bool]:
        """(configured hardware_mapping, whether a trial is unconfirmed,
        whether every candidate has now been tried) -- read by SetupServer's
        GET / to render the display check card."""
        tried = self._tried_mappings()
        tried_all = tried is not None and set(PANEL_HARDWARE_MAPPING_CHOICES) <= set(tried)
        return (self.settings.panel.hardware_mapping, tried is not None, tried_all)

    def _tried_mappings(self) -> list[str] | None:
        """The mappings this trial has tried, or None with no trial running.

        An unreadable marker still counts as a trial (the gate must hold)
        that has only tried the current mapping.
        """
        try:
            raw = self.hw_mapping_trial_path.read_text()
        except FileNotFoundError:
            return None
        except OSError:
            return [self.settings.panel.hardware_mapping]
        try:
            tried = json.loads(raw)
        except json.JSONDecodeError:
            tried = None
        if not isinstance(tried, list) or not all(isinstance(t, str) for t in tried):
            return [self.settings.panel.hardware_mapping]
        return tried

    def _on_panel_next(self, chosen: str | None = None) -> str | None:
        """ "No, try the next option" (or a board picked by name): save that
        mapping and restart so the panel actually picks it up, returning it
        on success. ``chosen`` must be one of the documented choices.

        The trial marker is written *before* the mapping changes: if it
        can't be, nothing changes and nothing restarts, rather than leaving
        a new mapping in place with no gate and no "is it working?" card.

        A throwaway Settings instance, not self.settings -- same reasoning
        as admin_server.py's saves: mutating the live app's Settings from
        this HTTP-handling thread while the main loop is mid-iteration
        reading it would be an undefined interleaving, and it is moot anyway
        once the restart below lands, since the new process loads settings
        from disk itself.
        """
        if self.settings.source_path is None:
            log.warning("No config file loaded; cannot try a different hardware_mapping")
            return None
        if chosen is not None and chosen not in PANEL_HARDWARE_MAPPING_CHOICES:
            log.warning("Ignoring unknown hardware_mapping %r from the setup page", chosen)
            return None
        current = self.settings.panel.hardware_mapping
        new_mapping = chosen or next_hardware_mapping(current)
        previous = self._tried_mappings()
        tried = [*(previous or [current]), new_mapping]
        try:
            self.hw_mapping_trial_path.write_text(json.dumps(tried))
        except OSError as exc:
            log.warning("Could not write hardware_mapping trial marker: %s", exc)
            return None
        try:
            Settings.from_toml(self.settings.source_path).save(
                {"panel": {"hardware_mapping": new_mapping}}
            )
        except (OSError, tomllib.TOMLDecodeError, ConfigWriteError) as exc:
            log.warning("Could not save hardware_mapping %r: %s", new_mapping, exc)
            self._restore_trial_marker(previous)
            return None
        self._restart_service()
        return new_mapping

    def _restore_trial_marker(self, previous: list[str] | None) -> None:
        """Put the marker back as it was before a save that didn't happen."""
        try:
            if previous is None:
                self.hw_mapping_trial_path.unlink(missing_ok=True)
            else:
                self.hw_mapping_trial_path.write_text(json.dumps(previous))
        except OSError as exc:
            log.warning("Could not restore hardware_mapping trial marker: %s", exc)

    def _on_panel_confirm(self) -> None:
        """ "Yes, it's working": end the trial, ungating the WiFi form."""
        self.hw_mapping_trial_path.unlink(missing_ok=True)

    def _select_base_scene(self, *, allow_fetch: bool = True) -> Scene:
        if self.last_success is None:
            return Scene("connecting")
        if self.is_stale():
            return Scene("no_data")
        scene = self._favourite_scene(allow_fetch=allow_fetch)
        if scene is not None:
            return scene
        if self._scores_grid_fallback():
            per_page = self.renderer.scores_per_page()
            return Scene("scores", games=tuple(self.games[self.index : self.index + per_page]))
        if self.games:
            return Scene("game", self.games[self.index])
        return Scene("clock" if self.settings.scoreboard.show_clock_when_idle else "no_games")

    def _apply_goal_override(self, scene: Scene) -> Scene:
        """Show the goal (or later, goal_detail) screen for a followed team's goal.

        Only ever replaces a "game" scene -- never a countdown, preview or
        other idle screen. The red zone (#260): while followed teams' live
        games take turns on screen, a goal in any of them jumps straight to
        that game, whichever one is up -- and so do the favourite's three
        stars, or a live followed game's turn could swallow them. A game no followed team is in
        (today's-games rotation) is never interrupted.
        For a followed team's goal, goal_detail wins when both are pending:
        it fires strictly after the goal scene's own score-increase trigger
        (see refresh_goal_details), so by the time it is ready there is no
        point re-showing the plain "GOAL" + score flash for the same goal.
        The favourite's goal is the exception: its animated goal light is the
        celebration, so it plays its full goal_flash_seconds and the scorer
        screen follows it (see _goal_detail_override). The scorer is usually
        ready within seconds, which used to cut the light to about 2s (#338).

        three_stars (#156) is the last layer: it only arms once the game is
        final, so it's temporally disjoint from the other two in practice.
        If a late game-winner's flash does overlap it, the goal screens win
        and three_stars just loses that slice of its own window.
        """
        if scene.kind != "game" or not self._is_followed(scene.game):
            return scene
        if scene.game.in_shootout:
            # The headline score only moves when a shootout is decided, so a
            # favourite "goal" here is really the win: the horn already
            # played (_on_goal), but GOAL would cover the final grid.
            stars = self._three_stars_override()
            return stars if stars is not None else scene
        detail = self._goal_detail_override()
        if detail is not None:
            return detail
        if self.last_goal is not None:
            goal_game_id, goal_time, goal_team = self.last_goal
            goal_game = next((g for g in self.games if g.id == goal_game_id), None)
            if (
                goal_game is not None
                and not goal_game.in_shootout  # a shootout win, not a goal (#259)
                and self.monotonic() - goal_time < self.settings.scoreboard.goal_flash_seconds
            ):
                return Scene("goal", goal_game, goal_team=goal_team)
        penalty = self._penalty_override()
        if penalty is not None:
            return penalty
        flash = self._blowout_override()
        if flash is not None:
            return flash
        stars = self._three_stars_override()
        if stars is not None:
            return stars
        return self._intermission_scene(scene) or scene

    def _goal_detail_override(self) -> Scene | None:
        if self._goal_detail is None:
            return None
        detail_game_id, detail_time, event = self._goal_detail
        now = self.monotonic()
        start = detail_time
        light_end = self._goal_light_end(detail_game_id)
        if light_end is not None and detail_time < light_end:
            # The favourite's goal light plays its whole window first; the
            # scorer screen then gets its own full window from the light's end.
            if now < light_end:
                return None
            start = light_end
        if now - start >= self.settings.scoreboard.goal_detail_seconds:
            return None
        game = next((g for g in self.games if g.id == detail_game_id), None)
        if game is None or game.in_shootout:
            return None
        return Scene("goal_detail", game, goal_event=event)

    def _goal_light_end(self, game_id: int) -> float | None:
        """When the favourite's animated goal light in ``game_id`` ends
        (monotonic), or ``None`` if the last goal there wasn't the favourite's.

        Only the favourite's goal is held ahead of the scorer screen: a
        followed team's goal is a quick static flash (#260), which the scorer
        screen still replaces as soon as it is ready."""
        if self.last_goal is None:
            return None
        goal_game_id, goal_time, goal_team = self.last_goal
        favourite = self._hockey_cfg().favourite_team
        if goal_game_id != game_id or not favourite or goal_team != favourite:
            return None
        return goal_time + self.settings.scoreboard.goal_flash_seconds

    def _favourite_scene(self, *, allow_fetch: bool = True) -> Scene | None:
        cfg = self._hockey_cfg()
        turns = self._followed_turns()
        if turns:
            position = self.monotonic() % sum(seconds for _, seconds in turns)
            for game, seconds in turns:
                if position < seconds:
                    return self._turn_scene(game)
                position -= seconds
            return self._turn_scene(turns[-1][0])
        if not cfg.favourite_team:
            return None
        today = self.favourite_game_today()
        upcoming = (
            today
            if today is not None and today.is_pregame
            else self.next_favourite_game(allow_fetch=allow_fetch)
        )
        standings = self._standings_scene(allow_fetch=allow_fetch)
        return self._rotate_idle_scenes(upcoming, standings, allow_fetch=allow_fetch)

    def _turn_scene(self, game: Game) -> Scene:
        """A turn's screen: a game not yet started is its countdown/preview."""
        return self._countdown_or_preview(game) if game.is_pregame else Scene("game", game)

    def _followed_turns(self) -> list[tuple[Game, float]]:
        """Which followed games are on screen now, each with its dwell in seconds.

        Primary-first, by the owner's call on #260: while the favourite is
        live and the puck is in play, its game holds the screen alone --
        other followed teams only appear when they score (the red zone,
        ``_apply_goal_override``). During the favourite's intermission, or
        while its final is held (``final_hold_minutes``, with its three
        stars), the other live followed games take ``rotate_seconds``
        turns, and the favourite's own screen drops in for a quick
        ``FAVOURITE_QUICK_TURN`` share of that each cycle so its score stays
        in view. With the favourite not playing, live followed games take
        equal turns. An ``also_follow`` team's game leaves the cycle the
        moment it ends; only the favourite's final is held.
        """
        cfg = self._hockey_cfg()
        today = self.favourite_game_today()
        favourite_game = None
        if today is not None and today.is_live:
            if not today.in_intermission:
                return [(today, cfg.rotate_seconds)]
            favourite_game = today
        elif today is not None and today.is_final:
            ended = self.ended_at.get(today.id)
            if ended is not None and self.clock() - ended < timedelta(
                minutes=cfg.final_hold_minutes
            ):
                favourite_game = today
        others = [
            (g, cfg.rotate_seconds)
            for g in self.games
            if g.is_live and g is not today and self._is_followed(g)
        ]
        if favourite_game is None and today is not None and today.is_pregame and others:
            # A followed team already live must not erase the favourite's
            # countdown/preview for the hours before puck drop.
            favourite_game = today
        if favourite_game is None:
            return others
        return [(favourite_game, cfg.rotate_seconds * FAVOURITE_QUICK_TURN), *others]

    def situation_targets(self) -> list[Game]:
        """Live games worth a second request: followed teams' and the on-screen one.

        Everything else shows even strength; that is the trade for not
        hammering the landing endpoint once per live game every poll.
        """
        targets = [g for g in self._api_games() if g.is_live and self._is_followed(g)]
        if self._index_game_on_screen():
            current = self._api_game(self.games[self.index])
            if current.is_live and current not in targets:
                targets.append(current)
        return targets

    def _index_game_on_screen(self) -> bool:
        """Whether ``games[index]`` is the game being drawn (the one-at-a-time fallback).

        Not when the grid shows (no per-game situation), nor while a
        favourite/followed flow or the idle rotation owns the screen: those
        never read ``index``, so polling for it is wasted NHL traffic.
        """
        if not self.games or self._scores_grid_fallback():
            return False
        return self._favourite_scene(allow_fetch=False) is None

    def _api_game(self, game: Game) -> Game:
        """The API's current view of a (possibly delayed) game."""
        return next((g for g in self._api_games() if g.id == game.id), game)

    def refresh_situations(self) -> None:
        now = self.monotonic()
        interval = self.settings.scoreboard.live_poll_seconds
        wanted = {g.id: g for g in self.situation_targets()}
        for game_id in list(self.situations):
            if game_id not in wanted:
                del self.situations[game_id]
                self._shown_situations.pop(game_id, None)
        for game_id, game in wanted.items():
            fetched_at = self.situations.get(game_id, (None, None))[0]
            if fetched_at is not None and now - fetched_at < interval:
                continue
            if game.in_intermission or game.in_shootout:
                # No special teams in a shootout; refresh_shootouts() owns it.
                self.situations[game_id] = (now, None)
                self._submit(
                    ("situation", game_id), lambda i=game_id: self._show_situation(i, None)
                )
                continue
            self.fetcher.submit(
                ("situation", game_id),
                lambda i=game_id: self.client.situation(i),
                lambda s, e, i=game_id, t=now: self._on_situation(i, t, s, e),
            )

    def _on_situation(
        self, game_id: int, fetched_at: float, situation: Situation | None, error: Exception | None
    ) -> None:
        if error is not None:
            log.debug("Situation fetch for %s failed: %s", game_id, error)
            situation = self.situations.get(game_id, (None, None))[1]
        self.situations[game_id] = (fetched_at, situation)
        self._submit(
            ("situation", game_id), lambda i=game_id, s=situation: self._show_situation(i, s)
        )

    def _show_situation(self, game_id: int, situation: Situation | None) -> None:
        self._shown_situations[game_id] = situation

    def shootout_targets(self) -> list[Game]:
        """Shootout games to track: followed teams' and the on-screen one (#259, #260).

        Same scoping as situation_targets. A finished game stays a target
        until one fetch has landed after it ended, so the grid ends on the
        deciding shot rather than the last poll before the final horn.
        """
        candidates = [g for g in self._api_games() if self._is_followed(g)]
        if self._index_game_on_screen():
            candidates.append(self._api_game(self.games[self.index]))
        targets: list[Game] = []
        for game in candidates:
            if game in targets or not game.in_shootout:
                continue
            if game.is_live or (game.is_final and not self._shootout_settled(game)):
                targets.append(game)
        return targets

    def _shootout_settled(self, game: Game) -> bool:
        entry = self.shootouts.get(game.id)
        return entry is not None and entry[2]

    def refresh_shootouts(self) -> None:
        """Fetch each tracked shootout every ``shootout_poll_seconds`` (#259).

        A failed fetch keeps the last good grid on screen, like situations.
        """
        now = self.monotonic()
        interval = self.settings.scoreboard.shootout_poll_seconds
        current = {g.id for g in self._api_games()}
        for game_id in list(self.shootouts):
            if game_id not in current:
                del self.shootouts[game_id]
                self._shown_shootouts.pop(game_id, None)
        for game_id in list(self._shootout_seen):
            if game_id not in current:
                del self._shootout_seen[game_id]
        for game in self.shootout_targets():
            previous = self.shootouts.get(game.id, (None, None, False))
            if previous[0] is not None and now - previous[0] < interval:
                continue
            self.fetcher.submit(
                ("shootout", game.id),
                lambda i=game.id: self.client.shootout(i),
                lambda s, e, i=game.id, t=now, final=game.is_final: self._on_shootout(
                    i, t, final, s, e
                ),
            )

    def _on_shootout(
        self,
        game_id: int,
        fetched_at: float,
        is_final: bool,
        shootout: Shootout | None,
        error: Exception | None,
    ) -> None:
        if error is not None:
            log.debug("Shootout fetch for %s failed: %s", game_id, error)
            previous = self.shootouts.get(game_id, (None, None, False))
            self.shootouts[game_id] = (fetched_at, previous[1], previous[2])
            return
        self.shootouts[game_id] = (fetched_at, shootout, is_final)
        self._submit(("shootout", game_id), lambda i=game_id, s=shootout: self._show_shootout(i, s))

    def _show_shootout(self, game_id: int, shootout: Shootout | None) -> None:
        self._shown_shootouts[game_id] = shootout
        self._note_shootout_attempts(game_id, shootout, self.monotonic())

    def _note_shootout_attempts(self, game_id: int, shootout: Shootout | None, now: float) -> None:
        """Stamp each attempt with when we first saw it (#259).

        The first successful fetch for a game is the baseline: whatever is
        already there is marked ``None`` and never animates, same rule as
        goal detection. The stamp is poll arrival, but the animation is
        driven by the age against the clock at render time, so the 5s poll
        cadence doesn't show up as stutter.
        """
        seen = self._shootout_seen.get(game_id)
        baseline = seen is None
        if seen is None:
            seen = self._shootout_seen[game_id] = {}
        for attempt in shootout.attempts if shootout is not None else ():
            if attempt.sequence not in seen:
                seen[attempt.sequence] = None if baseline else now

    def shootout_ages(self, game_id: int) -> dict[int, float]:
        """Seconds since each still-animating attempt first appeared."""
        now = self.monotonic()
        window = self.renderer.SHOOTOUT_ANIM_SECONDS
        ages = {}
        for sequence, stamp in self._shootout_seen.get(game_id, {}).items():
            if stamp is not None and 0 <= now - stamp < window:
                ages[sequence] = now - stamp
        return ages

    def with_situation(self, game: Game) -> Game:
        situation = self._shown_situations.get(game.id)
        if situation is not None:
            game = dataclasses.replace(game, situation=situation)
        data = self._shown_shootouts.get(game.id)
        if data is not None and game.shootout is None:
            if self.april_fools_active():
                data = april_fools.swap_shootout(data)
            game = dataclasses.replace(game, shootout=data)
        return game

    def order(self, games: list[Game]) -> list[Game]:
        """Sort live-first, then optionally pin the favourite team to the front.

        The sort is repeated here rather than trusted from the client so that
        display order is a property of the app, not of whoever fetched.
        """
        games = sorted(games, key=Game.sort_key)
        favourite = self._hockey_cfg().favourite_team
        if not (favourite and self.settings.scoreboard.prefer_favourite):
            return games
        pinned = [g for g in games if g.involves(favourite)]
        rest = [g for g in games if not g.involves(favourite)]
        return pinned + rest

    def poll_interval(self) -> float:
        """Poll harder while a game is actually in progress."""
        cfg = self._hockey_cfg()
        games = self._api_games()
        if any(g.is_live and g.in_shootout for g in games):
            return min(cfg.shootout_poll_seconds, cfg.live_poll_seconds)
        if any(g.is_live and not g.in_intermission for g in games):
            return cfg.live_poll_seconds
        return cfg.poll_seconds

    def _scores_grid_fallback(self) -> bool:
        """Whether today's games cycle as grid pages rather than one at a time (#269).

        A single game keeps the full game scene: a grid of one is just a
        smaller version of it.
        """
        return self.settings.scoreboard.scores_grid and len(self.games) > 1

    def advance(self) -> None:
        if not self.games:
            return
        if self._scores_grid_fallback():
            # index is the first game of the current page.
            per_page = self.renderer.scores_per_page()
            pages = math.ceil(len(self.games) / per_page)
            self.index = (self.index // per_page + 1) % pages * per_page
            return
        self.index = (self.index + 1) % len(self.games)

    # -- output ----------------------------------------------------------

    def is_stale(self) -> bool:
        if self.last_success is None:
            return True
        return (self.monotonic() - self.last_success) > STALE_AFTER_SECONDS

    # -- status page (#48) ------------------------------------------------

    # -- the admin page's Cache tab ----------------------------------------------------

    def cache_items(self) -> list[dict[str, Any]]:
        """Everything cached, hockey's and football's, for the admin page to show (read-only; it
        runs on the admin thread, so it only copies what is already in memory)."""
        from .cache_view import item

        now = self.monotonic()
        out: list[dict[str, Any]] = []
        if self._standings is not None:
            at, rows = self._standings
            out.append(
                item(
                    "hockey:standings", "hockey", "Standings", now - at, f"{len(rows)} teams", rows
                )
            )
        if self._schedule is not None:
            at, games = self._schedule
            out.append(
                item(
                    "hockey:schedule",
                    "hockey",
                    f"{self._hockey_cfg().favourite_team or 'favourite'} season schedule",
                    now - at,
                    f"{len(games)} games",
                    games,
                )
            )
        for game_id, (at, record) in sorted(dict(self._season_series).items()):
            out.append(
                item(
                    f"hockey:season_series:{game_id}",
                    "hockey",
                    f"Season series, game {game_id}",
                    now - at,
                    "no tally" if record is None else "head-to-head tally",
                    record,
                )
            )
        if self._leaders is not None:
            team, at, leaders = self._leaders
            out.append(
                item(
                    "hockey:leaders",
                    "hockey",
                    f"{team} leaders",
                    now - at,
                    "none" if leaders is None else "goals, points, goalies",
                    leaders,
                )
            )
        for team, (at, roster) in sorted(dict(self._team_rosters).items()):
            out.append(
                item(
                    f"hockey:rosters:{team}",
                    "hockey",
                    f"{team} roster",
                    now - at,
                    f"{len(roster)} players",
                    roster,
                )
            )
        if self._football is not None:
            out += self._football.cache_items()
        return out

    def request_cache_clear(self, scope: str) -> bool:
        """Clear a scope of the cache (``all``, ``hockey``, ``football`` or one item's key).

        Called from the admin thread, so it only leaves a note: hockey's caches are cleared by the
        render thread, football's by its feed worker (which owns them). Returns whether the scope
        is one this board has."""
        from .cache_view import valid_scope

        keys = [i["key"] for i in self.cache_items()]
        if not valid_scope(scope, keys):
            return False
        self._cache_clears.add(scope)
        return True

    def _apply_cache_clears(self) -> None:
        if not self._cache_clears:
            return
        from .cache_view import matches

        scopes, self._cache_clears = set(self._cache_clears), set()

        def wanted(key: str) -> bool:
            return any(matches(s, key) for s in scopes)

        # An item key names one thing; clearing it clears its kind (a team's roster, say).
        def kind(prefix: str) -> bool:
            return wanted(prefix) or any(s.startswith(prefix + ":") for s in scopes)

        if kind("hockey:standings"):
            self._standings, self._standings_retry_after = None, 0.0
        if kind("hockey:schedule"):
            self._schedule, self._schedule_retry_after = None, 0.0
        if kind("hockey:season_series"):
            self._season_series, self._season_series_retry_after = {}, {}
        if kind("hockey:leaders"):
            self._leaders, self._leaders_retry_after = None, 0.0
        if kind("hockey:rosters"):
            self._team_rosters = {}
        log.info("Cache cleared: %s", ", ".join(sorted(scopes)))
        if self._football is not None:
            for scope in scopes:
                if scope in ("all", "football") or scope.startswith("football:"):
                    self._football.request_clear(scope)

    def status_snapshot(self) -> dict[str, str]:
        """Everything the admin page's status box shows -- state already
        sitting in memory.

        Called from the admin server's own thread (#61, #178 story 10):
        must never trigger a network fetch or mutate shared state
        concurrently with the main loop, hence ``allow_fetch=False`` -- a
        slow hockey response must not block a "read-only" status view, and
        the two threads must not race into duplicate fetches.
        """
        scene = self.select_scene(allow_fetch=False)
        return {
            "version": installed_version() or "unknown (factory image)",
            "address": self._board_name() or "(unknown)",
            "demo mode": "on" if self._demo_mode else "off",
            "scene": "demo" if self._demo_mode else scene.kind,
            "current game": self._scene_game_label(scene),
            **self._hockey_status(),
            **self._football_status(),
        }

    def _hockey_status(self) -> dict[str, str]:
        """The hockey half of the status box, always shown and labelled."""
        cfg = self._hockey_cfg()
        return {
            "Hockey favourite team": cfg.favourite_team or "(none)",
            "Hockey also following": ", ".join(cfg.also_follow) or "(none)",
            "Hockey last successful poll": self._format_time(self.last_success_at),
            "Hockey last error": self.last_error or "(none)",
            "Hockey last error at": self._error_time_label() or "(none)",
            **self._fetch_status(),
        }

    def _fetch_status(self) -> dict[str, str]:
        """The fetch worker's health (#267): a slow or hung API shows up here."""
        stats = self.fetcher.stats()
        if not stats.threaded:
            return {"Hockey fetch worker": "inline (no worker)"}
        if stats.in_flight and stats.oldest_age is not None:
            worker = f"busy: {stats.in_flight} in flight, oldest {stats.oldest_age:.0f}s"
        else:
            worker = "idle"
        if stats.last_seconds is None:
            last = "(none yet)"
        else:
            outcome = "ok" if stats.last_ok else "failed"
            last = f"{stats.last_label}, {stats.last_seconds:.1f}s, {outcome}"
        return {
            "Hockey fetch worker": worker,
            "Hockey last fetch": last,
            "Hockey fetch totals": (
                f"{stats.completed} done, {stats.failed} failed, "
                f"{stats.slow} slow (over {SLOW_FETCH_SECONDS:.0f}s)"
            ),
        }

    def _football_status(self) -> dict[str, str]:
        """The football half of the status box, always shown and labelled (#352).

        The worker's snapshot times are monotonic, so they are turned into wall-clock times here.
        Before football's mode exists (no football team ranked on a hockey-only board) the
        feed fields say so rather than vanish.
        """
        cfg = self._football_cfg()
        base = {
            "Football favourite team": cfg.favourite_team or "(none)",
            "Football also following": ", ".join(cfg.also_follow) or "(none)",
        }
        if self._football is None:
            off = "(football not running)"
            return {
                **base,
                "Football last successful poll": off,
                "Football last error": off,
                "Football last error at": off,
            }
        snap = self._football.snapshot

        def wall(mono: float | None) -> datetime | None:
            if mono is None:
                return None
            return self.clock() - timedelta(seconds=self.monotonic() - mono)

        failed_at = wall(snap.last_error_at) if snap is not None else None
        return {
            **base,
            "Football last successful poll": self._format_time(
                wall(snap.fetched_at) if snap else None
            ),
            "Football last error": (snap.last_error if snap else "") or "(none)",
            "Football last error at": self._format_time(failed_at) if failed_at else "(none)",
        }

    def _error_time_label(self) -> str:
        if self.last_error_at is None:
            return ""
        label = self._format_time(self.last_error_at)
        if self.last_error_recovered_at is not None:
            recovered = self.last_error_recovered_at.astimezone(self.tz).strftime("%H:%M:%S")
            label += f" (recovered {recovered})"
        return label

    @staticmethod
    def _scene_game_label(scene: Scene) -> str:
        if scene.fb_game is not None:
            return f"{scene.fb_game.away.abbrev} @ {scene.fb_game.home.abbrev}"
        if scene.game is None:
            return ", ".join(f"{g.away.abbrev} @ {g.home.abbrev}" for g in scene.games)
        return f"{scene.game.away.abbrev} @ {scene.game.home.abbrev}"

    def _format_time(self, value: datetime | None) -> str:
        if value is None:
            return "never"
        return value.astimezone(self.tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    def draw(self) -> None:
        self._delay.drain()
        if self._night_mode_active() and self.settings.night_mode.dim_brightness == 0:
            # Blank outright: brightness 0 alone isn't guaranteed dark on
            # every backend, and there's no point rendering a scene nobody
            # can see.
            self._begin_frame(("blank", self._applied_brightness))
            self.canvas.Clear()
            self.swap_canvas()
            self._overlay_animating = False
            self._shootout_animating = False
            self._goal_animating = self._goal_building = self._fb_animating = False
            self._penalty_animating = self._penalty_building = False
            self._egg_animating = False
            return
        if self._demo_mode:
            if not self._demo_was_on:
                self._demo_was_on = True
                self._demo_real_logos = self.renderer.logos
                self._demo_steps, self._demo_step_index, self._demo_next_step_at = [], 0, 0.0
            self._draw_demo_step()
            return
        if self._demo_was_on:
            self._demo_was_on = False
            self.renderer.logos = self._demo_real_logos
        self.draw_scene(self.select_scene())

    def _begin_frame(self, key: object) -> None:
        """Snapshot this frame for the live view (#268) if what it shows
        (``key``: the scene and everything else that decides its pixels)
        differs from the last snapshot, or one was asked for. A frame in the
        middle of an animation waits for it to finish, so a fly-by or a
        shootout pop-in isn't frozen half-drawn; ``key`` stays unrecorded
        until then, so the change isn't missed. The clock's ticking time
        isn't in ``key``: the page's Refresh is for that."""
        mirror = self.mirror
        if not mirror.watching and not mirror.requested:
            self._mirror_key = None
            return
        if key == self._mirror_key and not mirror.requested:
            return
        if (
            self._overlay_animating
            or self._shootout_animating
            or self._scroll_animating
            or self._goal_building
            or self._fb_animating
            or self._penalty_building
        ):
            return
        mirror.requested = False
        self._mirror_key = key
        self.canvas = MirrorCanvas(unwrap(self.canvas), mirror)

    def swap_canvas(self) -> None:
        """Show the frame just drawn, publishing it first if it was a
        live-view snapshot (see _begin_frame)."""
        if isinstance(self.canvas, MirrorCanvas):
            self.mirror.publish(self._applied_brightness, self.clock())
        self.canvas = self.matrix.SwapOnVSync(unwrap(self.canvas))

    def april_fools_active(self) -> bool:
        """April 1 on a Preds board (#248) -- see april_fools.py."""
        local = self.clock().astimezone(self.tz)
        return april_fools.active(self._hockey_cfg().favourite_team, local)

    @staticmethod
    def _april_fools_scene(scene: Scene) -> Scene:
        """Every NSH label in ``scene`` as MIL; nothing else changes (#248)."""
        changes: dict[str, object] = {}
        if scene.game is not None:
            changes["game"] = april_fools.swap_game(scene.game)
        if scene.goal_event is not None:
            changes["goal_event"] = april_fools.swap_goal(scene.goal_event)
        if scene.goal_team:
            changes["goal_team"] = april_fools.rename(scene.goal_team)
        if scene.penalty is not None:
            changes["penalty"] = dataclasses.replace(
                scene.penalty, team_abbrev=april_fools.rename(scene.penalty.team_abbrev)
            )
        if scene.stars is not None:
            changes["stars"] = tuple(april_fools.swap_star(s) for s in scene.stars)
        if scene.standings is not None:
            changes["standings"] = april_fools.swap_rows(scene.standings)
        if scene.games:
            changes["games"] = tuple(april_fools.swap_game(g) for g in scene.games)
        return dataclasses.replace(scene, **changes) if changes else scene

    def draw_scene(self, scene: Scene) -> None:
        r = self.renderer
        self._shootout_animating = False
        self._egg_animating = False
        self._scroll_animating = scene.scrolling
        self._fb_animating = scene.animating
        goal_age = self._goal_age(scene)
        self._goal_animating = goal_age is not None
        self._goal_building = goal_age is not None and goal_age < goal_light.BUILD_SECONDS
        penalty_age = self._penalty_age(scene)
        self._penalty_animating = penalty_age is not None
        self._penalty_building = (
            penalty_age is not None and penalty_age < penalty_screen.ENTRANCE_SECONDS
        )
        football_on = self._sport == "football" and self._football is not None
        favourite = (
            self._football_cfg().favourite_team
            if football_on
            else self._hockey_cfg().favourite_team
        )
        if not football_on and self.april_fools_active():
            favourite = april_fools.PRANK_AS
            scene = self._april_fools_scene(scene)
        if scene.kind == "game":
            scene = dataclasses.replace(scene, game=self.with_situation(scene.game))
        self._begin_frame(
            (scene, favourite, self.renderer.logos is not None, self._applied_brightness)
        )
        if scene.kind == "game":
            game = scene.game
            if game.shows_shootout:
                ages = self._shootout_frame_ages(game)
                self._shootout_animating = bool(ages)
                r.draw_shootout(self.canvas, game, self.monotonic(), ages)
            else:
                r.draw_game(self.canvas, game)
        elif scene.kind == "goal":
            r.draw_goal(self.canvas, scene.game, scene.goal_team or favourite, goal_age)
        elif scene.kind == "goal_detail":
            r.draw_goal_detail(self.canvas, scene.game, scene.goal_event)
        elif scene.kind == "penalty":
            r.draw_penalty(self.canvas, scene.penalty, penalty_age)
        elif scene.kind == "three_stars":
            r.draw_three_stars(self.canvas, scene.game, scene.stars)
        elif scene.kind == "intermission":
            r.draw_intermission(self.canvas, scene.game, scene.stats, scene.stats_page)
        elif scene.kind == "blowout":  # not documented on purpose, see blowout.py
            r.draw_blowout(self.canvas, scene.game, favourite)
        elif scene.kind == "countdown":
            r.draw_countdown(self.canvas, scene.game, self.clock())
        elif scene.kind == "preview":
            r.draw_preview(self.canvas, scene.game, self.clock())
        elif scene.kind == "conference_leaders":
            r.draw_conference_leaders(
                self.canvas, scene.standings, favourite, scene.scroll_px, scene.playoff_cut
            )
        elif scene.kind == "division":
            r.draw_division(
                self.canvas, scene.standings, favourite, scene.scroll_px, scene.playoff_cut
            )
        elif scene.kind == "wildcard":
            r.draw_wildcard(
                self.canvas, scene.standings, favourite, scene.scroll_px, scene.playoff_cut
            )
        elif scene.kind == "standings":
            r.draw_standings(self.canvas, scene.standings, favourite, scene.playoff_cut)
        elif scene.kind == "matchup":
            r.draw_matchup(self.canvas, scene.game, scene.season_series)
        elif scene.kind == "matchup_meetings":
            r.draw_matchup_meetings(self.canvas, scene.game, scene.meetings)
        elif scene.kind == "leaders":
            r.draw_leaders(self.canvas, scene.leaders, favourite)
        elif scene.kind == "scores":
            r.draw_scores(self.canvas, scene.games)
        elif scene.kind == "no_data":
            r.draw_message(self.canvas, "NO DATA", "CHECK NETWORK")
        elif scene.kind == "connecting":
            r.draw_message(self.canvas, "HOCKEY", "CONNECTING")
        elif scene.kind == "fb_connecting":
            r.draw_message(self.canvas, "FOOTBALL", "CONNECTING")
        elif scene.kind == "fb_no_data":
            r.draw_message(self.canvas, "NO DATA", "FOOTBALL CHECK NETWORK")
        elif scene.kind == "fb_no_games":
            r.draw_message(self.canvas, "NO GAMES", "FOOTBALL")
        elif scene.kind == "fb_scores":
            r.draw_fb_scores(self.canvas, scene.fb_game)
        elif scene.kind == "fb_field":
            r.draw_fb_field(self.canvas, scene.fb_game)
        elif scene.kind == "fb_halftime":
            r.draw_fb_halftime(self.canvas, scene.fb_game)
        elif scene.kind == "fb_countdown":
            r.draw_fb_countdown(self.canvas, scene.fb_game, self.clock())
        elif scene.kind == "fb_redzone":
            r.draw_fb_redzone(self.canvas, scene.fb_game, scene.fb_elapsed)
        elif scene.kind == "fb_schedule":
            r.draw_fb_schedule(self.canvas, scene.fb_idle, self.clock())
        elif scene.kind == "fb_week":
            r.draw_fb_week(self.canvas, scene.fb_idle, scene.fb_page)
        elif scene.kind == "fb_standings":
            r.draw_fb_standings(self.canvas, scene.fb_idle, scene.fb_page)
        elif scene.kind == "fb_final":
            r.draw_fb_final(self.canvas, scene.fb_idle, self.clock())
        elif scene.kind == "fb_bye":
            r.draw_fb_bye(self.canvas, scene.fb_idle, self.clock())
        elif scene.kind == "fb_preview":
            r.draw_fb_preview(self.canvas, scene.fb_idle, self.clock())
        elif scene.kind in ("fb_play", "fb_playtext", "fb_event"):
            r.draw_fb_play_scene(self.canvas, scene)
        elif scene.kind == "clock":
            sport, abbrev = self._colour_scheme(favourite, clock=True)
            with use_sport(sport):
                r.draw_clock(self.canvas, self.clock(), abbrev)
        elif scene.kind == "christmas_tree":
            sport, abbrev = self._colour_scheme(favourite)
            egg = self._tree_egg()
            # The squirrel and fire move; the quote is static text (the tree twinkles at 2fps).
            self._egg_animating = egg is not None and egg[0] in ("squirrel", "fire")
            with use_sport(sport):
                r.draw_christmas_tree(self.canvas, self.clock(), abbrev, egg)
        elif scene.kind == "thanksgiving":
            sport, abbrev = self._colour_scheme(favourite)
            egg = self._turkey_egg()
            self._egg_animating = egg is not None
            with use_sport(sport):
                r.draw_thanksgiving(self.canvas, self.clock(), abbrev, egg)
        elif scene.kind == "address":
            r.draw_address(
                self.canvas,
                scene.address_ip,
                scene.address_port,
                scene.address_qr,
                scene.address_name,
            )
        elif scene.kind == "ap_setup":
            r.draw_ap_setup(self.canvas, scene.ap_ssid, scene.ap_password, scene.ap_qr_matrix)
        elif scene.kind == "wifi_join":
            r.draw_wifi_join(self.canvas, scene.wifi_join_status, scene.wifi_join_ssid)
        else:
            r.draw_message(self.canvas, "NO GAMES")
        self._draw_holiday_overlay(scene, favourite)
        self.swap_canvas()

    def _shootout_frame_ages(self, game: Game) -> dict[int, float]:
        if self._demo_drawing:
            # The demo has no polls: its newest attempt "appears" when the
            # step starts, so the animation is visible on every pass.
            started = self._demo_shootout_started
            if started is None or game.shootout is None or not game.shootout.attempts:
                return {}
            age = self.monotonic() - started
            newest = game.shootout.attempts[-1].sequence
            return {newest: age} if age < self.renderer.SHOOTOUT_ANIM_SECONDS else {}
        return self.shootout_ages(game.id)

    def active_holiday(self) -> Holiday | None:
        """The configured holiday in season today (local date), if any."""
        cfg = self.settings.holiday
        if not cfg.enabled:
            return None
        return active_holiday(cfg.themes, self.clock().astimezone(self.tz).date())

    def _football_game_holiday(self, scene: Scene, season: Holiday | None) -> Holiday | None:
        """The holiday to draw over a football scene (#430).

        A **game screen** (the field, the plays, the countdown, the preview, the final...) gets a
        decoration only for a Thanksgiving or Christmas game, by the game's own date in the board's
        zone, and only when that holiday is ticked; no other holiday touches it, whatever the
        calendar says. Every other football scene (the clock, the standings...) keeps the season's.
        """
        from .football.idle_views import game_holiday

        if scene.kind not in FOOTBALL_GAME_SCENES:
            return season
        start = None
        if scene.fb_game is not None:
            start = scene.fb_game.start_utc
        elif scene.fb_idle is not None:
            start = getattr(scene.fb_idle, "start_utc", None)
        name = game_holiday(start, self.tz)
        cfg = self.settings.holiday
        if name is None or not cfg.enabled or name not in cfg.themes:
            return None
        return HOLIDAYS.get(name)

    def _draw_holiday_overlay(self, scene: Scene, favourite: str) -> None:
        holiday = self._demo_holiday if self._demo_drawing else self.active_holiday()
        football_on = self._sport == "football" and self._football is not None
        if football_on and not self._demo_drawing:
            holiday = self._football_game_holiday(scene, holiday)
        min_gap, max_gap = self.settings.holiday.flyby_gap_minutes
        sport, favourite = self._colour_scheme(favourite)
        with use_sport(sport):
            self._overlay_animating = self.holiday_overlay.draw(
                self.canvas,
                scene_kind=scene.kind,
                holiday=holiday,
                now=self.monotonic(),
                width=self.renderer.width,
                height=self.renderer.height,
                min_gap_seconds=min_gap * 60,
                max_gap_seconds=max_gap * 60,
                day=self.clock().astimezone(self.tz).date(),
                favourite=favourite,
            )
