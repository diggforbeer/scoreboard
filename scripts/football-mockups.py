#!/usr/bin/env python3
"""Draw the football screen mockups for football_screen.md as LED-dot PNGs.

    python scripts/football-mockups.py             # write docs/football/*.png

These are **design mockups, not renderer output**: no football renderer exists
yet, so each frame is drawn here, pixel by pixel, to show the layout the design
describes. They reuse the NHL guide's dot rendering (``scripts/render-screens.py``)
and the project's own BDF fonts, so size, pitch and type match the real panel.
Teams are real NFL abbreviations in plain colour circles, as the NHL guide does,
because the crests are team artwork and are not committed.

When the real renderer lands, the images should come from it (the way
``render-screens.py`` does for the NHL) and this script should be deleted.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from RGBMatrixEmulator import graphics  # noqa: E402

from nhl_scoreboard.display.ascii import AsciiCanvas  # noqa: E402
from nhl_scoreboard.display.fonts import font_path  # noqa: E402
from nhl_scoreboard.display.mirror import Frame  # noqa: E402

OUT = REPO_ROOT / "docs" / "football"

_spec = importlib.util.spec_from_file_location(
    "render_screens", REPO_ROOT / "scripts" / "render-screens.py"
)
render_screens = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_screens)

RGB = tuple[int, int, int]

# -- palette (LED-tuned, like display/teams.py) --------------------------------
WHITE: RGB = (255, 255, 255)
DIM: RGB = (120, 120, 120)
AMBER: RGB = (255, 176, 0)
RED: RGB = (230, 40, 40)
GREEN: RGB = (40, 220, 90)
YELLOW: RGB = (255, 225, 0)
BLUE_LINE: RGB = (70, 130, 255)
TURF: RGB = (0, 52, 16)
YARD: RGB = (0, 104, 40)
MID: RGB = (0, 150, 60)
BALL: RGB = (214, 130, 54)
TEAMS: dict[str, RGB] = {
    "NYG": (40, 110, 255),  # blue, lifted
    "WSH": (255, 184, 28),  # gold
    "ATL": (226, 24, 54),
    "CIN": (255, 110, 0),
}
NAMES = {"NYG": "NEW YORK", "WSH": "WASHINGTON", "ATL": "ATLANTA", "CIN": "CINCINNATI"}

_fonts: dict[str, object] = {}


def font(name: str):
    if name not in _fonts:
        f = graphics.Font()
        f.LoadFont(str(font_path(f"{name}.bdf")))
        _fonts[name] = f
    return _fonts[name]


def scale(c: RGB, k: float) -> RGB:
    return (int(c[0] * k), int(c[1] * k), int(c[2] * k))


class Panel:
    """A 128x32 (or 64x32) canvas with the few drawing calls the mockups need."""

    def __init__(self, width: int = 128) -> None:
        self.w = width
        self.h = 32
        self.canvas = AsciiCanvas(width, 32)

    def px(self, x: int, y: int, c: RGB) -> None:
        self.canvas.SetPixel(int(x), int(y), *c)

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: RGB) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.px(x, y, c)

    def vline(self, x: int, y0: int, y1: int, c: RGB) -> None:
        for y in range(y0, y1 + 1):
            self.px(x, y, c)

    def line(self, x0: float, y0: float, x1: float, y1: float, c: RGB) -> None:
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n + 1):
            t = i / n
            self.px(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), c)

    def disc(self, cx: float, cy: float, r: float, c: RGB) -> None:
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                    self.px(x, y, c)

    def text(self, name: str, x: int, baseline: int, c: RGB, s: str) -> int:
        return graphics.DrawText(self.canvas, font(name), x, baseline, graphics.Color(*c), s)

    def width_of(self, name: str, s: str) -> int:
        f = font(name)
        return sum(f.CharacterWidth(ord(ch)) for ch in s)

    def center(self, name: str, baseline: int, c: RGB, s: str, x0: int = 0, x1: int | None = None):
        x1 = self.w if x1 is None else x1
        self.text(name, x0 + (x1 - x0 - self.width_of(name, s)) // 2, baseline, c, s)

    def text2x(self, name: str, x: int, top: int, c: RGB, s: str) -> int:
        """Text at double size (one source pixel becomes a 2x2 block)."""
        tmp = AsciiCanvas(self.w, 32)
        f = font(name)
        base = 13  # 7x13B baseline within its own 13-row cell
        graphics.DrawText(tmp, f, 0, base, graphics.Color(*c), s)
        for (px, py), col in tmp.pixels.items():
            for dx in (0, 1):
                for dy in (0, 1):
                    self.px(x + px * 2 + dx, top + py * 2 + dy, col)
        return sum(f.CharacterWidth(ord(ch)) for ch in s) * 2

    def logo(self, cx: int, cy: int, team: str, r: float = 6, dim: float = 1.0) -> None:
        """A team's logo stand-in: a ring and a disc in its colour."""
        col = scale(TEAMS[team], dim)
        self.disc(cx, cy, r, col)
        self.disc(cx, cy, r - 2.5, scale(col, 0.45))

    def frame(self) -> Frame:
        buf = bytearray(self.w * self.h * 3)
        for (x, y), (r, g, b) in self.canvas.pixels.items():
            i = (y * self.w + x) * 3
            buf[i : i + 3] = bytes((r, g, b))
        return Frame(0, self.w, self.h, bytes(buf), 100, datetime(2026, 11, 13, tzinfo=UTC))


