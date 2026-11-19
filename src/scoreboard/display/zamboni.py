"""The Zamboni page of the intermission screen (#526): a top-down rink resurfaced during the break.

The ice starts scratched and dull; two machines, one per half of the rink, each start at the end
boards and spiral inward in 3px swaths (rotationally mirrored, so they start in opposite corners),
and everything they have passed turns to clean, light ice with a brief wet shine behind them. The
machines are drawn in the two teams' colours. The countdown is at the right.

Real arenas run two machines for about six minutes a break; here it is a time-lapse stretched over
the whole break, finishing ``EARLY_FINISH_SECONDS`` before it ends so the clean ice is seen. All a
pure function of ``elapsed`` and ``total`` seconds: nothing here keeps state. 128px panels only.
"""

from __future__ import annotations

import functools
import itertools
import math
from typing import TYPE_CHECKING, Any

from .teams import team_color

if TYPE_CHECKING:
    from ..hockey.models import Game
    from .renderer import Renderer

RINK_W, RINK_H = 96, 32
MIN_PANEL_WIDTH = 128
CORNER = 6
SWATH = 3
LAPS = 5
#: Each machine's last stretch of path that still shines wet, in path pixels.
SHINE_PIXELS = 12
#: The clean is done this long before the break ends, and the machines drive off this long after.
EARLY_FINISH_SECONDS = 150.0
EXIT_SECONDS = 12.0

BOARD = (84, 88, 104)
DIRTY = (108, 124, 148)
DIRTY_LIGHT = (150, 166, 188)
DIRTY_DARK = (70, 84, 106)
CLEAN = (196, 218, 236)
SHINE = (244, 251, 255)
RED_LINE = (190, 40, 40)
BLUE_LINE = (40, 70, 200)
CAB = (30, 34, 44)
GLASS = (90, 130, 170)
BEACON = (255, 170, 0)
LABEL = (150, 150, 150)
WHITE = (255, 255, 255)

#: Faint rink markings as (x, colour): centre line, blue lines, goal lines (200ft over 96px).
MARKINGS = (
    (47, RED_LINE),
    (48, RED_LINE),
    (35, BLUE_LINE),
    (60, BLUE_LINE),
    (5, RED_LINE),
    (90, RED_LINE),
)


def clean_seconds(total: float) -> float:
    """How long the machines take: all but the last stretch of the break."""
    return max(total - EARLY_FINISH_SECONDS, total * 0.5)


def progress(elapsed: float, total: float) -> float:
    """How much of the clean is done, 0 to 1."""
    span = clean_seconds(total)
    return 0.0 if span <= 0 else min(1.0, max(0.0, elapsed / span))


def fits(width: int) -> bool:
    return width >= MIN_PANEL_WIDTH


def _inside(x: int, y: int, inset: int) -> bool:
    """Whether (x, y) is inside the rink rounded rectangle shrunk by ``inset``."""
    lo_x, hi_x = inset, RINK_W - 1 - inset
    lo_y, hi_y = inset, RINK_H - 1 - inset
    if not (lo_x <= x <= hi_x and lo_y <= y <= hi_y):
        return False
    radius = CORNER - inset
    cx = lo_x + radius if x < lo_x + radius else hi_x - radius if x > hi_x - radius else x
    cy = lo_y + radius if y < lo_y + radius else hi_y - radius if y > hi_y - radius else y
    return (x - cx) ** 2 + (y - cy) ** 2 <= (radius + 0.5) ** 2


@functools.cache
def spiral() -> tuple[tuple[int, int], ...]:
    """The left-half machine's path, a pixel at a time: round the boards, then inward each lap."""
    verts: list[tuple[int, int]] = []
    for k in range(LAPS):
        xl, xr = 2 + SWATH * k, 46 - SWATH * k
        top, bottom = 2 + SWATH * k, 29 - SWATH * k
        verts += [(xl, top), (xr, top), (xr, bottom), (xl, bottom)]
        if k < LAPS - 1:
            verts.append((xl, top + SWATH))
    points = [verts[0]]
    for (x0, y0), (x1, y1) in itertools.pairwise(verts):
        sx, sy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
        x, y = x0, y0
        while (x, y) != (x1, y1):
            x, y = x + sx, y + sy
            points.append((x, y))
    return tuple(points)


def _mirror(point: tuple[int, int]) -> tuple[int, int]:
    return RINK_W - 1 - point[0], RINK_H - 1 - point[1]


def path(machine: int) -> tuple[tuple[int, int], ...]:
    """Machine 0 spirals in the left half, machine 1 is its half-turn on the right."""
    return spiral() if machine == 0 else _mirror_path()


