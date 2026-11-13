"""The NFL play scenes (#377): what is drawn while a play, its text or an event is on screen.

Three scene kinds, chosen by ``football.director``:

* ``fb_play``: the animation of one play, a pure function of the seconds since it started.
* ``fb_playtext``: the play's own sentence once the animation is over.
* ``fb_event``: a celebration, alert, coin toss or reversal (``Scene.fb_stage`` says which).

Every designed screen is **one entry in a registry**, so a screen's story only adds a function:

* ``@play_screen(PlayKind.RUSH)`` registers the animation for a play kind;
* ``@event_screen(Touchdown, EVENT)`` registers the screen for an event class in a stage
  (``football.director.EVENT`` / ``DETAIL`` / ``REVERSAL``).

Anything with no entry gets the generic version here, so an unknown play type or an event nobody
has drawn yet still shows something sensible and never raises. These generic screens are
deliberately plain: they are the floor every designed screen replaces.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..football import textlayout as tl
from ..football.director import DETAIL, EVENT, REVERSAL
from ..football.events import CoinToss, FieldGoal, GenericScore, Touchdown, Turnover
from ..football.geometry import FieldLayout
from ..football.models import PlayKind
from ..football.reversals import Reversal
from ..football.teams import is_team, team_color
from . import football_field as ff
from .fonts import text_width

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

Drawer = Callable[["Renderer", Any, "Scene"], None]

PLAY_SCREENS: dict[PlayKind, Drawer] = {}
EVENT_SCREENS: dict[tuple[type, str], Drawer] = {}

WHITE = (255, 255, 255)
GAIN = (0, 235, 90)
LOSS = (235, 50, 50)
NEUTRAL = (255, 176, 0)
#: The amber of a card headline (the end of a quarter, the half).
AMBER_CARD = (255, 176, 0)
DIM = (120, 120, 120)
#: How much of a generic play's time the ball spends moving; the rest it rests at the end spot.
TRAVEL = 0.8


def play_screen(kind: PlayKind) -> Callable[[Drawer], Drawer]:
    def register(drawer: Drawer) -> Drawer:
        PLAY_SCREENS[kind] = drawer
        return drawer

    return register


def event_screen(event: type, stage: str = EVENT) -> Callable[[Drawer], Drawer]:
    def register(drawer: Drawer) -> Drawer:
        EVENT_SCREENS[(event, stage)] = drawer
        return drawer

    return register


#: The modules that register a designed screen on import. Loaded on first draw rather than at the
#: bottom of this module, so importing any one of them first cannot hit a half-built import cycle
#: (each imports this module for ``play_screen``, and some import each other).
SCREEN_MODULES = (
    "football_run",
    "football_pass",
    "football_kickoff",
    "football_punt",
    "football_incomplete",
    "football_sack",
    "football_penalty",
    "football_stoppage",
    "football_period",
    "football_cointoss",
    "football_touchdown",
    "football_score_detail",
)
_loaded = False


def load_screens() -> None:
    """Import every screen module so its ``@play_screen`` / ``@event_screen`` entries exist."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in SCREEN_MODULES:
        importlib.import_module(f".{name}", __package__)


def draw(r: Renderer, canvas: Any, scene: Scene) -> None:
    """Draw one of the three play scenes."""
    load_screens()
    if scene.kind == "fb_play":
        PLAY_SCREENS.get(scene.fb_play.kind, draw_generic_play)(r, canvas, scene)
    elif scene.kind == "fb_playtext":
        draw_playtext(r, canvas, scene)
    else:
        drawer = EVENT_SCREENS.get((type(scene.fb_event), scene.fb_stage), draw_generic_event)
        drawer(r, canvas, scene)


# -- the generic play animation --------------------------------------------------------------


