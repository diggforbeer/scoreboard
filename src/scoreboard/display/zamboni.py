"""The Zamboni page of the intermission screen (#526): a top-down rink resurfaced during the break.

The ice starts scratched and dull. Two machines split the rink along its length at the centre
line, one working the top half and one the bottom, each in the same inward spiral (the pattern the
owner drew in #526): along the top boards, down the far end, back along the middle, up the near end,
then the inner lap, in 3px swaths. Everything they have passed turns to clean, light ice with a
brief wet shine behind them. The machines are drawn in the two teams' colours; the rink is a
rounded rectangle with faint markings (lines and face-off circles); the countdown is at the right.

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
#: The rink's corners are rounded ellipses (the owner's reference drawing, stretched to this panel's
#: shape): wider than tall, since 200 ft is drawn 96px across but 85 ft only 32px down.
CORNER_X, CORNER_Y = 10, 7
SWATH = 3
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

#: Faint rink markings, after the reference drawing: (x, colour, strength) lines (centre, blue,
#: goal)
#: and (centre x, centre y, radius x, radius y) face-off circles.
LINES = (
    (47, RED_LINE, 0.35),
    (48, RED_LINE, 0.35),
    (34, BLUE_LINE, 0.4),
    (61, BLUE_LINE, 0.4),
    (6, RED_LINE, 0.3),
    (89, RED_LINE, 0.3),
)
CIRCLES = (
    (47.5, 15.5, 7.0, 5.5),
    (15.0, 9.0, 7.0, 5.0),
    (15.0, 23.0, 7.0, 5.0),
    (80.0, 9.0, 7.0, 5.0),
    (80.0, 23.0, 7.0, 5.0),
)
CIRCLE_STRENGTH = 0.28


def _on_circle(x: int, y: int) -> bool:
    for cx, cy, rx, ry in CIRCLES:
        d = math.hypot((x - cx) / rx, (y - cy) / ry)
        if abs(d - 1.0) * min(rx, ry) < 0.6:
            return True
    return False


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
    rx, ry = CORNER_X - inset, CORNER_Y - inset
    cx = lo_x + rx if x < lo_x + rx else hi_x - rx if x > hi_x - rx else x
    cy = lo_y + ry if y < lo_y + ry else hi_y - ry if y > hi_y - ry else y
    return ((x - cx) / (rx + 0.5)) ** 2 + ((y - cy) / (ry + 0.5)) ** 2 <= 1.0


def _nudge(x: int, ys: range, step: int) -> int:
    """``x`` moved by ``step`` until a machine's centre is on the ice (2px in from the boards) along
    every row of ``ys``: the spiral's legs keep clear of the rounded corners."""
    while not all(_inside(x, y, 2) for y in ys):
        x += step
    return x


@functools.cache
def path(machine: int) -> tuple[tuple[int, int], ...]:
    """A machine's route, a pixel at a time. Machine 0 works the top half of the rink and machine 1
    the bottom, the same shape: east along the outer board, down the far end, west along the middle,
    up the near end, then the inner lap (east, down, west, up) and a last pass east through the
    middle. Legs are pulled in where a rounded corner would put the machine on the boards."""
    oy = 15 * machine
    a, b, c, d, e = 2 + oy, 14 + oy, 5 + oy, 11 + oy, 8 + oy
    xa = _nudge(2, range(a, a + 1), 1)
    xb = _nudge(93, range(a, b + 1), -1)
    xc = _nudge(2, range(c, b + 1), 1)
    xd = _nudge(min(90, xb - SWATH), range(c, d + 1), -1)
    xe = _nudge(max(5, xc + SWATH), range(e, d + 1), 1)
    xf = _nudge(min(88, xd - 2), range(e, e + 1), -1)
    verts = [(xa, a), (xb, a), (xb, b), (xc, b), (xc, c), (xd, c), (xd, d), (xe, d), (xe, e)]
    verts.append((xf, e))
    points = [verts[0]]
    for (x0, y0), (x1, y1) in itertools.pairwise(verts):
        sx, sy = (x1 > x0) - (x1 < x0), (y1 > y0) - (y1 < y0)
        x, y = x0, y0
        while (x, y) != (x1, y1):
            x, y = x + sx, y + sy
            points.append((x, y))
    return tuple(points)


@functools.cache
def _coverage() -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """For each machine, the path index at which each pixel of its half is cleaned: the first one
    whose 3px swath covers it, and for the few corner pixels no swath reaches, that of the nearest
    pixel that is (the driver's rounded corner)."""
    out = []
    for machine in (0, 1):
        first: dict[tuple[int, int], int] = {}
        for i, (x, y) in enumerate(path(machine)):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    first.setdefault((x + dx, y + dy), i)
        rows = range(16 * machine, 16 * machine + 16)
        todo = {
            (x, y) for y in rows for x in range(RINK_W) if _inside(x, y, 1) and (x, y) not in first
        }
        while todo:
            filled = {}
            for x, y in todo:
                near = [
                    first[(x + dx, y + dy)]
                    for dx in (-1, 0, 1)
                    for dy in (-1, 0, 1)
                    if (x + dx, y + dy) in first
                ]
                if near:
                    filled[(x, y)] = min(near)
            if not filled:
                break
            first.update(filled)
            todo -= set(filled)
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


def ice_colour(
    x: int, y: int, reaches: tuple[float, float], cover: tuple[dict, dict]
) -> tuple[int, int, int]:
    """The ice at (x, y) once the two machines have gone ``reaches`` path pixels."""
    colour = _scratched(x, y)
    shine = 0.0
    for first, reach in zip(cover, reaches, strict=True):
        i = first.get((x, y))
        if i is not None and i <= reach:
            colour = CLEAN
            shine = max(shine, max(0.0, 1.0 - (reach - i) / SHINE_PIXELS))
    if shine:
        colour = _blend(colour, SHINE, shine)
    for mx, mc, strength in LINES:
        if x == mx:
            colour = _blend(colour, mc, strength)
    if _on_circle(x, y):
        colour = _blend(colour, RED_LINE, CIRCLE_STRENGTH)
    return colour


def machine_pixels(
    x: int, y: int, heading: tuple[int, int], body: tuple[int, int, int]
) -> list[tuple[int, int, tuple[int, int, int]]]:
    """A machine seen from above, centred at (x, y): 7 long, 5 wide, cab at the front, an amber
    beacon at the back. Pixels off the rink (the rounded corners) are left out."""
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
            if _inside(wx, wy, 0):
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
    reaches = tuple(p * (len(path(m)) - 1) for m in (0, 1))
    for y in range(RINK_H):
        for x in range(RINK_W):
            if not _inside(x, y, 0):
                continue
            colour = BOARD if not _inside(x, y, 1) else ice_colour(x, y, reaches, cover)
            canvas.SetPixel(x, y, *colour)
    if elapsed <= clean_seconds(total) + EXIT_SECONDS:
        colours = (team_color(game.away.abbrev), team_color(game.home.abbrev))
        for machine in (0, 1):
            points = path(machine)
            i = min(len(points) - 1, round(reaches[machine]))
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
