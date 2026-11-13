"""Timeouts and the two-minute warning (#387): a clock icon that freezes, and who stopped it.

A full-panel card (there is no ball movement to show). The clock icon's hand **spins and
freezes**; beside it the stoppage is named::

    Timeout            TIMEOUT / NYG 2ND / 0:45, the team's logo, and its timeouts left as dots
    Official Timeout   OFFICIAL / TIMEOUT / 11:12, the icon in a neutral colour, no dots
    Two-Minute Warning 2-MIN / WARNING / 2:00, the icon in amber

The tiny font has no usable ``#``, so ``timeout #2`` is written ``2ND``. Timeouts left is
``3 - number`` from the text, replaced by the situation's own count when the feed gives one
(``homeTimeouts`` / ``awayTimeouts``). A single 64px panel drops the logo and the caption. A pure
function of the seconds since the stage began (3s)::

    0.00-0.35  the hand spins, slowing
    0.35-0.60  frozen; the ring flashes
    0.60-1.00  held
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..football.models import PlayKind
from ..football.teams import is_team, team_color
from .fonts import text_width
from .football_plays import DIM, WHITE, play_screen, r_fit

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

FREEZE_AT, FLASH_END = 0.35, 0.60
#: How many turns the hand makes before it stops, and the angle it stops at (degrees from 12).
SPIN_TURNS, STOP_ANGLE = 2.0, 150.0
TIMEOUTS_PER_HALF = 3
RADIUS = 7
OFFICIAL_ICON = (170, 170, 170)
WARNING_ICON = (255, 176, 0)
EMPTY_DOT = (40, 40, 40)


def kind_of(scene: Scene) -> str:
    return scene.fb_play.kind.value


def team_of(scene: Scene) -> str:
    """The team that called it (``""`` for an official timeout or the warning)."""
    return scene.fb_play.info.timeout_team if scene.fb_play.kind == PlayKind.TIMEOUT else ""


def timeouts_left(scene: Scene) -> int | None:
    """Timeouts the team has left: the situation's count when it has one, else ``3 - number``."""
    team = team_of(scene)
    if not team:
        return None
    game = scene.fb_game
    sit = game.situation if game is not None else None
    if sit is not None:
        count = sit.home_timeouts if team == game.home.abbrev else (
            sit.away_timeouts if team == game.away.abbrev else None
        )  # fmt: skip
        if count is not None:
            return max(0, min(TIMEOUTS_PER_HALF, count))
    number = scene.fb_play.info.timeout_number
    return None if number is None else max(0, min(TIMEOUTS_PER_HALF, TIMEOUTS_PER_HALF - number))


def ordinal(n: int | None) -> str:
    return {1: "1ST", 2: "2ND", 3: "3RD"}.get(n or 0, f"{n}TH" if n else "")


def lines(scene: Scene) -> tuple[str, str, str]:
    """The three lines of text: the headline, the second line, the clock."""
    play = scene.fb_play
    clock = play.info.timeout_clock or play.clock
    if play.kind == PlayKind.TIMEOUT:
        team = team_of(scene)
        return "TIMEOUT", f"{team} {ordinal(play.info.timeout_number)}".strip(), clock
    if play.kind == PlayKind.OFFICIAL_TIMEOUT:
        return "OFFICIAL", "TIMEOUT", clock
    return "2-MIN", "WARNING", "2:00"


def icon_color(scene: Scene) -> tuple[int, int, int]:
    play = scene.fb_play
    if play.kind == PlayKind.TIMEOUT:
        team = team_of(scene)
        return team_color(team) if is_team(team) else WHITE
    return OFFICIAL_ICON if play.kind == PlayKind.OFFICIAL_TIMEOUT else WARNING_ICON


def hand_angle(share: float) -> float:
    """Degrees clockwise from 12 o'clock: spinning, slowing, then frozen at ``STOP_ANGLE``."""
    p = max(0.0, min(1.0, share / FREEZE_AT))
    return STOP_ANGLE + 360.0 * SPIN_TURNS * (1 - p) ** 2