@functools.cache
def _mirror_path() -> tuple[tuple[int, int], ...]:
    return tuple(_mirror(p) for p in spiral())


@functools.cache
def _coverage() -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """For each machine, the first path index whose swath covers each pixel."""
    out = []
    for machine in (0, 1):
        first: dict[tuple[int, int], int] = {}
        for i, (x, y) in enumerate(path(machine)):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    first.setdefault((x + dx, y + dy), i)
        out.append(first)
    return out[0], out[1]


def _hash(x: int, y: int) -> int:
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return h ^ (h >> 16)


def _scratched(x: int, y: int) -> tuple[int, int, int]:
    """The dull ice: skate scratches as short horizontal streaks, light and dark, plus a little
    speckle."""
    streak = _hash(x // 5, y)
    if streak % 100 < 16:
        return DIRTY_LIGHT if (streak >> 8) % 2 else DIRTY_DARK
    speckle = _hash(x, y) % 100
    if speckle < 8:
        return DIRTY_LIGHT
    if speckle < 14:
        return DIRTY_DARK
    return DIRTY


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def ice_colour(x: int, y: int, reach: float, cover: tuple[dict, dict]) -> tuple[int, int, int]:
    """The ice at (x, y) once the machines have gone ``reach`` path pixels."""
    colour = _scratched(x, y)
    shine = 0.0
    for first in cover:
        i = first.get((x, y))
        if i is not None and i <= reach:
            colour = CLEAN
            shine = max(shine, max(0.0, 1.0 - (reach - i) / SHINE_PIXELS))
    if shine:
        colour = _blend(colour, SHINE, shine)
    for mx, mc in MARKINGS:
        if x == mx:
            colour = _blend(colour, mc, 0.35)
    return colour


def machine_pixels(
    x: int, y: int, heading: tuple[int, int], body: tuple[int, int, int]
) -> list[tuple[int, int, tuple[int, int, int]]]:
    """A machine seen from above, centred at (x, y): 7 long, 5 wide, cab at the front, an amber
    beacon at the back. Pixels off the panel are left out."""
    hx, hy = heading
    px, py = -hy, hx
    out = []
    for u in range(7):
        for v in range(-2, 3):
            if u == 6 and abs(v) > 1:
                continue
            if u in (4, 5) and abs(v) <= 1:
                colour = GLASS if u == 5 else CAB
            elif u == 1 and v == 0:
                colour = BEACON
            elif u == 0:
                colour = CAB
            else:
                colour = body
            wx, wy = x + hx * (u - 3) + px * v, y + hy * (u - 3) + py * v
            if 0 <= wx < RINK_W and 0 <= wy < RINK_H:
                out.append((wx, wy, colour))
    return out


def _heading(points: tuple[tuple[int, int], ...], i: int) -> tuple[int, int]:
    j = min(i + 1, len(points) - 1)
    k = j - 1 if j == i else i
    (x0, y0), (x1, y1) = points[k], points[j]
    dx, dy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
    return (dx, dy) if (dx or dy) else (1, 0)


def countdown_text(left: float) -> str:
    seconds = max(0, math.ceil(left))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def ordinal(period: int) -> str:
    return {1: "1ST", 2: "2ND", 3: "3RD"}.get(period, f"{period}TH")


def draw(r: Renderer, canvas: Any, game: Game, elapsed: float, total: float) -> None:
    """The page: the rink at the left, the countdown at the right."""
    canvas.Clear()
    p = progress(elapsed, total)
    cover = _coverage()
    length = len(spiral())
    reach = p * (length - 1)
    for y in range(RINK_H):
        for x in range(RINK_W):
            if not _inside(x, y, 0):
                continue
            colour = BOARD if not _inside(x, y, 1) else ice_colour(x, y, reach, cover)
            canvas.SetPixel(x, y, *colour)
    if elapsed <= clean_seconds(total) + EXIT_SECONDS:
        colours = (team_color(game.away.abbrev), team_color(game.home.abbrev))
        for machine in (0, 1):
            points = path(machine)
            i = min(length - 1, round(reach))
            x, y = points[i]
            for wx, wy, colour in machine_pixels(x, y, _heading(points, i), colours[machine]):
                canvas.SetPixel(wx, wy, *colour)
    cx = RINK_W + (r.width - RINK_W) // 2
    r.text_center(canvas, r.fonts.tiny, cx, 7, LABEL, f"{ordinal(game.period)} INT")
    left = total - elapsed
    r.text_center(canvas, r.fonts.medium, cx, 19, WHITE, countdown_text(left))
    done = p >= 1.0
    r.text_center(
        canvas, r.fonts.tiny, cx, 28, WHITE if done else LABEL, "READY" if done else "ZAMBONI"
    )