# -- the field -------------------------------------------------------------------
HOME, AWAY = "NYG", "WSH"
FIELD_TOP, FIELD_BOT = 8, 30


class Field:
    """Geometry of the field strip for a given panel width.

    ``yardLine`` runs 0-100 from the HOME goal line (the left end zone here), as in
    the feed, so the away team attacks toward 0 and the view must flip for it.
    """

    def __init__(self, panel: Panel, left: int = 0, right: int | None = None) -> None:
        self.p = panel
        right = panel.w if right is None else right
        self.left = left
        self.right = right
        self.ez = 14 if (right - left) >= 112 else 7
        self.x0 = left + self.ez  # x of yardLine 0
        self.span = (right - left) - 2 * self.ez  # pixels for 100 yards

    def x(self, yard_line: float) -> float:
        return self.x0 + self.span * yard_line / 100

    def draw(self, poss: str = HOME, dim_other: bool = True) -> None:
        p = self.p
        p.rect(self.left, FIELD_TOP, self.right - 1, FIELD_BOT, TURF)
        p.rect(self.left, FIELD_TOP, self.x0 - 1, FIELD_BOT, scale(TEAMS[HOME], 0.30))
        p.rect(int(self.x(100)), FIELD_TOP, self.right - 1, FIELD_BOT, scale(TEAMS[AWAY], 0.30))
        for yard in range(10, 100, 10):
            col = MID if yard == 50 else YARD
            p.vline(round(self.x(yard)), FIELD_TOP, FIELD_BOT, col)
        for yard in range(5, 100, 10):
            xx = round(self.x(yard))
            p.px(xx, FIELD_TOP + 3, YARD)
            p.px(xx, FIELD_BOT - 3, YARD)
        # logos in their end zones; the team with the ball is full brightness
        r = 6 if self.ez >= 14 else 3
        mid = (FIELD_TOP + FIELD_BOT) // 2
        p.logo(self.left + self.ez // 2, mid, HOME, r, 1.0 if poss == HOME else 0.45)
        p.logo(self.right - self.ez // 2 - 1, mid, AWAY, r, 1.0 if poss == AWAY else 0.45)

    def markers(self, yard_line: float, distance: int, poss: str = HOME) -> None:
        """Line of scrimmage and first-down line; the sign follows the drive direction."""
        p = self.p
        direction = 1 if poss == HOME else -1
        p.vline(round(self.x(yard_line)), FIELD_TOP, FIELD_BOT, BLUE_LINE)
        p.vline(round(self.x(yard_line + direction * distance)), FIELD_TOP, FIELD_BOT, YELLOW)

    def ball(self, yard_line: float, y: float | None = None, c: RGB = BALL) -> None:
        p = self.p
        bx = round(self.x(yard_line))
        by = round((FIELD_TOP + FIELD_BOT) / 2 if y is None else y)
        p.rect(bx - 1, by, bx + 1, by + 1, c)
        p.px(bx, by - 1, scale(c, 0.7))

    def number(self, yard_line: float, y: int, num: str, c: RGB = WHITE) -> None:
        self.p.text("4x6", round(self.x(yard_line)) - 3, y, c, num)


def band(p: Panel, left: str, right: str = "", c: RGB = WHITE, rc: RGB = AMBER) -> None:
    """The one-line status band across the top (tiny font)."""
    p.text("4x6", 1, 6, c, left)
    if right:
        p.text("4x6", p.w - p.width_of("4x6", right) - 1, 6, rc, right)


def trail(p: Panel, f: Field, a: float, b: float, y: int, c: RGB = WHITE) -> None:
    """A fading trail of dots from yard line ``a`` to ``b``."""
    steps = max(2, int(abs(f.x(b) - f.x(a))))
    for i in range(steps):
        t = i / steps
        k = 0.25 + 0.75 * (t if b > a else 1 - t) if b > a else 0.25 + 0.75 * (1 - t)
        p.px(round(f.x(a) + (f.x(b) - f.x(a)) * t), y, scale(c, k))


def arc(
    p: Panel,
    f: Field,
    a: float,
    b: float,
    base_y: float,
    height: float,
    upto: float = 1.0,
    c: RGB = WHITE,
) -> tuple[float, float]:
    """A dotted parabola from yard ``a`` to ``b``; draws the first ``upto`` of it."""
    xa, xb = f.x(a), f.x(b)
    n = max(8, int(abs(xb - xa)))
    last = (xa, base_y)
    for i in range(int(n * upto) + 1):
        t = i / n
        x = xa + (xb - xa) * t
        y = base_y - height * 4 * t * (1 - t)
        p.px(round(x), round(y), scale(c, 0.8))
        last = (x, y)
    return last


def burst(p: Panel, cx: int, cy: int, c: RGB) -> None:
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)):
        p.px(cx + dx, cy + dy, c)
    p.px(cx, cy, WHITE)


