"""``fb_touchdown`` (#390): the favourite scores a touchdown.

The football goal light, and deliberately built like it (full panel, no logos, no score in the
first seconds), reusing ``goal_light``'s building blocks. A pure function of the seconds since the
play (the 6s stage, ``fb_score_seconds``)::

    0.0-1.0s   a white flash, then both end zones pulse in the team's colour
    1.0-3.0s   the whole panel strobes in the team's colour; the ball is spiked at the goal line
    1.0-3.5s   TOUCHDOWN drops in one letter at a time, in the team's colour
    3.5-6.0s   a white shimmer sweeps across the letters; the team's name fades in along the bottom

A followed team's touchdown (``Scope.QUICK``) is the **quick version**: the plain score screen, a
static card with the headline, the team and the score, no animation. On a single 64px panel the
word wraps to two lines (``TOUCH`` / ``DOWN``) at normal size. The sound is a separate story and
plays the instant the score is detected, whatever is on screen: this module only draws.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..football.director import EVENT
from ..football.events import Scope, Touchdown
from ..football.teams import is_team, team, team_color
from . import football_field as ff
from .fonts import text_width
from .football_plays import WHITE, event_screen, r_fit
from .goal_light import _Buffer, _ease, _glyph, _scaled, _shimmer, _towards_white

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

WORD = "TOUCHDOWN"
FLASH_SECONDS = 0.12
END_ZONES_END = 1.0
STROBE_START, STROBE_END = 1.0, 3.0
STROBE_PERIOD = 0.2
LETTERS_START, LETTER_STAGGER, LETTER_DROP_SECONDS = 1.0, 0.17, 0.28
NAME_START, NAME_FADE_SECONDS = 3.5, 0.4
SHIMMER_START, SHIMMER_PERIOD = 3.5, 1.5
TEXT_SCALE = 2
TOP = 3
#: The ball: dropped at the goal line from this height (row) onto the ground.
BALL_FALL_START, BALL_FALL_END, BALL_BOUNCE_END = 1.0, 1.3, 1.7
BALL_GROUND, BALL_TOP, BOUNCE_HEIGHT = 26, 9, 6
END_ZONE_WIDTH_WIDE, END_ZONE_WIDTH_NARROW = 14, 7


def team_rgb(abbrev: str) -> tuple[int, int, int]:
    return team_color(abbrev) if is_team(abbrev) else WHITE


def city(abbrev: str) -> str:
    """What goes along the bottom: the team's short name (``NEW YORK G``), else its code."""
    return team(abbrev).name if is_team(abbrev) else abbrev


@event_screen(Touchdown, EVENT)
def draw_touchdown(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    if event.scope != Scope.FULL:
        draw_quick(r, canvas, scene)
        return
    canvas.Clear()
    age = max(0.0, scene.fb_elapsed)
    color = team_rgb(event.team)
    buf = _Buffer(r.width, r.height)
    wide = r.width >= 128

    if age < FLASH_SECONDS:
        buf.wash(WHITE, 0.35 * (1 - age / FLASH_SECONDS))
    if age < END_ZONES_END:
        _end_zones(buf, r.width, color, age, wide)
    elif age < STROBE_END:
        _strobe(buf, color, age)
    if BALL_FALL_START <= age < STROBE_END:
        _ball(buf, scene, r.width, age)
    if age >= LETTERS_START:
        if wide:
            _letters_wide(r, buf, color, age)
        else:
            _letters_narrow(r, buf, color, age)
    buf.flush(canvas)
    if age >= NAME_START:
        fade = _ease((age - NAME_START) / NAME_FADE_SECONDS)
        name = city(event.team)
        if text_width(r.fonts.small, name) > r.width:
            name = event.team
        r.text_center(
            canvas,
            r.fonts.small,
            r.width // 2,
            r.height - 1,
            _scaled(color, 0.35 + 0.65 * fade),
            name,
        )


# -- the first seconds -----------------------------------------------


def _end_zones(buf: _Buffer, width: int, color, age: float, wide: bool) -> None:
    """Both end zones pulsing in the team's colour (the white flash comes first)."""
    zone = END_ZONE_WIDTH_WIDE if wide else END_ZONE_WIDTH_NARROW
    glow = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(age * 14))
    shade = _scaled(color, glow)
    for y in range(buf.height):
        for x in list(range(zone)) + list(range(width - zone, width)):
            buf.add(x, y, shade, 1.0)


def _strobe(buf: _Buffer, color, age: float) -> None:
    """The whole panel alternating between lit and dark in the team's colour."""
    if int((age - STROBE_START) / (STROBE_PERIOD / 2)) % 2 == 0:
        buf.wash(color, 0.30)