def play_label(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    """``PUNT +53``-style text for the band and its colour: green for a gain, red for a loss."""
    play = scene.fb_play
    yards = play.stat_yardage
    name = play.type.upper() or play.kind.value.replace("_", " ").upper()
    if play.kind in (PlayKind.RUSH, PlayKind.PASS_COMPLETE, PlayKind.SACK) and yards:
        return f"{name.split()[0]} {yards:+d}", GAIN if yards > 0 else LOSS
    return name, NEUTRAL


def quarter_clock(play: Any) -> str:
    """``3RD 12:24`` for the band (the 4x6 ``Q`` reads as a zero); ``OT`` after the fourth."""
    ordinal = {1: "1ST", 2: "2ND", 3: "3RD", 4: "4TH"}.get(play.period, "OT")
    return f"{ordinal} {play.clock}".strip()


def _side(game: Any, team_id: int | None) -> str | None:
    return ff.possession_of(game, team_id)


def _spot(pos: Any, fallback: float) -> float:
    return fallback if pos is None or pos.yard_line is None else float(pos.yard_line)


def draw_generic_play(r: Renderer, canvas: Any, scene: Scene) -> None:
    """Any play: the field, and the ball sliding from where the play started to where it ended,
    with the play's name over it."""
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    team_id = (play.start or play.end).team_id if (play.start or play.end) else None
    side = _side(game, team_id)
    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    start = _spot(play.start, 50.0)
    end = _spot(play.end, start)
    progress = (
        1.0 if scene.fb_seconds <= 0 else min(1.0, scene.fb_elapsed / (scene.fb_seconds * TRAVEL))
    )
    ff.draw_ball(canvas, layout, start + (end - start) * progress)
    label, color = play_label(scene)
    _band(r, canvas, label, color, quarter_clock(play))


def _band(r: Renderer, canvas: Any, label: str, color: tuple[int, int, int], right: str) -> None:
    """The one-line band over the field: the play on the left, the clock on the right."""
    clock = r._fit_text(r.fonts.tiny, right.upper(), r.width // 2 - 2)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)
    room = r.width - text_width(r.fonts.tiny, clock) - 4
    r.text(canvas, r.fonts.tiny, 1, 6, color, r._fit_text(r.fonts.tiny, label, room))


# -- the generic play text ---------------------------------------------------------------------


def wrap(text: str, width: int, font: Any, lines: int) -> list[str]:
    """``text`` broken into at most ``lines`` lines of ``width`` pixels (the last cut short)."""
    out: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if text_width(font, trial) <= width:
            line = trial
            continue
        if line:
            out.append(line)
        line = word
    if line:
        out.append(line)
    if len(out) > lines:
        out = [*out[: lines - 1], r_fit(" ".join(out[lines - 1 :]), width, font)]
    return [r_fit(x, width, font) for x in out]


def r_fit(text: str, width: int, font: Any) -> str:
    from .renderer import Renderer

    return Renderer._fit_text(font, text, width)


def draw_playtext(r: Renderer, canvas: Any, scene: Scene) -> None:
    """The field and the feed's own sentence (#379).

    128px: the field in the left half with the ball where the play left it, the sentence on the
    right three lines at a time (it scrolls a line at a time when longer), and the new down and
    distance under it. 64px: the field and the text take turns (``football.textlayout``).
    """
    play = scene.fb_play
    canvas.Clear()
    wide = r.width >= 128
    pos = play.end or play.start
    down = pos.short_down_distance_text.upper() if pos else ""
    if wide:
        half = r.width // 2
        _field_half(r, canvas, scene, 0, half)
        x = half + 3
        lines = wrap(play.text.upper(), r.width - x - 1, r.fonts.tiny, 99)
        _text_lines(r, canvas, lines, x, tl.WIDE_LINES, scene.fb_elapsed, down)
        return
    visible = NARROW_LINES
    lines = wrap(play.text.upper(), r.width - 3, r.fonts.tiny, 99)
    view, t = tl.narrow_view(scene.fb_elapsed, len(lines), visible)
    if view == "field":
        _field_half(r, canvas, scene, 0, r.width)
    else:
        _text_lines(r, canvas, lines, 2, visible, t, down)


#: Lines of text a 64px panel shows at once: three, with the down and distance under them.
NARROW_LINES = 3


def _field_half(r: Renderer, canvas: Any, scene: Scene, left: int, right: int) -> None:
    """The field in ``left..right`` with the ball where the play left it, and its label."""
    game, play = scene.fb_game, scene.fb_play
    layout = FieldLayout.for_panel(r.width, left, right)
    pos = play.end or play.start
    side = _side(game, pos.team_id if pos else None)
    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=None)
    if pos is not None and pos.yard_line is not None:
        ff.draw_ball(canvas, layout, pos.yard_line)
    label, color = play_label(scene)
    r.text(canvas, r.fonts.tiny, left + 1, 6, color, r_fit(label, right - left - 2, r.fonts.tiny))


def _text_lines(
    r: Renderer, canvas: Any, lines: list[str], x: int, visible: int, elapsed: float, down: str
) -> None:
    """``visible`` lines of text from where the scroll has got to, with the down under them."""
    first = tl.first_line(elapsed, len(lines), visible)
    for i, line in enumerate(lines[first : first + visible]):
        r.text(canvas, r.fonts.tiny, x, 6 + 7 * i, WHITE, line)
    if down:
        r.text(
            canvas,
            r.fonts.tiny,
            x,
            r.height - 2,
            NEUTRAL,
            r_fit(down, r.width - x - 1, r.fonts.tiny),
        )


# -- the generic event card ---------------------------------------------------------------------


def event_title(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    """The headline and colour of an event: its team's colour for a score, green or red for a
    turnover by who gained the ball, amber for a correction or a plain kick."""
    event = scene.fb_event
    team = event.team
    team_rgb = team_color(team) if is_team(team) else WHITE
    if isinstance(event, Reversal):
        return event.title, NEUTRAL
    if isinstance(event, Touchdown):
        return "TOUCHDOWN", team_rgb
    if isinstance(event, FieldGoal):
        return ("FIELD GOAL" if event.made else "NO GOOD"), (team_rgb if event.made else NEUTRAL)
    if isinstance(event, GenericScore):
        return f"{event.points} POINTS", team_rgb
    if isinstance(event, Turnover):
        return event.reason.replace("_", " ").upper() or "TURNOVER", NEUTRAL
    if isinstance(event, CoinToss):
        return f"{team} RECEIVE", team_rgb
    return "PLAY", WHITE


def _score_line(scene: Scene) -> str:
    game, event = scene.fb_game, scene.fb_event
    return f"{game.away.abbrev} {event.away_score}  {game.home.abbrev} {event.home_score}"


def draw_generic_event(r: Renderer, canvas: Any, scene: Scene) -> None:
    """A full-panel card: the headline in colour, and under it the detail or the new score."""
    canvas.Clear()
    title, color = event_title(scene)
    width = r.width - 4
    font = next(
        (
            f
            for f in (r.fonts.large, r.fonts.medium, r.fonts.small)
            if text_width(f, title) <= width
        ),
        r.fonts.tiny,
    )
    r.text_center(canvas, font, r.width // 2, 13, color, r_fit(title, width, font))
    if scene.fb_stage == DETAIL:
        line = scene.fb_play.text.upper()
    elif scene.fb_stage == REVERSAL:
        line = getattr(scene.fb_event, "reason", "").upper()
    elif isinstance(scene.fb_event, CoinToss):
        line = "KICKS " + scene.fb_event.kicker if scene.fb_event.kicker else ""
    else:
        line = _score_line(scene)
    r.text_center(canvas, r.fonts.tiny, r.width // 2, 22, WHITE, r_fit(line, width, r.fonts.tiny))