def flag(p: Panel, x: int, y: int) -> None:
    """A yellow penalty flag on a pole."""
    p.vline(x, y - 6, y, DIM)
    p.rect(x + 1, y - 6, x + 5, y - 4, YELLOW)
    p.rect(x + 1, y - 3, x + 3, y - 2, YELLOW)


def clock_icon(p: Panel, cx: int, cy: int, c: RGB = WHITE) -> None:
    for a in range(0, 360, 12):
        p.px(
            round(cx + 6 * math.cos(math.radians(a))), round(cy + 6 * math.sin(math.radians(a))), c
        )
    p.line(cx, cy, cx, cy - 4, c)
    p.line(cx, cy, cx + 3, cy, c)


# -- the screens -----------------------------------------------------------------
def fb_field() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    f.markers(28, 7)
    f.ball(28)
    band(p, "Q1 14:52", "2ND & 7  NYG 28")
    return p


def fb_field_redzone() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(AWAY)
    p.rect(round(f.x(0)), FIELD_TOP, round(f.x(20)), FIELD_BOT, (90, 0, 0))
    f.markers(14, 6, AWAY)
    f.ball(14)
    band(p, "Q2 03:12", "1ST & 6  NYG 14", WHITE, RED)
    return p


def fb_playtext() -> Panel:
    p = Panel()
    f = Field(p, 0, 64)
    f.draw(HOME)
    f.markers(46, 1)
    f.ball(46)
    p.text("4x6", 1, 6, WHITE, "Q1 14:13")
    x = 68
    for i, (line, col) in enumerate(
        [
            ("McCARTHY PASS", WHITE),
            ("SHORT MID TO", WHITE),
            ("I.LIKELY +9", GREEN),
            ("2ND & 1", AMBER),
            ("AT NYG 46", AMBER),
        ]
    ):
        p.text("4x6", x, 6 + i * 6, col, line)
    return p


def sack() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    f.markers(31, 10)
    trail(p, f, 25, 19, 20, AMBER)
    burst(p, round(f.x(19)), 20, RED)
    f.number(25, 17, "3")
    band(p, "Q1 09:21", "SACK -6  (95)", WHITE, RED)
    return p


def penalty() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    f.markers(33, 10)
    f.ball(33)
    flag(p, round(f.x(33)) + 3, 25)
    band(p, "Q2 12:56", "FLAG: FALSE START", WHITE, YELLOW)
    p.text("4x6", 1, 31, DIM, "")  # keep the band clear; detail below
    return p


def penalty_no_play() -> Panel:
    p = Panel()
    p.center("5x7", 10, YELLOW, "FLAG")
    p.center("4x6", 18, WHITE, "OFFENSIVE HOLDING")
    p.center("4x6", 25, AMBER, "10 YD  NO PLAY")
    flag(p, 14, 20)
    flag(p, p.w - 20, 20)
    return p


