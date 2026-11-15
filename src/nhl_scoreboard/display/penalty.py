"""The penalty screen (#340): who took it and what for, with a short entrance.

A pure function of ``age`` (seconds since the penalty was announced), like
``goal_light``, so tests, the demo and the live view can draw any frame and the
clock alone drives the animation. No logos: the 64px column between them is too
tight for a name, a call and a time.

Timeline (``TOTAL_SECONDS`` long):

* 0.0-1.0s  the hazard-tape border strobes solid.
* 0.1-1.6s  a whistle shakes in the middle; rings ripple out from it (to 2.0s).
* 1.6s on   ``PENALTY  NSH``, the player, then the call and its length fade in.
* 2.5s on   settled: the border keeps marching slowly until the screen ends.

Severity sets the colour of the border, the title and the call: minor amber,
major red, misconduct dim red. The player's line is in the team's colour.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from ..nhl.models import Penalty
from .fonts import text_width
from .teams import team_color

if TYPE_CHECKING:
    from .renderer import Renderer

RGB = tuple[int, int, int]

ENTRANCE_SECONDS = 2.5
SETTLED_SECONDS = 4.0
TOTAL_SECONDS = ENTRANCE_SECONDS + SETTLED_SECONDS

STROBE_SECONDS = 1.0
STROBE_PERIOD = 0.1
WHISTLE_START = 0.1
WHISTLE_END = 1.6
RIPPLE_END = 2.0
RIPPLE_START = 0.25
RIPPLE_STAGGER = 0.4
RIPPLE_SECONDS = 1.4
RIPPLE_SPEED = 30.0
TEXT_START = 1.6
LINE_STAGGER = 0.25
FADE_SECONDS = 0.4
#: Border thickness, in pixels, and its stripe width along the diagonal.
BORDER = 2
STRIPE = 3
MARCH_PX_PER_SECOND = 8.0

SEVERITY_COLORS: dict[str, RGB] = {
    "minor": (255, 176, 0),
    "major": (235, 50, 50),
    "misconduct": (150, 30, 30),
}

#: descKey -> the label for the 5x7 font. Anything missing falls back to
#: ``_label``'s title-case-and-truncate.
LABELS = {
    "slashing": "SLASHING",
    "tripping": "TRIPPING",
    "hooking": "HOOKING",
    "holding": "HOLDING",
    "interference": "INTERFERENCE",
    "high-sticking": "HIGH STICK",
    "roughing": "ROUGHING",
    "cross-checking": "CROSS CHECK",
    "boarding": "BOARDING",
    "charging": "CHARGING",
    "elbowing": "ELBOWING",
    "kneeing": "KNEEING",
    "fighting": "FIGHTING",
    "delaying-game": "DELAY OF GAME",
    "delay-of-game": "DELAY OF GAME",
    "delaying-game-puck-over-glass": "PUCK OVER GLASS",
    "too-many-men-on-the-ice": "TOO MANY MEN",
    "unsportsmanlike-conduct": "UNSPORTSMANLIKE",
    "instigator": "INSTIGATOR",
    "instigator-misconduct": "INSTIGATOR",
    "misconduct": "MISCONDUCT",
    "game-misconduct": "GAME MISCONDUCT",
    "match-penalty": "MATCH PENALTY",
    "embellishment": "DIVING",
    "diving": "DIVING",
    "goalkeeper-interference": "GOALIE INTERFERENCE",
    "interference-goalkeeper": "GOALIE INTERFERENCE",
    "illegal-check-to-head": "HEAD CHECK",
    "spearing": "SPEARING",
    "butt-ending": "BUTT ENDING",
    "clipping": "CLIPPING",
    "checking-from-behind": "FROM BEHIND",
    "closing-hand-on-puck": "HAND ON PUCK",
    "holding-the-stick": "HOLDING STICK",
    "face-off-violation": "FACEOFF VIOLATION",
    "bench-minor": "BENCH MINOR",
    "bench": "BENCH MINOR",
}
LABEL_MAX = 18


def label(desc_key: str) -> str:
    """The short call name for ``desc_key``: the table, else its words, capped."""
    known = LABELS.get(desc_key)
    if known:
        return known
    words = " ".join(w for w in desc_key.replace("_", "-").split("-") if w).upper()
    return (words or "PENALTY")[:LABEL_MAX]


def length(minutes: int) -> str:
    return f"{minutes}:00"


def lines(p: Penalty) -> tuple[str, str, str]:
    """``(title, who, what)`` for the three lines of the settled frame."""
    if p.is_fight:
        return "FIGHT", "FIGHTING", length(p.minutes)
    if p.is_bench:
        who = "BENCH MINOR"
    elif p.sweater_number is not None:
        who = f"#{p.sweater_number} {p.surname}"
    else:
        who = p.surname
    return "PENALTY", who, f"{label(p.desc_key)}  {length(p.minutes)}"


def severity_color(p: Penalty) -> RGB:
    return SEVERITY_COLORS.get(p.severity, SEVERITY_COLORS["minor"])


def draw(r: Renderer, canvas: Any, p: Penalty, age: float) -> None:
    """Draw ``p`` at ``age`` seconds. Everything is clipped to the panel."""
    canvas.Clear()
    width, height = r.width, r.height
    colour = severity_color(p)

    _border(canvas, width, height, colour, age)
    if WHISTLE_START <= age < RIPPLE_END:
        _ripples(canvas, width, height, colour, age)
    if WHISTLE_START <= age < WHISTLE_END:
        shake = round(math.sin(age * 40) * 1.5)
        _whistle(canvas, width // 2 - len(_WHISTLE[0]) // 2 + shake, height // 2 - 3, colour)

    if age >= TEXT_START:
        _text(r, canvas, p, colour, age)


# -- text --------------------------------------------------------------------


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _scaled(colour: RGB, k: float) -> RGB:
    return (int(colour[0] * k), int(colour[1] * k), int(colour[2] * k))


def _fit(text: str, fonts: list[Any], room: int) -> tuple[Any, str]:
    """The first font the text fits in, else the smallest with the text cut."""
    for font in fonts:
        if text_width(font, text) <= room:
            return font, text
    font = fonts[-1]
    while text and text_width(font, text) > room:
        text = text[:-1]
    return font, text


def _text(r: Renderer, canvas: Any, p: Penalty, colour: RGB, age: float) -> None:
    title, who, what = lines(p)
    cx = r.width // 2
    room = r.width - 2 * (BORDER + 2)
    team = team_color(p.team_abbrev)
    fade = [_ease((age - TEXT_START - LINE_STAGGER * i) / FADE_SECONDS) for i in range(3)]

    # Line 1: the title in the severity colour, the team beside it in its own.
    tiny = r.fonts.tiny
    head = f"{title}  "
    total = text_width(tiny, head) + text_width(tiny, p.team_abbrev)
    left = cx - total // 2
    r.text(canvas, tiny, left, 8, _scaled(colour, 0.35 + 0.65 * fade[0]), head)
    r.text(
        canvas,
        tiny,
        left + text_width(tiny, head),
        8,
        _scaled(team, 0.35 + 0.65 * fade[0]),
        p.team_abbrev,
    )

    font, who = _fit(who, [r.fonts.medium, r.fonts.small, r.fonts.tiny], room)
    r.text_center(canvas, font, cx, 19, _scaled(team, 0.35 + 0.65 * fade[1]), who)

    font, what = _fit(what, [r.fonts.small, r.fonts.tiny], room)
    r.text_center(canvas, font, cx, 28, _scaled(colour, 0.35 + 0.65 * fade[2]), what)


# -- border, whistle, ripples ------------------------------------------------


def _set(canvas: Any, width: int, height: int, x: int, y: int, rgb: RGB) -> None:
    if 0 <= x < width and 0 <= y < height:
        canvas.SetPixel(x, y, *rgb)


def _border(canvas: Any, width: int, height: int, colour: RGB, age: float) -> None:
    """Hazard tape round the edge: diagonal stripes marching along it."""
    solid = age < STROBE_SECONDS and int(age / STROBE_PERIOD) % 2 == 0
    march = int(age * MARCH_PX_PER_SECOND)
    for y in range(height):
        for x in range(width):
            if BORDER <= x < width - BORDER and BORDER <= y < height - BORDER:
                continue
            if solid or ((x + y + march) // STRIPE) % 2 == 0:
                canvas.SetPixel(x, y, *colour)


_WHISTLE = (
    "..XXXXXX....",
    ".XXXXXXXX...",
    "XXXX..XXXXXX",
    "XXXX..XXXXXX",
    ".XXXXXXXX...",
    "..XXXXXX....",
)


def _whistle(canvas: Any, x0: int, y0: int, colour: RGB) -> None:
    for dy, row in enumerate(_WHISTLE):
        for dx, ch in enumerate(row):
            if ch == "X":
                canvas.SetPixel(x0 + dx, y0 + dy, *colour)


def _ripples(canvas: Any, width: int, height: int, colour: RGB, age: float) -> None:
    cx, cy = width // 2, height // 2
    for i in range(3):
        t = age - RIPPLE_START - RIPPLE_STAGGER * i
        if t < 0 or t > RIPPLE_SECONDS:
            continue
        radius = 4 + t * RIPPLE_SPEED
        rgb = _scaled(colour, 0.9 * (1 - t / RIPPLE_SECONDS))
        steps = int(2 * math.pi * radius) + 8
        for s in range(steps):
            a = 2 * math.pi * s / steps
            _set(
                canvas,
                width,
                height,
                cx + round(radius * math.cos(a)),
                cy + round(radius * math.sin(a)),
                rgb,
            )
