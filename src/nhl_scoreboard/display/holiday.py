"""Seasonal holiday decorations drawn over the normal scenes (#236, #237).

An overlay, not a scene: ``ScoreboardApp.draw_scene()`` draws whatever scene
is up, then hands the canvas here before swapping it, so no individual scene
needs to know holidays exist. Each holiday turns itself on only inside its
own date window; the owner only ticks which ones they want (``[holiday]``
``themes``), never dates.

Everything draws through ``SetPixel`` (CLAUDE.md's one-code-path rule), and
every animated position is a pure function of the monotonic time passed in,
so a test can freeze a fly-by mid-crossing and snapshot it like any scene.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

RGB = tuple[int, int, int]


#: The scoring moments and the Wi-Fi setup screens stay clean: a ghost
#: crossing "GOAL" or a QR code someone is trying to scan helps nobody.
NO_OVERLAY_SCENES = frozenset({"goal", "goal_detail", "three_stars", "ap_setup", "wifi_join"})
#: Idle scenes with empty corners for a holiday's static decoration. Not
#: countdown/preview: their 32px logos fill both edges, same reason the
#: game scene gets none.
CORNER_SCENES = frozenset({"clock", "no_games"})
#: Gap between a corner decoration and the panel edge.
CORNER_INSET = 4


@dataclass(frozen=True, slots=True)
class Drop:
    """A small sprite a fly-by leaves behind on the bottom edge."""

    rows: tuple[str, ...]
    palette: tuple[tuple[str, RGB], ...]


@dataclass(frozen=True, slots=True)
class Flyby:
    """Something that crosses the panel right to left now and then."""

    #: Animation frames, cycled every ``frame_seconds``. Every frame the same size.
    frames: tuple[tuple[str, ...], ...]
    #: Sprite character -> colour, as pairs so the dataclass stays hashable.
    palette: tuple[tuple[str, RGB], ...]
    #: Pixels per second.
    speed: float
    frame_seconds: float
    #: Vertical bob amplitude (px) and period (s); 0 for something walking.
    bob_pixels: float = 0.0
    bob_period: float = 1.0
    #: "middle" floats through the centre; "bottom" walks along the bottom edge.
    align: str = "middle"
    #: Things left on the ground behind it (Santa's presents, #240): one
    #: dropped every ``drop_spacing`` px travelled, from sprite column
    #: ``drop_column``, cycling through ``drops``. They stay put until the
    #: pass ends, ``linger_seconds`` after the sprite itself has left.
    drops: tuple[Drop, ...] = ()
    drop_spacing: int = 0
    drop_column: int = 0
    linger_seconds: float = 0.0

    @property
    def width(self) -> int:
        return len(self.frames[0][0])

    @property
    def height(self) -> int:
        return len(self.frames[0])


@dataclass(frozen=True, slots=True)
class Holiday:
    name: str
    #: Human-readable, for the admin page's checkbox list (#238).
    label: str
    #: When it shows, in words, next to its admin-page checkbox (#238). Text
    #: rather than derived from is_active: Thanksgiving's window (#239) is
    #: computed per year and has no fixed dates to print.
    window: str
    is_active: Callable[[date], bool]
    flyby: Flyby
    #: Draws the static decoration on CORNER_SCENES: (canvas, now, width, height).
    corners: Callable[[Any, float, int, int], None]
    #: Ticked when [holiday] themes isn't set. False for a holiday most
    #: boards wouldn't want unasked (Canadian Thanksgiving on a US board).
    default_on: bool = True
    #: Which wins when two ticked windows overlap: the higher number.
    priority: int = 0


def _between(start: tuple[int, int], end: tuple[int, int]) -> Callable[[date], bool]:
    """Inclusive (month, day) window inside a single calendar year."""

    def check(day: date) -> bool:
        return start <= (day.month, day.day) <= end

    return check


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``th ``weekday`` (Monday = 0) of a month, e.g. 4th Thursday of November."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _us_thanksgiving_week(day: date) -> bool:
    """The 7 days up to and including the 4th Thursday of November (#239)."""
    thanksgiving = nth_weekday(day.year, 11, 3, 4)
    return thanksgiving - timedelta(days=6) <= day <= thanksgiving


def _ca_thanksgiving_weekend(day: date) -> bool:
    """Friday through the 2nd Monday of October -- the long weekend (#239).

    Deliberately short: it sits inside Halloween's window and wins over it
    there (see HOLIDAYS), so every extra day here is a day less of Halloween.
    """
    monday = nth_weekday(day.year, 10, 0, 2)
    return monday - timedelta(days=3) <= day <= monday


# -- Halloween (#237) ----------------------------------------------------------

GHOST_BODY = (235, 235, 255)
EYE = (0, 0, 0)
# The face has to stand out from the shell even at the flicker's dim end:
# a first try at (255, 100, 0) shell / (255, 150, 0) dim glow read as a
# plain orange ball in a rendered preview.
PUMPKIN = (200, 60, 0)
STEM = (0, 150, 0)
GLOW_BRIGHT = (255, 235, 60)
GLOW_DIM = (255, 190, 0)

# '#' body, 'o' eye. Two frames that differ only in the hem, so the ghost
# wiggles as it floats. Faces left, the way it travels.
_GHOST_TOP = (
    "...####...",
    ".########.",
    "##########",
    "#oo##oo###",
    "#oo##oo###",
    "##########",
    "##########",
    "##########",
    "##########",
    "##########",
)
GHOST_FRAMES = (
    (*_GHOST_TOP, "##########", "#.##.##.##"),
    (*_GHOST_TOP, "##########", "##.##.##.#"),
)
GHOST = Flyby(
    frames=GHOST_FRAMES,
    palette=(("#", GHOST_BODY), ("o", EYE)),
    # ~7s to cross 128px: slow enough to read as floating.
    speed=20.0,
    frame_seconds=0.25,
    bob_pixels=1.5,
    bob_period=1.6,
)
GHOST_WIDTH = GHOST.width
GHOST_HEIGHT = GHOST.height
#: The ghost's speed, kept under its original name for the tests.
FLYBY_SPEED = GHOST.speed

# 'O' pumpkin, 'G' stem, 'Y' the carved face (lit from inside).
PUMPKIN_SPRITE = (
    ".....G.....",
    "....GG.....",
    "..OOOOOOO..",
    ".OOOOOOOOO.",
    "OOYOOOOOYOO",
    "OYYYOOOYYYO",
    "OOOOOYOOOOO",
    "OYYYYYYYYYO",
    ".OOYOYOYOO.",
    "..OOOOOOO..",
)
PUMPKIN_WIDTH = len(PUMPKIN_SPRITE[0])
PUMPKIN_HEIGHT = len(PUMPKIN_SPRITE)


def _draw_pumpkins(canvas: Any, now: float, width: int, height: int) -> None:
    # Candle flicker: mostly bright, briefly dim, the two pumpkins out of
    # step so it doesn't read as one blinking light.
    y = (height - PUMPKIN_HEIGHT) // 2
    for x, phase in ((CORNER_INSET, 0), (width - PUMPKIN_WIDTH - CORNER_INSET, 1)):
        glow = GLOW_DIM if (int(now * 2) + phase) % 3 == 0 else GLOW_BRIGHT
        palette = {"O": PUMPKIN, "G": STEM, "Y": glow}
        draw_sprite(canvas, PUMPKIN_SPRITE, palette, x, y, width, height)


# -- Thanksgiving (#239) -------------------------------------------------------

FEATHER_RED = (210, 30, 0)
FEATHER_ORANGE = (255, 110, 0)
FEATHER_GOLD = (255, 200, 0)
# Brighter than a real turkey: (140, 70, 20) all but vanished in a
# rendered preview, the same trap teams.py lifts navy/burgundy out of.
TURKEY_BODY = (180, 95, 30)
TURKEY_HEAD = (225, 165, 110)
WATTLE = (255, 0, 0)
BEAK = (255, 170, 0)
LEGS = (255, 140, 0)
MAPLE = (230, 50, 0)
LEAF_GOLD = (240, 170, 0)
LEAF_VEIN = (150, 70, 0)

# Side view facing left (the way it walks): fan of tail feathers behind,
# 'k' beak, 'w' wattle, 'e' eye, 'L' legs. Two frames that differ only in
# the legs, so it walks rather than slides.
_TURKEY_TOP = (
    ".......RRRR...",
    ".....RROOOORR.",
    "....ROOYYYYOOR",
    "..HHROYYYYYYOR",
    ".HeHROYYYYYYOR",
    "kHHBBBYYYYYYOR",
    ".wHBBBBBYYYYOR",
    ".wBBBBBBBBYOR.",
    "..BBBBBBBBBRR.",
    "...BBBBBBBB...",
    "....BBBBBB....",
)
TURKEY_FRAMES = (
    (*_TURKEY_TOP, ".....L..L.....", "....LL.LL....."),
    (*_TURKEY_TOP, "......LL......", ".....LL.L....."),
)
TURKEY = Flyby(
    frames=TURKEY_FRAMES,
    palette=(
        ("R", FEATHER_RED),
        ("O", FEATHER_ORANGE),
        ("Y", FEATHER_GOLD),
        ("B", TURKEY_BODY),
        ("H", TURKEY_HEAD),
        ("e", EYE),
        ("k", BEAK),
        ("w", WATTLE),
        ("L", LEGS),
    ),
    # A walk, not a float: slower than the ghost, no bob, along the bottom.
    speed=14.0,
    frame_seconds=0.3,
    align="bottom",
)

# 'M' maple red, 's' stem.
MAPLE_LEAF = (
    "....M....",
    "...MMM...",
    ".M.MMM.M.",
    "MMMMMMMMM",
    ".MMMMMMM.",
    "..MMMMM..",
    ".MMMMMMM.",
    "....s....",
    "....s....",
)
# 'G' gold, 'v' vein: a plain leaf lying on the diagonal.
GOLD_LEAF = (
    "......GG.",
    "....GGGGG",
    "...GGGGvG",
    "..GGGGvGG",
    ".GGGGvGG.",
    ".GGGvGGG.",
    "GGGvGGG..",
    "..vGGG...",
    ".v.......",
)
LEAF_SIZE = len(MAPLE_LEAF)


def _draw_leaves(canvas: Any, now: float, width: int, height: int) -> None:
    # Static: nothing here needs the fast frame loop.
    del now
    y = (height - LEAF_SIZE) // 2
    draw_sprite(canvas, MAPLE_LEAF, {"M": MAPLE, "s": LEAF_VEIN}, CORNER_INSET, y, width, height)
    right = width - LEAF_SIZE - CORNER_INSET
    palette = {"G": LEAF_GOLD, "v": LEAF_VEIN}
    draw_sprite(canvas, GOLD_LEAF, palette, right, y, width, height)


# -- Christmas (#240) ----------------------------------------------------------

SANTA_RED = (220, 0, 0)
SANTA_WHITE = (255, 255, 255)
SANTA_FACE = (255, 185, 140)
# Not black: (0, 0, 0) is an unlit LED, so boots and belt would read as holes.
SANTA_DARK = (70, 70, 70)
BUCKLE = (255, 210, 0)
SACK = (160, 100, 40)
SNOW = (190, 200, 230)

# Side view facing left: 'R' suit, 'W' fur trim and beard, 'F' face, 'e'
# eye, 'K' belt/boots, 'G' buckle, 'S' the sack over his shoulder. Two
# frames that differ only in the boots.
_SANTA_TOP = (
    "..RRRR........",
    ".RRRRRRW......",
    ".WWWWWW...SSS.",
    ".FeFFF...SSSSS",
    "WWFFFWW.SSSSSS",
    "WWWWWWWRSSSSSS",
    ".WWWWWRRRSSSS.",
    ".RRWWRRRRRSS..",
    ".RRRRRRRR.....",
    "KKKGKKKKK.....",
    ".RRRRRRRR.....",
    ".WWWWWWWW.....",
)
SANTA_FRAMES = (
    (*_SANTA_TOP, "..RR..RR......", ".KKK.KKK......"),
    (*_SANTA_TOP, "...RR.RR......", "..KKKKKK......"),
)


def _present(box: RGB, ribbon: RGB) -> tuple[tuple[str, RGB], ...]:
    return (("C", box), ("r", ribbon))


# Dropped as he walks: small, bow on top, ribbon cross.
SMALL_PRESENT = (
    ".r.r.",
    "CCrCC",
    "rrrrr",
    "CCrCC",
    "CCrCC",
)
# Stacked beside the clock.
BIG_PRESENT = (
    "..r.r..",
    "...r...",
    "CCCrCCC",
    "CCCrCCC",
    "rrrrrrr",
    "CCCrCCC",
    "CCCrCCC",
    "CCCrCCC",
)
PRESENT_COLOURS = (
    _present((200, 0, 0), (255, 210, 0)),
    _present((0, 160, 40), (220, 0, 0)),
    _present((40, 90, 255), (255, 255, 255)),
)
SANTA = Flyby(
    frames=SANTA_FRAMES,
    palette=(
        ("R", SANTA_RED),
        ("W", SANTA_WHITE),
        ("F", SANTA_FACE),
        ("e", EYE),
        ("K", SANTA_DARK),
        ("G", BUCKLE),
        ("S", SACK),
    ),
    speed=14.0,
    frame_seconds=0.3,
    align="bottom",
    drops=tuple(Drop(SMALL_PRESENT, colours) for colours in PRESENT_COLOURS),
    # Every ~26px: four or five presents across the panel.
    drop_spacing=26,
    # Under the sack, which hangs off his back (the right, since he walks left).
    drop_column=9,
    # Long enough to see the trail of presents once he's gone.
    linger_seconds=2.0,
)


def _snowflakes(count: int, seed: int) -> tuple[tuple[int, float, float], ...]:
    """(column within its band, start offset, px per second), fixed per run.

    Seeded, not live random: the corner draw has to be a pure function of
    time so a snapshot can freeze it.
    """
    rng = random.Random(seed)
    return tuple(
        (rng.randrange(28), rng.uniform(0, 32), rng.uniform(1.5, 3.0)) for _ in range(count)
    )


#: Slow enough (1.5-3 px/s) to look right at the normal 2fps loop, so a
#: month of snow never needs the fast animation loop (#240).
SNOWFLAKES = (_snowflakes(9, 1), _snowflakes(9, 2))
#: Snow stays in a band this wide at each edge -- the real panel can't be
#: asked which pixels the clock text lit, so flakes can't weave around it.
SNOW_BAND = 30


def _draw_presents_and_snow(canvas: Any, now: float, width: int, height: int) -> None:
    for band, flakes in enumerate(SNOWFLAKES):
        left = 1 if band == 0 else width - SNOW_BAND - 1
        for column, offset, speed in flakes:
            y = int(offset + now * speed) % height
            sway = round(math.sin(now * 0.8 + offset))
            x = min(max(left + column + sway, left), left + SNOW_BAND - 1)
            canvas.SetPixel(x, y, *SNOW)
    # Presents on top of the snow: two side by side in each corner, a
    # small one perched on the first.
    red, green, blue = PRESENT_COLOURS
    y = height - len(BIG_PRESENT)
    step = len(BIG_PRESENT[0]) + 1
    for x, first, second, small in (
        (CORNER_INSET, green, blue, red),
        (width - CORNER_INSET - 2 * step + 1, red, green, blue),
    ):
        draw_sprite(canvas, BIG_PRESENT, dict(first), x, y, width, height)
        draw_sprite(canvas, BIG_PRESENT, dict(second), x + step, y, width, height)
        draw_sprite(
            canvas, SMALL_PRESENT, dict(small), x + 1, y - len(SMALL_PRESENT), width, height
        )


#: In calendar order: also the order of the admin page's checkboxes.
HOLIDAYS: dict[str, Holiday] = {
    "halloween": Holiday(
        "halloween", "Halloween", "Oct 1-31", _between((10, 1), (10, 31)), GHOST, _draw_pumpkins
    ),
    "thanksgiving_ca": Holiday(
        "thanksgiving_ca",
        "Thanksgiving (Canada)",
        "Fri-Mon of the 2nd Monday in Oct",
        _ca_thanksgiving_weekend,
        TURKEY,
        _draw_leaves,
        default_on=False,
        # Its long weekend sits inside Halloween's October and wins there
        # (owner's call, #239).
        priority=1,
    ),
    "thanksgiving": Holiday(
        "thanksgiving",
        "Thanksgiving (US)",
        "The week up to the 4th Thursday in Nov",
        _us_thanksgiving_week,
        TURKEY,
        _draw_leaves,
    ),
    "christmas": Holiday(
        "christmas",
        "Christmas",
        "Dec 1-26",
        _between((12, 1), (12, 26)),
        SANTA,
        _draw_presents_and_snow,
    ),
}
HOLIDAY_NAMES = tuple(HOLIDAYS)
DEFAULT_THEMES = tuple(name for name, holiday in HOLIDAYS.items() if holiday.default_on)


def active_holiday(themes: Sequence[str], day: date) -> Holiday | None:
    """The ticked holiday whose window contains ``day``, if any.

    Overlaps go to the higher ``priority``; ties to the earlier entry.
    """
    active = [h for name, h in HOLIDAYS.items() if name in themes and h.is_active(day)]
    return max(active, key=lambda h: h.priority, default=None)


def draw_sprite(
    canvas: Any,
    rows: Sequence[str],
    palette: dict[str, RGB],
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    """Blit ``rows`` at (x, y), clipped to the panel ('.' is transparent).

    Clipped here rather than left to the driver: the fly-by enters and
    leaves off-panel, and the test canvas records off-panel writes as bugs.
    """
    for dy, row in enumerate(rows):
        py = y + dy
        if not 0 <= py < height:
            continue
        for dx, ch in enumerate(row):
            px = x + dx
            if ch == "." or not 0 <= px < width:
                continue
            canvas.SetPixel(px, py, *palette[ch])


class HolidayOverlay:
    """Draws the active holiday's decorations and times its fly-bys.

    The only state is when the next fly-by is due and when the current one
    started. A fly-by only *starts* while a scene that allows it is up; one
    already crossing is simply not drawn over an excluded scene (a goal
    mid-pass), and its clock keeps running underneath.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self._next_flyby_at: float | None = None
        self._flyby_started: float | None = None

    def reset(self) -> None:
        self._next_flyby_at = None
        self._flyby_started = None

    def start_flyby(self, now: float) -> None:
        """Begin a fly-by right now -- for demo mode, which can't wait minutes."""
        self._flyby_started = now
        self._next_flyby_at = None

    def draw(
        self,
        canvas: Any,
        *,
        scene_kind: str,
        holiday: Holiday | None,
        now: float,
        width: int,
        height: int,
        min_gap_seconds: float,
        max_gap_seconds: float,
    ) -> bool:
        """Decorate ``canvas``; returns True while something is moving.

        The caller uses that to run the frame loop fast only for the few
        seconds a fly-by is on screen, and at its normal 2fps otherwise.
        """
        if holiday is None:
            # Out of season or unticked: forget any schedule, so turning it
            # back on starts a fresh random gap instead of firing at once.
            self.reset()
            return False
        if scene_kind in NO_OVERLAY_SCENES:
            return False
        if scene_kind in CORNER_SCENES:
            holiday.corners(canvas, now, width, height)
        return self._draw_flyby(
            canvas, holiday.flyby, now, width, height, min_gap_seconds, max_gap_seconds
        )

    def _draw_flyby(
        self,
        canvas: Any,
        flyby: Flyby,
        now: float,
        width: int,
        height: int,
        min_gap: float,
        max_gap: float,
    ) -> bool:
        if self._flyby_started is None:
            if self._next_flyby_at is None:
                self._next_flyby_at = now + self.rng.uniform(min_gap, max_gap)
            if now < self._next_flyby_at:
                return False
            self.start_flyby(now)
        elapsed = now - self._flyby_started
        travelled = round(elapsed * flyby.speed)
        x = width - travelled
        linger = round(flyby.linger_seconds * flyby.speed)
        if x + flyby.width + linger <= 0:
            self._flyby_started = None
            self._next_flyby_at = now + self.rng.uniform(min_gap, max_gap)
            return False
        if flyby.drops:
            self._draw_drops(canvas, flyby, travelled, width, height)
        if flyby.align == "bottom":
            y = height - flyby.height
        else:
            bob = flyby.bob_pixels * math.sin(2 * math.pi * elapsed / flyby.bob_period)
            y = (height - flyby.height) // 2 + round(bob)
        frame = flyby.frames[int(elapsed / flyby.frame_seconds) % len(flyby.frames)]
        draw_sprite(canvas, frame, dict(flyby.palette), x, y, width, height)
        return True

    @staticmethod
    def _draw_drops(canvas: Any, flyby: Flyby, travelled: int, width: int, height: int) -> None:
        """Everything dropped so far, each where the sprite was when it fell.

        A pure function of distance travelled, like the sprite itself: drop
        ``i`` falls once ``(i + 1) * drop_spacing`` px are covered, at the
        x ``drop_column`` was at that moment, and only while that's on-panel.
        """
        i = 0
        while (distance := (i + 1) * flyby.drop_spacing) <= travelled:
            drop = flyby.drops[i % len(flyby.drops)]
            drop_x = width - distance + flyby.drop_column
            if drop_x + len(drop.rows[0]) > width or drop_x < 0:
                i += 1
                continue
            y = height - len(drop.rows)
            draw_sprite(canvas, drop.rows, dict(drop.palette), drop_x, y, width, height)
            i += 1