def timeout() -> Panel:
    p = Panel()
    p.logo(14, 16, HOME, 8)
    clock_icon(p, 40, 15)
    p.text("5x7", 52, 12, WHITE, "TIMEOUT")
    p.text("5x7", 52, 22, TEAMS[HOME], "NYG  2ND")
    p.text("4x6", 52, 30, DIM, "0:45")
    for i in range(3):
        c = TEAMS[HOME] if i < 1 else (40, 40, 40)
        p.rect(100 + i * 8, 12, 105 + i * 8, 17, c)
    p.text("4x6", 98, 25, DIM, "LEFT")
    return p


def halftime() -> Panel:
    p = Panel()
    p.center("7x13B", 15, WHITE, "HALFTIME")
    p.logo(14, 16, HOME, 7)
    p.logo(p.w - 15, 16, AWAY, 7)
    p.center("5x7", 28, WHITE, "NYG 10   WSH 7")
    return p


def end_quarter() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    f.markers(46, 1)
    f.ball(46)
    p.rect(20, 10, 107, 26, (0, 0, 0))
    p.center("7x13B", 22, AMBER, "END Q1")
    return p


def cointoss_flip() -> Panel:
    p = Panel()
    p.text("4x6", 2, 7, DIM, "COIN TOSS")
    cx, cy = 64, 15
    for y in range(-7, 8):
        half = round(2 * math.sqrt(max(0, 1 - (y / 7) ** 2)))
        for x in range(-half, half + 1):
            p.px(cx + x, cy + y - 3, (190, 190, 200))
    return p


def cointoss_result() -> Panel:
    p = Panel()
    p.text("4x6", 2, 7, DIM, "COIN TOSS")
    p.logo(64, 13, HOME, 8)
    p.center("5x7", 29, TEAMS[HOME], "NYG RECEIVE")
    p.text("4x6", p.w - 25, 31, DIM, "KICK")
    p.logo(p.w - 12, 15, AWAY, 4, 0.6)
    return p


def touchdown() -> Panel:
    p = Panel()
    for i in range(0, 160, 14):  # strobe rays
        p.line(i - 30, 0, i, 31, scale(TEAMS[HOME], 0.28))
    w = p.text2x("7x13B", 1, 0, TEAMS[HOME], "TOUCHDOWN")
    p.center("4x6", 31, WHITE, "NEW YORK")
    del w
    return p


def score_detail() -> Panel:
    p = Panel()
    p.logo(10, 16, HOME, 8)
    p.logo(p.w - 11, 16, AWAY, 8, 0.5)
    p.center("5x7", 8, WHITE, "14 I.LIKELY", 22, p.w - 22)
    p.center("4x6", 16, TEAMS[HOME], "9 YD PASS FROM", 22, p.w - 22)
    p.center("4x6", 22, TEAMS[HOME], "J.McCARTHY", 22, p.w - 22)
    p.center("4x6", 30, AMBER, "PAT GOOD  NYG 7 WSH 0", 22, p.w - 22)
    return p


def fieldgoal() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    for x in (round(f.x(100)) + 2, round(f.x(100)) + 10):  # uprights
        p.vline(x, 8, 22, YELLOW)
    p.vline(round(f.x(100)) + 6, 22, 30, YELLOW)
    p.line(round(f.x(100)) + 2, 22, round(f.x(100)) + 10, 22, YELLOW)
    arc(p, f, 83, 104, 23, 17, upto=0.85)
    f.ball(98, 8)
    band(p, "Q1 04:11", "FIELD GOAL 31 YD", WHITE, GREEN)
    return p


def fieldgoal_opponent() -> Panel:
    p2 = Panel()
    f = Field(p2)
    f.draw(AWAY)
    for x in (round(f.x(0)) - 11, round(f.x(0)) - 3):
        p2.vline(x, 8, 22, scale(YELLOW, 0.5))
    p2.line(round(f.x(0)) - 11, 22, round(f.x(0)) - 3, 22, scale(YELLOW, 0.5))
    arc(p2, f, 17, -4, 23, 17, upto=0.85)
    f.ball(2, 8)
    band(p2, "Q2 01:03", "WSH FIELD GOAL 38 YD", WHITE, DIM)
    return p2


