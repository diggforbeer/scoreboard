"""Drawing the scoreboard onto a matrix canvas.

The layout targets the default 128x32 chain (two 64x32 P2 panels) but is
computed from the canvas size, so a 64x32 or 128x64 panel still renders
sensibly -- just with less or more breathing room.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..nhl.models import Game
from .fonts import FontSet, text_width
from .teams import team_color

WHITE = (255, 255, 255)
DIM = (48, 48, 48)
LIVE = (0, 235, 90)
INTERMISSION = (255, 170, 0)
FINAL = (150, 150, 150)
PREGAME = (90, 180, 255)
ACCENT = (255, 210, 0)
SUBDUED = (110, 110, 110)


class Renderer:
    def __init__(
        self,
        graphics: Any,
        fonts: FontSet,
        width: int,
        height: int,
        tz: ZoneInfo,
        favourite: str = "",
    ) -> None:
        self.g = graphics
        self.fonts = fonts
        self.width = width
        self.height = height
        self.tz = tz
        self.favourite = favourite.strip().upper()
        self._colors: dict[tuple[int, int, int], Any] = {}

    # -- primitives ------------------------------------------------------

    def color(self, rgb: tuple[int, int, int]) -> Any:
        """Cache Color objects; the backend allocates on construction."""
        if rgb not in self._colors:
            self._colors[rgb] = self.g.Color(*rgb)
        return self._colors[rgb]

    def text(self, canvas: Any, font: Any, x: int, y: int, rgb: tuple[int, int, int], s: str) -> int:
        return self.g.DrawText(canvas, font, x, y, self.color(rgb), s)

    def text_right(self, canvas: Any, font: Any, right: int, y: int, rgb, s: str) -> int:
        return self.text(canvas, font, right - text_width(font, s), y, rgb, s)

    def text_center(self, canvas: Any, font: Any, cx: int, y: int, rgb, s: str) -> int:
        return self.text(canvas, font, cx - text_width(font, s) // 2, y, rgb, s)

    def hline(self, canvas: Any, x0: int, x1: int, y: int, rgb: tuple[int, int, int]) -> None:
        self.g.DrawLine(canvas, x0, y, x1, y, self.color(rgb))

    def vline(self, canvas: Any, x: int, y0: int, y1: int, rgb: tuple[int, int, int]) -> None:
        self.g.DrawLine(canvas, x, y0, x, y1, self.color(rgb))

    # -- scenes ----------------------------------------------------------

    def draw_game(self, canvas: Any, game: Game) -> None:
        canvas.Clear()
        half = self.width // 2
        score_baseline = 13
        rule_y = 19
        status_baseline = self.height - 2

        self._draw_side(canvas, game.away.abbrev, game.away.score, 0, half, score_baseline)
        self._draw_side(canvas, game.home.abbrev, game.home.score, half, half, score_baseline)

        self.vline(canvas, half - 1, 2, rule_y - 3, DIM)
        self.hline(canvas, 0, self.width - 1, rule_y, DIM)

        self.text_center(
            canvas,
            self.fonts.small,
            self.width // 2,
            status_baseline,
            self._status_color(game),
            game.status_label(self.tz),
        )

    def _draw_side(self, canvas: Any, abbrev: str, score: int, x0: int, span: int, y: int) -> None:
        self.text(canvas, self.fonts.large, x0 + 3, y, team_color(abbrev), abbrev)
        self.text_right(canvas, self.fonts.large, x0 + span - 3, y, WHITE, str(score))
        if self.favourite and abbrev == self.favourite:
            self.hline(canvas, x0 + 3, x0 + 3 + text_width(self.fonts.large, abbrev) - 1, y + 2, ACCENT)

    def draw_clock(self, canvas: Any, now: datetime) -> None:
        """Idle scene: the time, for when there is no hockey to show."""
        canvas.Clear()
        local = now.astimezone(self.tz)
        self.text_center(
            canvas, self.fonts.large, self.width // 2, 15, WHITE, local.strftime("%-I:%M %p")
        )
        self.text_center(
            canvas,
            self.fonts.small,
            self.width // 2,
            self.height - 2,
            SUBDUED,
            local.strftime("%a %b %-d").upper(),
        )

    def draw_message(self, canvas: Any, title: str, subtitle: str = "") -> None:
        canvas.Clear()
        if subtitle:
            self.text_center(canvas, self.fonts.medium, self.width // 2, 13, WHITE, title)
            self.text_center(
                canvas, self.fonts.small, self.width // 2, self.height - 3, SUBDUED, subtitle
            )
        else:
            self.text_center(
                canvas, self.fonts.medium, self.width // 2, self.height // 2 + 4, WHITE, title
            )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _status_color(game: Game) -> tuple[int, int, int]:
        if game.in_intermission:
            return INTERMISSION
        if game.is_live:
            return LIVE
        if game.is_final:
            return FINAL
        return PREGAME