def _ball(buf: _Buffer, scene: Scene, width: int, age: float) -> None:
    """The ball spiked at the goal line the scoring team attacked: it drops, bounces and rests."""
    event = scene.fb_event
    home = scene.fb_game.home.abbrev
    x = width - 14 if event.team == home else 13  # the far goal line (the home team attacks right)
    if age < BALL_FALL_END:
        t = (age - BALL_FALL_START) / (BALL_FALL_END - BALL_FALL_START)
        y = BALL_TOP + (BALL_GROUND - BALL_TOP) * t * t
    elif age < BALL_BOUNCE_END:
        t = (age - BALL_FALL_END) / (BALL_BOUNCE_END - BALL_FALL_END)
        y = BALL_GROUND - BOUNCE_HEIGHT * 4 * t * (1 - t)
    else:
        y = BALL_GROUND
    row = round(y)
    for dx in (-1, 0, 1):
        for dy in (0, 1):
            buf.set(x + dx, row + dy, ff.BALL)
    buf.set(x, row - 1, _scaled(ff.BALL, 0.7))


# -- the letters -----------------------------------------------------


def _drop(age: float, index: int, travel: int) -> tuple[int, float]:
    """How far above its place a letter still is, and how freshly it landed (0-1)."""
    start = LETTERS_START + LETTER_STAGGER * index
    drop = _ease((age - start) / LETTER_DROP_SECONDS)
    return round(travel * (1 - drop)), max(0.0, 1 - (age - start) / 0.25)


def _letters_wide(r: Renderer, buf: _Buffer, color, age: float) -> None:
    glyphs = [_glyph(r, ch) for ch in WORD]
    cell = max(advance for _, advance in glyphs) * TEXT_SCALE
    left = r.width // 2 - (cell * len(glyphs)) // 2
    for i, (pixels, advance) in enumerate(glyphs):
        if age < LETTERS_START + LETTER_STAGGER * i:
            continue
        lift, landing = _drop(age, i, 26)
        glyph_left = left + i * cell + (cell - advance * TEXT_SCALE) // 2
        for px, py in pixels:
            sweep = _shimmer_at(age, glyph_left + px * TEXT_SCALE)
            lit = _towards_white(color, min(1.0, landing * 0.9 + sweep * 0.75))
            for dx in range(TEXT_SCALE):
                for dy in range(TEXT_SCALE):
                    buf.set(
                        glyph_left + px * TEXT_SCALE + dx, TOP - lift + py * TEXT_SCALE + dy, lit
                    )


def _letters_narrow(r: Renderer, buf: _Buffer, color, age: float) -> None:
    """``TOUCH`` over ``DOWN`` at normal size, one letter at a time."""
    index = 0
    for row, word in enumerate(("TOUCH", "DOWN")):
        glyphs = [_glyph(r, ch) for ch in word]
        cell = max(advance for _, advance in glyphs)
        left = r.width // 2 - (cell * len(glyphs)) // 2
        for i, (pixels, advance) in enumerate(glyphs):
            if age >= LETTERS_START + LETTER_STAGGER * index:
                lift, landing = _drop(age, index, 28)
                glyph_left = left + i * cell + (cell - advance) // 2
                for px, py in pixels:
                    sweep = _shimmer_at(age, glyph_left + px)
                    lit = _towards_white(color, min(1.0, landing * 0.9 + sweep * 0.75))
                    buf.set(glyph_left + px, 2 + row * 14 - lift + py, lit)
            index += 1


def _shimmer_at(age: float, x: int) -> float:
    return _shimmer(age - (SHIMMER_START - 3.0), x)  # goal_light's band, started at 3.5s


# -- the quick version -----------------------------------------------


def draw_quick(r: Renderer, canvas: Any, scene: Scene) -> None:
    """A followed team's touchdown: the plain score screen, no animation."""
    event, game = scene.fb_event, scene.fb_game
    canvas.Clear()
    color = team_rgb(event.team)
    width = r.width - 4
    font = next(
        (
            f
            for f in (r.fonts.large, r.fonts.medium, r.fonts.small)
            if text_width(f, "TOUCHDOWN") <= width
        ),
        r.fonts.tiny,
    )
    r.text_center(canvas, font, r.width // 2, 13, color, "TOUCHDOWN")
    name = city(event.team)
    r.text_center(canvas, r.fonts.small, r.width // 2, 22, color, r_fit(name, width, r.fonts.small))
    score = f"{game.away.abbrev} {event.away_score}  {game.home.abbrev} {event.home_score}"
    r.text_center(canvas, r.fonts.tiny, r.width // 2, 30, WHITE, r_fit(score, width, r.fonts.tiny))