def fg_miss() -> Panel:
    p = Panel()
    f = Field(p)
    f.draw(HOME)
    for x in (round(f.x(100)) + 2, round(f.x(100)) + 10):
        p.vline(x, 8, 22, YELLOW)
    p.line(round(f.x(100)) + 2, 22, round(f.x(100)) + 10, 22, YELLOW)
    arc(p, f, 80, 106, 24, 14, upto=0.9, c=RED)
    f.ball(103, 11, RED)
    band(p, "Q3 09:05", "NO GOOD  38 YD  WIDE LEFT", WHITE, RED)
    return p


def turnover() -> Panel:
    p = Panel()
    p.logo(11, 16, HOME, 8, 0.5)
    p.logo(p.w - 12, 16, AWAY, 8)
    p.center("7x13B", 14, RED, "INTERCEPTION", 22, p.w - 22)
    p.line(34, 22, 92, 22, scale(RED, 0.6))
    p.line(92, 22, 88, 19, scale(RED, 0.6))
    p.line(92, 22, 88, 25, scale(RED, 0.6))
    p.center("4x6", 31, WHITE, "INT  B.CARTER  ATL 43", 22, p.w - 22)
    return p


def reversal() -> Panel:
    p = Panel()
    p.logo(10, 16, HOME, 7)
    p.center("5x7", 9, AMBER, "TOUCHDOWN", 22, p.w - 22)
    p.center("5x7", 17, AMBER, "OVERTURNED", 22, p.w - 22)
    p.center("4x6", 24, WHITE, "OFF PASS INTERFERENCE", 22, p.w - 22)
    p.center("4x6", 31, DIM, "SCORE BACK TO NYG 0 WSH 0", 22, p.w - 22)
    flag(p, p.w - 12, 22)
    return p


# -- 64px (single panel) variants ------------------------------------------------
def fb_field_64() -> Panel:
    p = Panel(64)
    f = Field(p)
    f.draw(HOME)
    f.markers(28, 7)
    f.ball(28)
    band(p, "Q1 14:52", "2&7")
    return p


def cointoss_result_64() -> Panel:
    p = Panel(64)
    p.text("4x6", 2, 7, DIM, "COIN TOSS")
    p.logo(32, 15, HOME, 6)
    p.center("5x7", 29, TEAMS[HOME], "NYG RECEIVE")
    return p


def touchdown_64() -> Panel:
    p = Panel(64)
    for i in range(0, 100, 12):
        p.line(i - 20, 0, i, 31, scale(TEAMS[HOME], 0.28))
    p.center("7x13B", 14, TEAMS[HOME], "TOUCH")
    p.center("7x13B", 28, TEAMS[HOME], "DOWN")
    return p


SCREENS = {
    "fb_field": fb_field,
    "fb_field_redzone": fb_field_redzone,
    "fb_playtext": fb_playtext,
    "sack": sack,
    "penalty": penalty,
    "penalty_no_play": penalty_no_play,
    "timeout": timeout,
    "halftime": halftime,
    "end_quarter": end_quarter,
    "cointoss_flip": cointoss_flip,
    "cointoss_result": cointoss_result,
    "touchdown": touchdown,
    "score_detail": score_detail,
    "fieldgoal": fieldgoal,
    "fieldgoal_opponent": fieldgoal_opponent,
    "fg_miss": fg_miss,
    "turnover": turnover,
    "reversal": reversal,
    "fb_field_64": fb_field_64,
    "cointoss_result_64": cointoss_result_64,
    "touchdown_64": touchdown_64,
}


def real_screens() -> set[str]:
    """Screens the real renderer now draws (``football.demo``): their images come from
    ``render-screens.py --sport nfl``, so a mockup of the same name is retired, not rewritten."""
    from nhl_scoreboard.football.demo import nfl_demo_steps

    return {step.name for step in nfl_demo_steps(render_screens.NOW)}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    real = real_screens()
    for old in OUT.glob("*.png"):
        if old.stem in SCREENS and old.stem not in real:
            old.unlink()
    written = 0
    for name, build in SCREENS.items():
        if name in real:
            continue  # replaced by the real renderer: delete its entry above, not its image
        written += 1
        panel = build()
        render_screens.to_image(panel.frame()).save(OUT / f"{name}.png", optimize=True)
    print(f"Wrote {written} mockups to {OUT} ({len(real)} screens are real renders now)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
