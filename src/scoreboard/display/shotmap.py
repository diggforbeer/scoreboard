"""The shot map: a page of the intermission stats showing where each team's shots came from.

The whole rink, drawn small and centred (200 ft by 85 ft at 0.375 px a foot is 75 by 32 pixels),
with each team's shots on goal glowing at the net it is attacking: the away team's at the left end,
the home team's at the right, whichever way they really shot that period (``hockey.models.ShotMap``
already has them that way). Each shot adds a soft round glow; where they pile up the glow brightens
from a dim shade of the team's colour to its full colour and, at the hottest spot, towards white. A
goal is a white dot on top. The team's abbreviation and its shot count sit at the panel's edges.

128px panels only: the rink does not fit narrower ones, so the page is not offered there. A pure
function of the shots: nothing moves.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..hockey.models import RINK_HALF_LENGTH, RINK_HALF_WIDTH, ShotMap
from .teams import team_color

if TYPE_CHECKING:
    from ..hockey.models import Game
    from .renderer import Renderer

#: Pixels per foot (one scale both ways, so the rink keeps its shape).
SCALE = 0.375
RINK_W = round(2 * RINK_HALF_LENGTH * SCALE)  # 75
RINK_H = round(2 * RINK_HALF_WIDTH * SCALE)  # 32
#: How far one shot's glow reaches (the Gaussian's sigma, in feet), and the glow strength a pixel
#: needs to light at all and to count as the hottest, so one lone shot still shows.
SIGMA_FT = 6.0
LIGHT_AT = 0.04
FULL_AT = 1.8
MIN_PANEL_WIDTH = RINK_W + 2 * 24  # room for a label at each edge

#: The rink's corners are rounded where the end boards meet the sides (28 ft in the real rink).
CORNER = round(28 * SCALE)

OUTLINE = (38, 38, 52)
CENTRE_LINE = (90, 24, 24)
GOAL_LINE = (70, 20, 20)
BLUE_LINE = (22, 30, 90)
COUNT = (255, 255, 255)
GOAL_DOT = (255, 255, 255)


def fits(width: int) -> bool:
    """Whether a panel is wide enough for the shot map page."""
    return width >= MIN_PANEL_WIDTH


def in_rink(px: int, py: int, width: int = RINK_W, height: int = RINK_H) -> bool:
    """Whether the pixel (``px``, ``py`` from the rink's top-left corner) is on the ice: inside the
    rectangle and, in each corner, inside the quarter circle that rounds it."""
    if not (0 <= px < width and 0 <= py < height):
        return False
    cx = CORNER if px < CORNER else width - 1 - CORNER if px > width - 1 - CORNER else px
    cy = CORNER if py < CORNER else height - 1 - CORNER if py > height - 1 - CORNER else py
    return (px - cx) ** 2 + (py - cy) ** 2 <= (CORNER + 0.5) ** 2


def heat_grid(points: list[tuple[float, float]], width: int = RINK_W, height: int = RINK_H):
    """The glow of ``points`` (rink feet, centre ice at 0,0) on a ``width`` x ``height`` pixel grid
    covering the whole rink: the sum of one Gaussian per shot. Returns rows of floats."""
    grid = [[0.0] * width for _ in range(height)]
    reach = math.ceil(SIGMA_FT * SCALE * 2.5)
    for x_ft, y_ft in points:
        cx = (x_ft + RINK_HALF_LENGTH) * SCALE
        cy = (y_ft + RINK_HALF_WIDTH) * SCALE
        for py in range(max(0, int(cy) - reach), min(height, int(cy) + reach + 1)):
            for px in range(max(0, int(cx) - reach), min(width, int(cx) + reach + 1)):
                dist2 = ((px + 0.5 - cx) / SCALE) ** 2 + ((py + 0.5 - cy) / SCALE) ** 2
                grid[py][px] += math.exp(-dist2 / (2 * SIGMA_FT**2))
    return grid


def shade(strength: float, base: tuple[int, int, int], peak: float) -> tuple[int, int, int] | None:
    """The pixel colour for a glow ``strength``: ``None`` when too faint, a dimmed team colour that
    brightens with it, then towards white at the hottest spot."""
    t = min(1.0, strength / peak) if peak else 0.0
    if t < LIGHT_AT:
        return None
    if t < 0.85:
        return tuple(min(255, round(v * (0.18 + 0.82 * t))) for v in base)
    mix = (t - 0.85) / 0.15 * 0.7
    return tuple(round(v + (255 - v) * mix) for v in base)


def draw_shot_map(r: Renderer, canvas: Any, game: Game, shots: ShotMap) -> None:
    """Draw the page (see the module docstring) on a cleared canvas."""
    x0 = (r.width - RINK_W) // 2
    _rink(canvas, x0)
    colours = {"away": team_color(game.away.abbrev), "home": team_color(game.home.abbrev)}
    layers = {side: heat_grid([(s.x, s.y) for s in shots.of(side)]) for side in ("away", "home")}
    peak = max(FULL_AT, max(max(row) for grid in layers.values() for row in grid))
    for side, grid in layers.items():
        for py, row in enumerate(grid):
            for px, strength in enumerate(row):
                colour = shade(strength, colours[side], peak)
                if colour is not None and in_rink(px, py):
                    canvas.SetPixel(x0 + px, py, *colour)
    for s in shots.shots:
        if s.goal:
            px = round((s.x + RINK_HALF_LENGTH) * SCALE)
            py = round((s.y + RINK_HALF_WIDTH) * SCALE)
            if in_rink(px, py):
                canvas.SetPixel(x0 + px, py, *GOAL_DOT)
    font = r.fonts.tiny
    for side, abbrev, edge in (("away", game.away.abbrev, 1), ("home", game.home.abbrev, None)):
        count = str(len(shots.of(side)))
        if edge is not None:
            r.text(canvas, font, edge, 8, colours[side], abbrev)
            r.text(canvas, font, edge, 16, COUNT, count)
        else:
            r.text_right(canvas, font, r.width - 1, 8, colours[side], abbrev)
            r.text_right(canvas, font, r.width - 1, 16, COUNT, count)


def _rink(canvas: Any, x0: int) -> None:
    """The rink's outline (rounded at the corners), centre, blue and goal lines, dim so the glow
    reads over them. The lines stop at the outline."""
    for py in range(RINK_H):
        for px in range(RINK_W):
            if not in_rink(px, py):
                continue
            edge = not all(
                in_rink(px + dx, py + dy) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            colour = OUTLINE if edge else _line_colour(px)
            if colour is not None:
                canvas.SetPixel(x0 + px, py, *colour)


def _line_colour(px: int) -> tuple[int, int, int] | None:
    """The colour of the rink's marking at column ``px``, or ``None`` for plain ice."""
    for feet, colour in (
        (0, CENTRE_LINE),
        (-25, BLUE_LINE),
        (25, BLUE_LINE),
        (-89, GOAL_LINE),
        (89, GOAL_LINE),
    ):
        if px == round((feet + RINK_HALF_LENGTH) * SCALE):
            return colour
    return None