def draw_clock_icon(
    canvas: Any, cx: int, cy: int, color, angle: float, bright: float = 1.0
) -> None:
    """A round clock face with a fixed short hand and a long hand at ``angle``."""
    ring = tuple(round(c * bright) for c in color)
    for deg in range(0, 360, 12):
        rad = math.radians(deg)
        canvas.SetPixel(
            round(cx + RADIUS * math.sin(rad)), round(cy - RADIUS * math.cos(rad)), *ring
        )
    for length, deg, shade in ((RADIUS - 2, angle, 1.0), (RADIUS - 4, 300.0, 0.7)):
        rad = math.radians(deg)
        col = tuple(round(c * shade) for c in color)
        for step in range(length + 1):
            canvas.SetPixel(
                round(cx + step * math.sin(rad)), round(cy - step * math.cos(rad)), *col
            )
    canvas.SetPixel(cx, cy, *WHITE)


def draw_dots(r: Renderer, canvas: Any, x: int, y: int, left: int, color) -> None:
    """Three little squares, ``left`` of them lit in the team's colour."""
    for i in range(TIMEOUTS_PER_HALF):
        shade = color if i < left else EMPTY_DOT
        x0 = x + i * 7
        for dx in range(5):
            for dy in range(4):
                canvas.SetPixel(x0 + dx, y + dy, *shade)


def _draw(r: Renderer, canvas: Any, scene: Scene) -> None:
    canvas.Clear()
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    wide = r.width >= 128
    color = icon_color(scene)
    head, second, clock = lines(scene)
    left = timeouts_left(scene)
    team = team_of(scene)

    icon_x = 40 if wide else 10
    text_x = 52 if wide else 22
    if wide and team:
        logo = r.nfl_logos.get(team, 16) if r.nfl_logos is not None and is_team(team) else None
        if logo is not None:
            ox, oy = 14 - logo.width // 2, 16 - logo.height // 2
            for dx, dy, (red, green, blue) in logo.pixels:
                canvas.SetPixel(ox + dx, oy + dy, red, green, blue)
        else:
            r.text_center(canvas, r.fonts.small, 14, 19, color, r_fit(team, 24, r.fonts.small))
    flash = 1.0 + 0.6 * math.sin(math.pi * (share - FREEZE_AT) / (FLASH_END - FREEZE_AT)) \
        if FREEZE_AT <= share < FLASH_END else 1.0  # fmt: skip
    draw_clock_icon(canvas, icon_x, 15 if wide else 16, color, hand_angle(share), min(flash, 1.6))

    room = r.width - text_x - 2 - (30 if wide and left is not None else 0)
    r.text(
        canvas, r.fonts.small, text_x, 12 if wide else 11, WHITE, r_fit(head, room, r.fonts.small)
    )
    r.text(
        canvas, r.fonts.small, text_x, 22 if wide else 20, color, r_fit(second, room, r.fonts.small)
    )
    r.text(canvas, r.fonts.tiny, text_x, 30, DIM, r_fit(clock, room, r.fonts.tiny))
    if left is not None:
        if wide:
            draw_dots(r, canvas, 98, 12, left, color)
            r.text(canvas, r.fonts.tiny, 99, 25, DIM, "LEFT")
        else:
            draw_dots(r, canvas, text_x + text_width(r.fonts.tiny, clock) + 3, 26, left, color)


@play_screen(PlayKind.TIMEOUT)
def draw_timeout(r: Renderer, canvas: Any, scene: Scene) -> None:
    _draw(r, canvas, scene)


@play_screen(PlayKind.OFFICIAL_TIMEOUT)
def draw_official_timeout(r: Renderer, canvas: Any, scene: Scene) -> None:
    _draw(r, canvas, scene)


@play_screen(PlayKind.TWO_MINUTE_WARNING)
def draw_two_minute_warning(r: Renderer, canvas: Any, scene: Scene) -> None:
    _draw(r, canvas, scene)
