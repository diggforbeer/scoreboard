"""``Scene``: what the panel should show right now.

Its own module so the drawing code (``display/``, ``football/``) can name a
scene without importing ``app``, which drives the hardware, audio, the admin
server and the rest of the board's shell. ``app`` re-exports ``Scene`` for
everything that already imports it from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import stocks as stocks_mod
from .football.events import Event as FbEvent
from .football.models import FbGame, Play
from .football.people import Person
from .hockey.models import (
    Game,
    GameStats,
    GoalEvent,
    MeetingResult,
    Penalty,
    SeasonSeriesRecord,
    ShotMap,
    StandingsRow,
    Star,
    TeamLeaders,
)
from .important_dates import DateView


@dataclass(frozen=True, slots=True)
class Scene:
    """What the board should show right now.

    ``kind`` is one of ``game`` (live or final scoreboard), ``goal``,
    ``goal_detail``, ``penalty``, ``three_stars``, ``intermission``, ``countdown``, ``preview``,
    ``standings``,
    ``conference_leaders``, ``division``, ``wildcard``, ``matchup``, ``matchup_meetings``,
    ``leaders``, ``scores``, ``clock``, ``christmas_tree``, ``thanksgiving``, ``no_games``,
    ``connecting``, ``no_data``, ``ap_setup``, ``wifi_join``, ``address``, ``dates``,
    ``stocks``.

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
    #: Set only for ``intermission`` -- the shots for its shot-map page, when there are any.
    shots: ShotMap | None = None
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
    #: Set only for ``dates`` (#524) -- the important dates inside their window, nearest first
    #: (a rotation slot narrows it to the one being shown).
    date_views: tuple[DateView, ...] = ()
    #: Set only for ``stocks`` -- the ticker's stocks as drawn; ``scroll_px`` is how far the strip
    #: has moved left and ``scrolling`` keeps the loop fast while it does.
    stock_views: tuple[stocks_mod.StockView, ...] = ()
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
    #: The upset an ``fb_upset`` scene announces (a ``football.upset.Upset``).
    fb_upset: Any = None
    #: Which page of a several-page idle screen (the standings' division, then conference).
    fb_page: int = 0
    fb_elapsed: float = field(default=0.0, compare=False)
    fb_seconds: float = 0.0
    animating: bool = False
    #: Set only for ``conference_leaders`` -- pixels the list has scrolled up.
    scroll_px: int = 0
    #: True while ``scroll_px`` is still moving, so the loop runs fast.
    scrolling: bool = False
