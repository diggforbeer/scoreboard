"""``fb_cointoss`` (#389): the opening coin toss, settling on who **receives**.

The feed says who receives the opening kickoff and nothing more (not who won the toss, called it,
or deferred), so that is all this claims: a coin flips and lands showing the receiving team's logo,
then ``<TEAM> RECEIVE`` in the team's colour, with the kicking team small at the other edge with
``KICK``. Whole panel, silent. A pure function of the seconds since the stage began (6s,
``fb_cointoss_seconds``)::

    0.00-0.08  ``COIN TOSS`` in small type; the coin appears at the centre
    0.08-0.50  it flips: its width squeezes to a line and back, spinning fast then slow, rising
               and falling a few pixels
    0.50-0.58  it lands face-up, the face the receiving team's logo (its abbreviation without art)
    0.58-1.00  ``<TEAM> RECEIVE`` fades in; the kicking team's small logo fades in with ``KICK``

A single 64px panel drops the kicking team and ``KICK``. An overtime toss (the event's play is in
period 5 or later) reads ``OT COIN TOSS``. The event comes from the opening kickoff, because the
site feed omits the ``Coin Toss`` play (``football/events.py``).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..football.director import EVENT
from ..football.events import CoinToss
from ..football.teams import is_team, team_color
from .fonts import text_width
from .football_plays import DIM, WHITE, event_screen, r_fit

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

APPEAR_END, FLIP_END, LAND_END = 0.08, 0.50, 0.58
TEXT_FADE_END = 0.70
#: The coin: its radius in pixels, how far it rises while it flips, and the half-turns it makes.
RADIUS, RISE, HALF_TURNS = 8, 5, 6
FRONT, BACK = (225, 190, 70), (185, 185, 195)
KICKER_DIM = 0.45
CENTRE_Y = 14


def title(scene: Scene) -> str:
    """``COIN TOSS``, or ``OT COIN TOSS`` for a toss in overtime."""
    return "OT COIN TOSS" if scene.fb_event.play.period >= 5 else "COIN TOSS"


def coin_state(share: float) -> tuple[float, float, int]:
    """The coin at ``share`` of the stage: its horizontal radius (a line when edge-on), how far it
    has risen, and which face shows (``+1`` front, ``-1`` back)."""
    if share < APPEAR_END:
        return RADIUS * (share / APPEAR_END), 0.0, 1
    p = min(1.0, (share - APPEAR_END) / (FLIP_END - APPEAR_END))
    angle = math.pi * HALF_TURNS * (1 - (1 - p) ** 2)  # fast, then slow: ends face-up
    return (
        RADIUS * abs(math.cos(angle)),
        RISE * math.sin(math.pi * p),
        1 if math.cos(angle) >= 0 else -1,
    )


def draw_coin(r: Renderer, canvas: Any, cx: int, cy: int, rx: float, ry: int, color) -> None:
    for dy in range(-ry, ry + 1):
        half = max(0, round(max(rx, 0.5) * math.sqrt(max(0.0, 1 - (dy / max(ry, 1)) ** 2))))
        r.hline(canvas, cx - half, cx + half, cy + dy, color)


def draw_logo(canvas: Any, logo: Any, cx: int, cy: int, factor: float = 1.0) -> None:
    ox, oy = cx - logo.width // 2, cy - logo.height // 2
    for dx, dy, (red, green, blue) in logo.pixels:
        canvas.SetPixel(
            ox + dx, oy + dy, round(red * factor), round(green * factor), round(blue * factor)
        )


@event_screen(CoinToss, EVENT)
def draw_cointoss(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    canvas.Clear()
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    cx = r.width // 2
    team, kicker = event.team, event.kicker
    color = team_color(team) if is_team(team) else WHITE
    r.text(canvas, r.fonts.tiny, 2, 6, DIM, r_fit(title(scene), r.width - 4, r.fonts.tiny))

    if share < LAND_END:
        rx, rise, face = coin_state(share)
        radius = RADIUS if share >= APPEAR_END else round(RADIUS * share / APPEAR_END)
        draw_coin(
            r,
            canvas,
            cx,
            CENTRE_Y + 1 - round(rise),
            rx,
            max(radius, 1),
            FRONT if face > 0 else BACK,
        )
        return

    logo = r.nfl_logos.get(team, 16) if r.nfl_logos is not None and is_team(team) else None
    if logo is not None:
        draw_logo(canvas, logo, cx, CENTRE_Y)
    else:
        r.text_center(
            canvas, r.fonts.medium, cx, CENTRE_Y + 5, color, r_fit(team, 30, r.fonts.medium)
        )
    fade = min(1.0, (share - LAND_END) / (TEXT_FADE_END - LAND_END))
    if fade <= 0:
        return
    shade = tuple(round(c * fade) for c in color)
    text = f"{team} RECEIVE"
    font = r.fonts.small if text_width(r.fonts.small, text) <= r.width - 4 else r.fonts.tiny
    r.text_center(canvas, font, cx, r.height - 3, shade, r_fit(text, r.width - 4, font))
    if r.width >= 128 and kicker:
        small = r.nfl_logos.get(kicker, 12) if r.nfl_logos is not None and is_team(kicker) else None
        x = r.width - 14
        if small is not None:
            draw_logo(canvas, small, x, CENTRE_Y + 1, KICKER_DIM * fade)
        else:
            dim = tuple(
                round(c * KICKER_DIM * fade)
                for c in (team_color(kicker) if is_team(kicker) else WHITE)
            )
            r.text_center(canvas, r.fonts.small, x, CENTRE_Y + 4, dim, kicker)
        r.text_center(
            canvas, r.fonts.tiny, x, r.height - 2, tuple(round(c * fade) for c in DIM), "KICK"
        )
