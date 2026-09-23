"""Drawing the scoreboard onto a matrix canvas.

The layout targets the default 128x32 chain (two 64x32 panels) but is
computed from the canvas size, so a 64x32 or 128x64 panel still renders
sensibly -- just with less or more breathing room.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..nhl.models import Game, StandingsRow
from .fonts import FontSet, text_width
from .logos import Logo, LogoLibrary
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
        logos: LogoLibrary | None = None,
    ) -> None:
        self.g = graphics
        self.fonts = fonts
        self.width = width
        self.height = height
        self.tz = tz
        self.logos = logos
        self._colors: dict[tuple[int, int, int], Any] = {}

    # -- primitives ------------------------------------------------------

    def color(self, rgb: tuple[int, int, int]) -> Any:
        """Cache Color objects; the backend allocates on construction."""
        if rgb not in self._colors:
            self._colors[rgb] = self.g.Color(*rgb)
        return self._colors[rgb]

    def text(
        self, canvas: Any, font: Any, x: int, y: int, rgb: tuple[int, int, int], s: str
    ) -> int:
        return self.g.DrawText(canvas, font, x, y, self.color(rgb), s)

    def text_right(self, canvas: Any, font: Any, right: int, y: int, rgb, s: str) -> int:
        return self.text(canvas, font, right - text_width(font, s), y, rgb, s)

    def text_center(self, canvas: Any, font: Any, cx: int, y: int, rgb, s: str) -> int:
        return self.text(canvas, font, cx - text_width(font, s) // 2, y, rgb, s)

    def hline(self, canvas: Any, x0: int, x1: int, y: int, rgb: tuple[int, int, int]) -> None:
        self.g.DrawLine(canvas, x0, y, x1, y, self.color(rgb))

    def vline(self, canvas: Any, x: int, y0: int, y1: int, rgb: tuple[int, int, int]) -> None:
        self.g.DrawLine(canvas, x, y0, x, y1, self.color(rgb))

    def draw_logo(self, canvas: Any, logo: Logo, x: int, y: int) -> None:
        for dx, dy, (r, g, b) in logo.pixels:
            canvas.SetPixel(x + dx, y + dy, r, g, b)

    # -- scenes ----------------------------------------------------------

    def draw_game(self, canvas: Any, game: Game) -> None:
        """Logos flanking the scores when both are available, else text."""
        if self.logos is not None:
            away = self.logos.get(game.away.abbrev)
            home = self.logos.get(game.home.abbrev)
            if away is not None and home is not None:
                self._draw_game_with_logos(canvas, game, away, home)
                return
        self._draw_game_text(canvas, game)

    def _draw_game_with_logos(self, canvas: Any, game: Game, away: Logo, home: Logo) -> None:
        """``[logo] 3   2 [logo]`` with the status line under the scores.

        Logos take the full panel height at each edge; everything else lives
        in the column between them.
        """
        canvas.Clear()
        score_baseline = 13
        # One extra blank row above the PP/SOG line (#70) beyond the row
        # PR #42 already added, so it centers better in the gap before the
        # status line rather than sitting right under the scores.
        rule_y = 20
        status_baseline = self.height - 2

        self.draw_logo(canvas, away, 0, (self.height - away.height) // 2)
        self.draw_logo(canvas, home, self.width - home.width, (self.height - home.height) // 2)

        left = away.width
        right = self.width - home.width
        span = right - left
        quarter = span // 4
        centre = left + span // 2

        self._draw_score(canvas, game.away.abbrev, game.away.score, left + quarter, score_baseline)
        self._draw_score(canvas, game.home.abbrev, game.home.score, right - quarter, score_baseline)

        self.vline(canvas, centre - 1, 3, score_baseline, DIM)
        self._draw_situation(canvas, game, left + 3, right - 4, rule_y)
        self.text_center(
            canvas,
            self.fonts.small,
            centre,
            status_baseline,
            self._status_color(game),
            game.status_label(self.tz),
        )

    def _draw_situation(self, canvas: Any, game: Game, x0: int, x1: int, baseline: int) -> None:
        """Power play / empty net indicator, or shots on goal as a fallback (#70).

        Always draws something -- TeamSide.sog is always present (defaults
        to 0, straight from the same score feed already polled every
        cycle), so there's no "nothing to show" case left the way there
        was before SOG existed; the plain rule this band used to fall
        back to is unreachable now and was removed from both callers.

        PP/EN always wins when present -- a penalty needs the room, SOG can
        wait. 4-on-4 arrives as a Situation but carries neither code (see
        Situation.indicator_side), so it falls through to SOG same as even
        strength. PP/EN drawn in the tiny font, amber, aligned to the side
        of the team it applies to; SOG in the same font, plain white and
        centred, so it doesn't compete for attention with the indicator
        colour.
        """
        font = self.fonts.tiny
        situation = game.situation
        if situation is not None:
            side = situation.indicator_side()
            label = situation.label()
            if side is not None and label:
                if side == "away":
                    self.text(canvas, font, x0, baseline, ACCENT, label)
                else:
                    self.text_right(canvas, font, x1 + 1, baseline, ACCENT, label)
                return
        self.text_center(
            canvas,
            font,
            (x0 + x1) // 2,
            baseline,
            WHITE,
            f"SOG {game.away.sog}-{game.home.sog}",
        )

    def _draw_score(self, canvas: Any, abbrev: str, score: int, cx: int, y: int) -> None:
        text = str(score)
        width = text_width(self.fonts.large, text)
        x = cx - width // 2
        self.text(canvas, self.fonts.large, x, y, WHITE, text)

    def _draw_game_text(self, canvas: Any, game: Game) -> None:
        """Fallback when a logo is missing: abbreviation and score per side."""
        canvas.Clear()
        half = self.width // 2
        score_baseline = 13
        # One extra blank row above the PP/SOG line (#70), matching
        # _draw_game_with_logos.
        rule_y = 20
        status_baseline = self.height - 2

        self._draw_side(canvas, game.away.abbrev, game.away.score, 0, half, score_baseline)
        self._draw_side(canvas, game.home.abbrev, game.home.score, half, half, score_baseline)

        self.vline(canvas, half - 1, 2, rule_y - 3, DIM)
        self._draw_situation(canvas, game, 3, self.width - 4, rule_y)

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

    def draw_goal(self, canvas: Any, game: Game) -> None:
        """A goal celebration: GOAL in big amber type, current score below.

        Fires only for the favourite's own goal (the app never calls this
        otherwise), so there is no separate "who scored" to thread through --
        the whole frame is the celebration, not a variant of the normal one.
        """
        if self.logos is not None:
            away = self.logos.get(game.away.abbrev)
            home = self.logos.get(game.home.abbrev)
            if away is not None and home is not None:
                self._draw_goal_with_logos(canvas, game, away, home)
                return
        self._draw_goal_text(canvas, game)

    def _draw_goal_with_logos(self, canvas: Any, game: Game, away: Logo, home: Logo) -> None:
        canvas.Clear()
        goal_baseline = 13
        score_baseline = self.height - 3

        self.draw_logo(canvas, away, 0, (self.height - away.height) // 2)
        self.draw_logo(canvas, home, self.width - home.width, (self.height - home.height) // 2)

        left, right = away.width, self.width - home.width
        centre = (left + right) // 2
        self.text_center(canvas, self.fonts.large, centre, goal_baseline, ACCENT, "GOAL")
        self.text_center(
            canvas,
            self.fonts.small,
            centre,
            score_baseline,
            WHITE,
            f"{game.away.score}-{game.home.score}",
        )

    def _draw_goal_text(self, canvas: Any, game: Game) -> None:
        canvas.Clear()
        goal_baseline = 13
        score_baseline = self.height - 3
        self.text_center(canvas, self.fonts.large, self.width // 2, goal_baseline, ACCENT, "GOAL")
        matchup = f"{game.away.abbrev} {game.away.score}-{game.home.score} {game.home.abbrev}"
        self.text_center(canvas, self.fonts.small, self.width // 2, score_baseline, WHITE, matchup)

    def draw_preview(self, canvas: Any, game: Game, now: datetime) -> None:
        """The favourite's next game: who, which day, what time."""
        self._draw_upcoming(
            canvas, game, top=game.day_label(now, self.tz), bottom=game.start_label(self.tz)
        )

    def draw_countdown(self, canvas: Any, game: Game, now: datetime) -> None:
        """Same frame as the preview, but the clock is running."""
        self._draw_upcoming(
            canvas,
            game,
            top=game.start_label(self.tz),
            bottom=game.countdown_label(now),
            bottom_color=ACCENT,
        )

    def _draw_upcoming(
        self,
        canvas: Any,
        game: Game,
        top: str,
        bottom: str,
        bottom_color: tuple[int, int, int] = WHITE,
    ) -> None:
        canvas.Clear()
        rule_y = 19
        top_baseline = 12
        bottom_baseline = self.height - 2

        away = home = None
        if self.logos is not None:
            away, home = self.logos.get(game.away.abbrev), self.logos.get(game.home.abbrev)

        if away is not None and home is not None:
            self.draw_logo(canvas, away, 0, (self.height - away.height) // 2)
            self.draw_logo(canvas, home, self.width - home.width, (self.height - home.height) // 2)
            left, right = away.width, self.width - home.width
            centre = (left + right) // 2
            self.text_center(canvas, self.fonts.medium, centre, top_baseline, WHITE, top)
            self.hline(canvas, left + 3, right - 4, rule_y, DIM)
            self.text_center(
                canvas, self.fonts.small, centre, bottom_baseline, bottom_color, bottom
            )
            return

        # No artwork: the matchup itself becomes the top line, and the day
        # joins the bottom line when the two fit side by side.
        self._draw_matchup(canvas, game, top_baseline + 1)
        self.hline(canvas, 0, self.width - 1, rule_y, DIM)
        combined = f"{top} {bottom}"
        fits = text_width(self.fonts.small, combined) <= self.width - 4
        self.text_center(
            canvas,
            self.fonts.small,
            self.width // 2,
            bottom_baseline,
            bottom_color,
            combined if fits else bottom,
        )

    def _draw_matchup(self, canvas: Any, game: Game, y: int) -> None:
        """``NSH @ TBL`` in the large face, each abbreviation in its colour."""
        font = self.fonts.large
        parts = (
            (game.away.abbrev, team_color(game.away.abbrev)),
            (" @ ", SUBDUED),
            (game.home.abbrev, team_color(game.home.abbrev)),
        )
        x = self.width // 2 - sum(text_width(font, t) for t, _ in parts) // 2
        for text, color in parts:
            x += self.text(canvas, font, x, y, color, text)

    #: Column offsets relative to the content area's left edge (past the
    #: favourite's logo, when there is one), so values of different widths
    #: (a 1- vs 2-digit rank, a 5- vs 7-char W-L-OT record) still line up
    #: between rows instead of drifting with their own width.
    _STANDINGS_RANK_DX = 2
    _STANDINGS_ABBREV_DX = 13
    _STANDINGS_RECORD_DX = 29
    #: Right edges are measured from the panel's own right edge instead,
    #: since they don't move when a logo appears on the left.
    _STANDINGS_GP_RIGHT_PAD = 20
    _STANDINGS_POINTS_RIGHT_PAD = 1

    def draw_standings(self, canvas: Any, rows: Sequence[StandingsRow], favourite: str) -> None:
        """The favourite's conference neighbourhood: logo, rank, abbrev, record, GP, points.

        The favourite's own logo anchors the left edge -- full panel height,
        same treatment as the game scene -- freeing the row content to widen
        into a games-played column that a bare table had no room for. Falls
        back to no logo (columns shifted flush left) if the library has none
        for the favourite, same fallback precedent as the game scene's text
        layout. One row per team, tightest face (``4x6``) so up to five rows
        fit the panel height.
        """
        canvas.Clear()
        font = self.fonts.tiny
        row_height = 6

        logo = self.logos.get(favourite) if self.logos is not None else None
        if logo is not None:
            self.draw_logo(canvas, logo, 0, (self.height - logo.height) // 2)
            left = logo.width
        else:
            left = 0

        rank_x = left + self._STANDINGS_RANK_DX
        abbrev_x = left + self._STANDINGS_ABBREV_DX
        record_x = left + self._STANDINGS_RECORD_DX
        gp_right = self.width - self._STANDINGS_GP_RIGHT_PAD
        points_right = self.width - self._STANDINGS_POINTS_RIGHT_PAD

        for i, row in enumerate(rows):
            y = 1 + i * row_height + (row_height - 2)
            color = ACCENT if row.abbrev == favourite else WHITE
            self.text(canvas, font, rank_x, y, color, f"{row.conference_sequence:>2}")
            self.text(canvas, font, abbrev_x, y, team_color(row.abbrev), row.abbrev)
            self.text(canvas, font, record_x, y, color, row.record_label())
            self.text_right(canvas, font, gp_right, y, color, str(row.games_played))
            self.text_right(canvas, font, points_right, y, color, str(row.points))

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
